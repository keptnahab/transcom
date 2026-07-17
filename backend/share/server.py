from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import PurePosixPath
import secrets
import socket
import threading
from urllib.parse import parse_qs, urlparse

import backend.config as cfg


VIEWER_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TransCom Live</title>
<style>
body{margin:0;background:#0f1018;color:#e9ecf4;font:14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}
header{position:sticky;top:0;background:#171a24;border-bottom:1px solid #2b3040;padding:12px 14px;display:flex;justify-content:space-between;gap:12px}
main{padding:10px 0}.row{display:grid;grid-template-columns:72px 112px 1fr;gap:10px;padding:8px 14px;border-left:4px solid transparent}
.ts,.speaker{color:#8d96ad;font-variant-numeric:tabular-nums}.text{line-height:1.45}.empty{padding:32px 14px;color:#8d96ad}
.confirm{display:inline-block;margin-right:7px;border:1px solid #f9c74f;border-radius:3px;color:#f9c74f;font-size:9px;padding:1px 4px}.confirmed{border-color:#70c1b3;color:#70c1b3}
.command{display:inline-block;margin-right:7px;border:1px solid #2f9e9b;border-radius:3px;color:#37b6a8;font-size:9px;padding:1px 4px}
.raw{display:block;margin-top:2px;color:#8d96ad;font:10px ui-monospace,SFMono-Regular,Menlo,monospace}
@media(max-width:620px){.row{grid-template-columns:56px 1fr}.speaker{grid-column:2}.text{grid-column:2}}
</style></head><body>
<header><strong>TransCom Live</strong><span id="status">Connecting</span></header><main id="rows"><div class="empty">Waiting for transcript...</div></main>
<script>
const token = new URLSearchParams(location.search).get('token');
const rows = document.getElementById('rows');
const status = document.getElementById('status');
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function ts(v){return new Date(v*1000).toTimeString().slice(0,8)}
async function poll(){
  try {
    const r = await fetch('/api/segments?token=' + encodeURIComponent(token || ''));
    if (!r.ok) throw new Error('denied');
    const data = await r.json();
    status.textContent = data.live ? 'Live' : 'Paused';
    rows.innerHTML = data.segments.length ? data.segments.map(s =>
      `<div class="row" style="border-left-color:${esc(s.speaker_color || '#5865f2')}"><span class="ts">${ts(s.timestamp)}</span><span class="speaker">${esc(s.speaker_name || 'Unknown')}</span><span class="text"${s.raw_text && s.raw_text !== s.text ? ` title="Roh erkannt: ${esc(s.raw_text)}"` : ''}>${s.requires_confirmation ? `<span class="confirm ${s.confirmation_acknowledged ? 'confirmed' : ''}">${s.confirmation_acknowledged ? 'BESTÄTIGT' : 'PRÜFEN'}</span>` : ''}${s.safety_command_id ? '<span class="command">BEFEHL</span>' : ''}${esc(s.text)}${s.raw_text && s.raw_text !== s.text ? `<small class="raw">Roh erkannt: ${esc(s.raw_text)}</small>` : ''}${s.safety_confirmation_used ? `<small class="raw">Zweitprüfung (${esc(s.safety_confirmation_model || 'unbekannt')}): ${esc(s.safety_confirmation_raw_text || '')}</small>` : ''}</span></div>`
    ).join('') : '<div class="empty">Waiting for transcript...</div>';
  } catch(e) { status.textContent = 'Disconnected'; }
}
poll(); setInterval(poll, 1500);
</script></body></html>"""


class ShareServer:
    """Small token-protected read-only LAN viewer."""

    def __init__(self, store_provider) -> None:
        self._store_provider = store_provider
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._token: str | None = None
        self._url: str | None = None

    def start(self) -> dict:
        if self._httpd is not None:
            return self.state()
        self._token = secrets.token_urlsafe(18)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                token = params.get("token", [""])[0]
                if parsed.path == "/api/segments":
                    if token != owner._token:
                        self.send_error(403)
                        return
                    payload = {
                        "live": True,
                        "segments": owner._store_provider().get_all()[-300:],
                    }
                    self._send_json(payload)
                    return
                if PurePosixPath(parsed.path).as_posix() == "/":
                    if token != owner._token:
                        self.send_error(403)
                        return
                    self._send_html(VIEWER_HTML)
                    return
                self.send_error(404)

            def log_message(self, fmt, *args):
                return

            def _send_json(self, payload):
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _send_html(self, html):
                raw = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._httpd = ThreadingHTTPServer((cfg.SHARE_HOST, cfg.SHARE_PORT), Handler)
        host = self._lan_host()
        self._url = f"http://{host}:{cfg.SHARE_PORT}/?token={self._token}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="share-server")
        self._thread.start()
        return self.state()

    def stop(self) -> dict:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._httpd = None
        self._thread = None
        self._token = None
        self._url = None
        return self.state()

    def state(self) -> dict:
        return {
            "enabled": self._httpd is not None,
            "url": self._url,
            "token": self._token,
            "port": cfg.SHARE_PORT,
        }

    def _lan_host(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"
