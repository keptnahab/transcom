from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .review_core import (
    ReviewError,
    append_decision,
    clip_binding,
    clip_id,
    completion_summary,
    display_reference,
    latest_decisions,
    load_manifest,
    load_profiles,
    read_and_validate_log,
    verify_audio_binding,
)


MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT_ROOT = MODULE_DIR.parents[1]
DEFAULT_PROFILES = MODULE_DIR / "profiles_v1.json"
STATIC_DIR = MODULE_DIR / "static"


def is_same_local_origin(host: str | None, origin: str | None) -> bool:
    return bool(host) and origin == f"http://{host}"


def session_payload(loaded) -> dict:
    _, events = read_and_validate_log(loaded)
    latest = latest_decisions(events)
    items = []
    for index, clip in enumerate(loaded.clips):
        event = latest.get(index)
        binding = clip_binding(clip, index)
        items.append(
            {
                "index": index,
                "clip_id": clip_id(clip, index),
                "reference_text": display_reference(clip),
                "binding_short": binding["clip_sha256"][:12],
                "audio_url": f"/api/audio?index={index}",
                "decision": event["decision"] if event else None,
                "note": event["note"] if event else "",
                "reviewer_id": event["reviewer_id"] if event else None,
                "reviewed_at_utc": event["reviewed_at_utc"] if event else None,
            }
        )
    return {
        "profile": {
            "id": loaded.profile.profile_id,
            "label": loaded.profile.label,
            "group": loaded.profile.group,
            "split": loaded.profile.split,
            "source_manifest_sha256": loaded.source_sha256,
        },
        "summary": completion_summary(loaded, events),
        "items": items,
    }


def make_handler(loaded, project_root: Path):
    class ReviewHandler(BaseHTTPRequestHandler):
        server_version = "TransComManualReview/1"

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "media-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'",
            )
            self.send_header("Cache-Control", "no-store")

        def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, status: int, payload: dict) -> None:
            self._send_bytes(
                status,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _error(self, status: int, message: str) -> None:
            self._send_json(status, {"error": message})

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/session":
                    current = load_manifest(loaded.profile)
                    if current.source_sha256 != loaded.source_sha256:
                        raise ReviewError("Source manifest changed; restart the review server")
                    self._send_json(HTTPStatus.OK, session_payload(current))
                    return
                if parsed.path == "/api/audio":
                    raw_index = parse_qs(parsed.query).get("index", [None])[0]
                    if raw_index is None:
                        raise ReviewError("Missing audio index")
                    index = int(raw_index)
                    current = load_manifest(loaded.profile)
                    if current.source_sha256 != loaded.source_sha256:
                        raise ReviewError("Source manifest changed; restart the review server")
                    audio_path, _ = verify_audio_binding(current, project_root, index)
                    content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
                    self._send_bytes(HTTPStatus.OK, audio_path.read_bytes(), content_type)
                    return
                static_name = "index.html" if parsed.path == "/" else parsed.path.removeprefix("/")
                if static_name not in {"index.html", "app.js", "styles.css"}:
                    self._error(HTTPStatus.NOT_FOUND, "Not found")
                    return
                static_path = STATIC_DIR / static_name
                content_type = mimetypes.guess_type(static_name)[0] or "application/octet-stream"
                if content_type.startswith("text/") or content_type == "application/javascript":
                    content_type += "; charset=utf-8"
                self._send_bytes(HTTPStatus.OK, static_path.read_bytes(), content_type)
            except (ReviewError, ValueError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except OSError as exc:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Local file error: {exc}")

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            if parsed.path != "/api/decision":
                self._error(HTTPStatus.NOT_FOUND, "Not found")
                return
            try:
                host = self.headers.get("Host")
                origin = self.headers.get("Origin")
                if not is_same_local_origin(host, origin):
                    raise ReviewError("Decision request must originate from this local review page")
                raw_length = self.headers.get("Content-Length")
                if raw_length is None:
                    raise ReviewError("Missing request length")
                length = int(raw_length)
                if length < 1 or length > 8192:
                    raise ReviewError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ReviewError("Decision request must be an object")
                current = load_manifest(loaded.profile)
                if current.source_sha256 != loaded.source_sha256:
                    raise ReviewError("Source manifest changed; restart the review server")
                event = append_decision(
                    current,
                    project_root,
                    index=body.get("index"),
                    decision=body.get("decision", ""),
                    note=body.get("note", ""),
                    reviewer_id=body.get("reviewer_id", ""),
                )
                self._send_json(
                    HTTPStatus.CREATED,
                    {
                        "event_sha256": event["event_sha256"],
                        "session": session_payload(current),
                    },
                )
            except (ReviewError, ValueError, json.JSONDecodeError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except OSError as exc:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Local file error: {exc}")

        def log_message(self, format: str, *args) -> None:
            # Keep terminal output concise; decisions are recorded in the hash-bound log.
            return

    return ReviewHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local manual audio/reference review UI")
    parser.add_argument("--profile", required=True, help="Exact profile id from profiles_v1.json")
    parser.add_argument("--host", default="127.0.0.1", help="Local bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Local port (default: 8765)")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        bind_address = ipaddress.ip_address(args.host)
    except ValueError as exc:
        raise SystemExit("--host must be a numeric loopback address") from exc
    if not bind_address.is_loopback:
        raise SystemExit("Manual review server may bind only to a loopback address")
    project_root = args.project_root.resolve()
    profiles = load_profiles(args.profiles, project_root)
    if args.profile not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown profile {args.profile!r}. Available: {choices}")
    loaded = load_manifest(profiles[args.profile])
    if loaded.profile.mode != "manual":
        raise SystemExit(
            "Derived audio is not manually reviewed. Review its canonical parent profile, "
            "then run the inheritance exporter."
        )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(loaded, project_root))
    print(f"Manual review: {loaded.profile.label}")
    print(f"Open http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop. No decision is preselected or generated automatically.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
