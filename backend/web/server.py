from __future__ import annotations

import json
import logging
import mimetypes
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import backend.config as cfg
from backend.auth import AuthService

logger = logging.getLogger(__name__)


class WebAppServer:
    def __init__(self, auth: AuthService, static_root: str | Path | None = None) -> None:
        self._auth = auth
        self._static_root = Path(static_root or cfg.PROJECT_ROOT / "renderer" / "dist")
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> dict:
        if self._server is not None:
            return self.state()

        auth = self._auth
        static_root = self._static_root

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/api/me":
                    user = auth.user_for_token(self._bearer_token())
                    if user is None:
                        self._send_json({"error": "Unauthorized"}, status=401)
                        return
                    self._send_json({"user": {"email": user["email"], "is_admin": user["is_admin"]}})
                    return
                if parsed.path == "/api/users":
                    user = auth.user_for_token(self._bearer_token())
                    if user is None:
                        self._send_json({"error": "Unauthorized"}, status=401)
                        return
                    if not user["is_admin"]:
                        self._send_json({"error": "Forbidden"}, status=403)
                        return
                    self._send_json({"users": auth.list_users()})
                    return
                self._send_static(parsed.path)

            def do_POST(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/api/login":
                    payload = self._read_json()
                    result = auth.login(payload.get("email", ""), payload.get("password", ""))
                    if result is None:
                        self._send_json({"error": "Invalid email or password"}, status=401)
                        return
                    self._send_json(result)
                    return
                if parsed.path == "/api/users":
                    user = auth.user_for_token(self._bearer_token())
                    if user is None:
                        self._send_json({"error": "Unauthorized"}, status=401)
                        return
                    if not user["is_admin"]:
                        self._send_json({"error": "Forbidden"}, status=403)
                        return
                    payload = self._read_json()
                    try:
                        created = auth.create_user(payload.get("email", ""), bool(payload.get("is_admin", False)))
                    except Exception as exc:
                        self._send_json({"error": str(exc)}, status=400)
                        return
                    self._send_json({"user": {k: v for k, v in created.items() if k != "password"}, "password": created["password"]})
                    return
                if parsed.path.startswith("/api/users/") and parsed.path.endswith("/password"):
                    user = auth.user_for_token(self._bearer_token())
                    if user is None:
                        self._send_json({"error": "Unauthorized"}, status=401)
                        return
                    if not user["is_admin"]:
                        self._send_json({"error": "Forbidden"}, status=403)
                        return
                    payload = self._read_json()
                    email = unquote(parsed.path.removeprefix("/api/users/").removesuffix("/password"))
                    try:
                        updated = auth.set_user_password(email, payload.get("password") or None)
                    except Exception as exc:
                        self._send_json({"error": str(exc)}, status=400)
                        return
                    self._send_json({"user": updated, "password": updated["password"]})
                    return
                self._send_json({"error": "Not found"}, status=404)

            def do_DELETE(self):  # noqa: N802
                parsed = urlparse(self.path)
                if not parsed.path.startswith("/api/users/"):
                    self._send_json({"error": "Not found"}, status=404)
                    return
                user = auth.user_for_token(self._bearer_token())
                if user is None:
                    self._send_json({"error": "Unauthorized"}, status=401)
                    return
                if not user["is_admin"]:
                    self._send_json({"error": "Forbidden"}, status=403)
                    return
                email = unquote(parsed.path.removeprefix("/api/users/"))
                try:
                    auth.delete_user(email)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=400)
                    return
                self._send_json({"ok": True})

            def log_message(self, fmt, *args):
                logger.debug("web app: " + fmt, *args)

            def _send_static(self, path: str) -> None:
                if path in {"", "/"}:
                    rel = "index.html"
                else:
                    rel = path.lstrip("/")
                target = (static_root / rel).resolve()
                root = static_root.resolve()
                if not str(target).startswith(str(root)) or not target.is_file():
                    target = root / "index.html"
                if not target.is_file():
                    self._send_json({"error": "Renderer build not found. Run npm run build:renderer."}, status=503)
                    return
                content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store" if target.name == "index.html" else "public, max-age=3600")
                self.end_headers()
                self.wfile.write(data)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0:
                    return {}
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except json.JSONDecodeError:
                    return {}

            def _bearer_token(self) -> str | None:
                header = self.headers.get("Authorization", "")
                if header.lower().startswith("bearer "):
                    return header[7:].strip()
                return None

            def _send_json(self, payload: dict, status: int = 200) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):  # noqa: N802
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.end_headers()

        self._server = ThreadingHTTPServer((cfg.WEB_HOST, cfg.WEB_PORT), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="web-app")
        self._thread.start()
        logger.info("Web app listening on http://%s:%d", self._lan_host(), cfg.WEB_PORT)
        return self.state()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

    def state(self) -> dict:
        return {
            "enabled": self._server is not None,
            "url": f"http://{self._lan_host()}:{cfg.WEB_PORT}",
            "port": cfg.WEB_PORT,
        }

    def _lan_host(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
