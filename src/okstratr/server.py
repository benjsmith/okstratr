"""Tiny HTTP stub on 8767: /health, /api/status, /api/seat."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from . import PORT
from . import blackboard, cos, dag, herdr, status


def _json_bytes(obj: Any, code: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(obj, indent=2, default=str).encode("utf-8") + b"\n"
    return code, body, "application/json; charset=utf-8"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # quieter stub
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            code, body, ct = _json_bytes({"ok": True, "service": "okstratr", "port": PORT})
            return self._send(code, body, ct)
        if path == "/api/status":
            snap = status.write_status()
            code, body, ct = _json_bytes(snap)
            return self._send(code, body, ct)
        code, body, ct = _json_bytes({"error": "not found", "path": path}, 404)
        self._send(code, body, ct)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        if path == "/api/seat":
            objective = str((payload or {}).get("objective") or "").strip()
            launch = bool((payload or {}).get("herdr", False))
            status.set_objective(objective)
            dag.seat_root(objective)
            if objective:
                blackboard.post(f"seated: {objective}", author="okstratr")
            plan = cos.advise(objective, blackboard.texts(5))
            herdr_result = None
            if launch and objective:
                herdr_result = herdr.launch(objective)
            snap = status.write_status()
            snap = dict(snap)
            snap["cos"] = plan
            if herdr_result is not None:
                snap["herdr_launch"] = herdr_result
            code, body, ct = _json_bytes(snap)
            return self._send(code, body, ct)
        code, body, ct = _json_bytes({"error": "not found", "path": path}, 404)
        self._send(code, body, ct)


def serve(host: str = "127.0.0.1", port: int = PORT) -> int:
    status.write_status()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"okstratr listening on http://{host}:{port}  (/health /api/status /api/seat)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()
    return 0
