"""HTTP API on 8767: health, status, seat, dag, blackboard, herdr run-ready."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import PORT
from . import blackboard, cos, dag, herdr, status

_NODE_STATE_RE = re.compile(r"^/api/dag/nodes/([^/]+)/state$")


def _json_bytes(obj: Any, code: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(obj, indent=2, default=str).encode("utf-8") + b"\n"
    return code, body, "application/json; charset=utf-8"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # quieter
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
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/health":
            code, body, ct = _json_bytes({"ok": True, "service": "okstratr", "port": PORT})
            return self._send(code, body, ct)

        if path == "/api/status":
            snap = status.write_status()
            code, body, ct = _json_bytes(snap)
            return self._send(code, body, ct)

        if path == "/api/dag":
            g = dag.default_dag()
            g.refresh_ready()
            code, body, ct = _json_bytes(g.summary())
            return self._send(code, body, ct)

        if path == "/api/blackboard":
            n = 20
            if "n" in qs:
                try:
                    n = int(qs["n"][0])
                except (ValueError, IndexError):
                    n = 20
            kind = (qs.get("kind") or [None])[0]
            q = (qs.get("q") or [None])[0]
            if kind:
                items = blackboard.by_kind(kind)
            elif q:
                items = blackboard.search(q)
            else:
                items = blackboard.head(n)
            payload = {"summary": blackboard.summary(), "items": items}
            code, body, ct = _json_bytes(payload)
            return self._send(code, body, ct)

        code, body, ct = _json_bytes({"error": "not found", "path": path}, 404)
        self._send(code, body, ct)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        if path == "/api/seat":
            objective = str(payload.get("objective") or "").strip()
            launch = bool(payload.get("herdr", False))
            reset = bool(payload.get("reset", False))
            want_cos = payload.get("cos")
            status.set_objective(objective)
            dag.seat_root(objective, reset=reset)
            if objective:
                blackboard.post(f"seated: {objective}", author="okstratr", kind="note")

            g = dag.default_dag()
            if want_cos is None:
                do_cos = cos.should_auto_break(g) and bool(objective)
            else:
                do_cos = bool(want_cos) and bool(objective)

            cos_result = None
            if do_cos:
                cos_result = cos.break_down(objective)
                plan = cos_result.get("plan") or cos.advise(objective, blackboard.texts(5))
            else:
                plan = cos.advise(objective, blackboard.texts(5))

            herdr_result = None
            if launch and objective:
                herdr_result = herdr.launch(objective)
            snap = status.write_status()
            snap = dict(snap)
            snap["cos"] = plan
            if cos_result is not None:
                snap["cos_break"] = {
                    "created": cos_result.get("created"),
                    "updated": cos_result.get("updated"),
                    "ready": cos_result.get("ready"),
                    "idempotent": cos_result.get("idempotent"),
                }
            if herdr_result is not None:
                snap["herdr_launch"] = herdr_result
            code, body, ct = _json_bytes(snap)
            return self._send(code, body, ct)

        if path == "/api/cos/break":
            objective = str(payload.get("objective") or "").strip() or status.get_objective()
            result = cos.break_down(objective)
            status.write_status()
            code, body, ct = _json_bytes(result)
            return self._send(code, body, ct)

        if path == "/api/herdr/run-ready":
            limit = payload.get("limit", 1)
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = 1
            dry = payload.get("dry_run")
            if dry is None:
                dry_run = None  # honor OKSTRATR_HERDR_DRY_RUN
            else:
                dry_run = bool(dry)
            result = herdr.run_ready(limit=limit, dry_run=dry_run)
            code, body, ct = _json_bytes(result)
            return self._send(code, body, ct)

        if path == "/api/dag/nodes":
            node_id = str(payload.get("id") or "").strip()
            title = str(payload.get("title") or node_id).strip()
            if not node_id:
                code, body, ct = _json_bytes({"error": "id required"}, 400)
                return self._send(code, body, ct)
            depends = payload.get("depends_on") or payload.get("depends") or []
            if isinstance(depends, str):
                depends = [d.strip() for d in depends.replace(" ", ",").split(",") if d.strip()]
            g = dag.default_dag()
            try:
                node = g.add(
                    node_id,
                    title,
                    depends_on=list(depends),
                    kind=payload.get("kind"),
                    objective=str(payload.get("objective") or ""),
                    notes=str(payload.get("notes") or ""),
                    state=payload.get("state"),
                )
            except Exception as e:  # noqa: BLE001
                code, body, ct = _json_bytes({"error": str(e)}, 400)
                return self._send(code, body, ct)
            status.write_status()
            code, body, ct = _json_bytes(node.to_dict())
            return self._send(code, body, ct)

        m = _NODE_STATE_RE.match(path)
        if m:
            node_id = m.group(1)
            new_state = str(payload.get("state") or "").strip()
            notes = payload.get("notes")
            g = dag.default_dag()
            try:
                if new_state == "done":
                    node = g.mark_done(node_id, notes=notes if notes is not None else None)
                elif new_state == "failed":
                    node = g.mark_failed(node_id, notes=notes if notes is not None else None)
                else:
                    node = g.set_state(node_id, new_state)
                    if notes is not None:
                        node.notes = str(notes)
                        g.save()
            except KeyError as e:
                code, body, ct = _json_bytes({"error": str(e)}, 404)
                return self._send(code, body, ct)
            except ValueError as e:
                code, body, ct = _json_bytes({"error": str(e)}, 400)
                return self._send(code, body, ct)
            status.write_status()
            code, body, ct = _json_bytes(node.to_dict())
            return self._send(code, body, ct)

        if path == "/api/blackboard":
            text = str(payload.get("text") or "").strip()
            if not text:
                code, body, ct = _json_bytes({"error": "text required"}, 400)
                return self._send(code, body, ct)
            tags = payload.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            entry = blackboard.post(
                text,
                author=str(payload.get("author") or "human"),
                kind=str(payload.get("kind") or "note"),
                tags=list(tags),
                provenance=str(payload.get("provenance") or ""),
                node_id=payload.get("node_id"),
            )
            status.write_status()
            code, body, ct = _json_bytes(entry)
            return self._send(code, body, ct)

        code, body, ct = _json_bytes({"error": "not found", "path": path}, 404)
        self._send(code, body, ct)


def serve(host: str = "127.0.0.1", port: int = PORT) -> int:
    status.write_status()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(
        f"okstratr listening on http://{host}:{port}  "
        "(/health /api/status /api/seat /api/dag /api/blackboard "
        "/api/cos/break /api/herdr/run-ready)"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()
    return 0
