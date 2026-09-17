"""HTTP API on 8767: health, status, desk, seat (alias), dag, blackboard, herdr."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import PORT
from . import blackboard, cos, dag, desks, herdr, herdr_jobs, okbay, roles, status, web_egress

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

        if path == "/api/desk/status":
            code, body, ct = _json_bytes(desks.status_snapshot())
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

        if path == "/api/web":
            code, body, ct = _json_bytes(web_egress.status())
            return self._send(code, body, ct)

        if path in ("/api/workspaces", "/api/workspace/list"):
            code, body, ct = _json_bytes(okbay.list_workspaces())
            return self._send(code, body, ct)

        if path in ("/api/config/roles", "/api/roles/config"):
            code, body, ct = _json_bytes(roles.load_role_config())
            return self._send(code, body, ct)

        if path in ("/api/herdr/job", "/api/herdr/jobs"):
            qs_id = (qs.get("id") or [None])[0]
            job = herdr_jobs.get_job(str(qs_id) if qs_id else None)
            payload = {"ok": True, "herdr_job": job, "last_error": herdr_jobs.last_error()}
            code, body, ct = _json_bytes(payload)
            return self._send(code, body, ct)


        if path in ("/api/harness", "/api/harness/list", "/api/config/harness"):
            from .harness import config as harness_config

            code, body, ct = _json_bytes(harness_config.list_for_api())
            return self._send(code, body, ct)

        if path == "/api/desk_session":
            from . import desk_session as desk_session_mod

            code, body, ct = _json_bytes(desk_session_mod.snapshot())
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

        if path in ("/api/desk/start", "/api/seat"):
            objective = str(payload.get("objective") or "").strip()
            launch = bool(payload.get("herdr", False))
            # Panel Start with objective sets drive_herdr; API/CLI default False (plan-only quiet).
            drive_herdr = bool(payload.get("drive_herdr", False))
            reset = bool(payload.get("reset", False))
            kind = payload.get("kind")
            kind = str(kind).strip() if kind else None
            effort = payload.get("effort")
            try:
                effort_f = float(effort) if effort is not None else None
            except (TypeError, ValueError):
                effort_f = None
            want_cos = payload.get("cos")
            run_cos = True if want_cos is None else bool(want_cos)
            ws_id = (
                payload.get("okbay_workspace_id")
                or payload.get("workspace_id")
                or payload.get("workspace")
            )
            ws_id = str(ws_id).strip() if ws_id else None
            herdr_limit = payload.get("herdr_limit", payload.get("limit", 4))
            try:
                herdr_limit = max(0, int(herdr_limit))
            except (TypeError, ValueError):
                herdr_limit = 4
            # /api/seat is deprecated alias → desk start auto
            if path == "/api/seat" and not kind:
                kind = "auto"
            result = desks.start(
                objective,
                kind=kind,
                reset=reset,
                effort=effort_f,
                run_cos=run_cos and bool(objective),
                okbay_workspace_id=ws_id,
                drive_herdr=drive_herdr,
            )
            snap = status.write_status()
            snap = dict(snap)
            snap["desk"] = result
            # Backward-compatible CoS fields for callers still expecting seat shape
            from . import cos as cos_mod

            plan = cos_mod.advise(objective, blackboard.texts(5)) if objective else cos_mod.advise("")
            snap["cos"] = plan
            g = dag.default_dag(force_reload=True)
            child_ids = [n for n in g.nodes if n != "root"]
            if child_ids:
                snap["cos_break"] = {
                    "created": child_ids,
                    "updated": [],
                    "ready": [n for n in child_ids if g.nodes[n].state == "ready"],
                    "idempotent": False,
                }
            if path == "/api/seat":
                snap["deprecated"] = "seat"
                snap["warning"] = "Use POST /api/desk/start; /api/seat aliases desk start auto"
            # Drive seats after CoS when requested (UI Start with effective objective).
            # Empty query may resume a quiet desk — use that desk's standing objective.
            desk_obj = str((result.get("desk") or {}).get("objective") or "").strip()
            effective_objective = objective or desk_obj
            if drive_herdr and not objective and desk_obj:
                # Resumed quiet desk with empty query: keep objective (already on desk).
                objective = desk_obj
                snap["objective"] = desk_obj
            if drive_herdr and effective_objective:
                dry = payload.get("dry_run")
                dry_run = None if dry is None else bool(dry)
                desk_id = (result.get("desk") or {}).get("id")
                # Non-blocking: kick background thread; HTTP returns immediately.
                kicked = herdr_jobs.kick_run_ready(
                    desk_id=str(desk_id) if desk_id else None,
                    limit=herdr_limit,
                    dry_run=dry_run,
                )
                snap["herdr_job"] = kicked.get("herdr_job")
                if not kicked.get("ok"):
                    snap["ok"] = False
                    snap["error"] = kicked.get("error") or "Herdr drive already running"
                    snap["message"] = kicked.get("message") or snap["error"]
                    # Desk was already started/resumed; leave it — caller can Stop.
                else:
                    snap["message"] = kicked.get("message") or (
                        "Desk started; Herdr drive running in background."
                    )
                    # Keep desk working while job runs (start already set working when drive_herdr).
                    try:
                        reg = desks.default_registry(force_reload=True)
                        updated = dict(result)
                        if desk_id and desk_id in reg.desks:
                            updated["desk"] = reg.desks[desk_id].to_dict()
                        snap["desk"] = updated
                    except Exception:  # noqa: BLE001
                        snap["desk"] = result
                # Refresh status without dropping desk / herdr_job / message.
                fresh = status.write_status()
                for key, val in fresh.items():
                    if key not in (
                        "desk",
                        "herdr_run",
                        "herdr_job",
                        "herdr_error",
                        "message",
                        "cos",
                        "cos_break",
                        "ok",
                        "error",
                    ):
                        snap[key] = val
                # Surface active job + any prior error from jobs module.
                job_snap = herdr_jobs.snapshot_for_status()
                if job_snap:
                    snap["herdr_job"] = snap.get("herdr_job") or job_snap
                err = herdr_jobs.last_error()
                if err and not snap.get("herdr_error"):
                    snap["herdr_error"] = err
            if launch and objective:
                snap["herdr_launch"] = herdr.launch(objective)
            code, body, ct = _json_bytes(snap)
            return self._send(code, body, ct)

        if path == "/api/desk/stop":
            desk_id = payload.get("desk_id") or payload.get("id")
            code, body, ct = _json_bytes(desks.stop(str(desk_id) if desk_id else None))
            return self._send(code, body, ct)

        if path in ("/api/desk/quiet_standing", "/api/desk/quiet-all"):
            code, body, ct = _json_bytes(desks.quiet_standing())
            return self._send(code, body, ct)

        if path == "/api/desk/dedupe_kind":
            kind = payload.get("kind")
            code, body, ct = _json_bytes(
                desks.dedupe_kind(str(kind) if kind else None)
            )
            return self._send(code, body, ct)

        if path == "/api/desk/dismiss":
            desk_id = payload.get("desk_id") or payload.get("id")
            code, body, ct = _json_bytes(desks.dismiss(str(desk_id) if desk_id else None))
            return self._send(code, body, ct)

        if path == "/api/desk/delete":
            desk_id = payload.get("desk_id") or payload.get("id")
            force = bool(payload.get("force", False))
            cleanup = True if payload.get("cleanup") is None else bool(payload.get("cleanup"))
            code, body, ct = _json_bytes(
                desks.delete(
                    str(desk_id) if desk_id else None,
                    force=force,
                    cleanup=cleanup,
                )
            )
            return self._send(code, body, ct)

        if path == "/api/desk/schedule":
            desk_id = payload.get("desk_id") or payload.get("id")
            spec = payload.get("spec") or payload.get("schedule") or payload.get("args")
            if isinstance(spec, list):
                args = [str(x) for x in spec]
            elif isinstance(spec, str):
                args = spec
            else:
                args = []
            code, body, ct = _json_bytes(
                desks.schedule(args, desk_id=str(desk_id) if desk_id else None)
            )
            return self._send(code, body, ct)

        if path == "/api/desk/status":
            code, body, ct = _json_bytes(desks.status_snapshot())
            return self._send(code, body, ct)

        if path == "/api/desk/hire":
            desk_id = payload.get("desk_id")
            code, body, ct = _json_bytes(
                desks.hire(payload, desk_id=str(desk_id) if desk_id else None)
            )
            return self._send(code, body, ct)

        if path == "/api/desk/retire":
            node_id = str(payload.get("node_id") or payload.get("id") or "").strip()
            desk_id = payload.get("desk_id")
            code, body, ct = _json_bytes(
                desks.retire_worker(node_id, desk_id=str(desk_id) if desk_id else None)
            )
            return self._send(code, body, ct)

        if path == "/api/desk/focus":
            desk_id = payload.get("desk_id") or payload.get("id")
            code, body, ct = _json_bytes(desks.focus(str(desk_id) if desk_id else None))
            return self._send(code, body, ct)

        if path == "/api/cos/break":
            objective = str(payload.get("objective") or "").strip() or status.get_objective()
            result = cos.break_down(objective)
            status.write_status()
            code, body, ct = _json_bytes(result)
            return self._send(code, body, ct)

        if path == "/api/herdr/launch":
            # Same process as `okstratr serve` — PATH includes ~/.local/bin when daemon
            # was started from a normal user session (unlike Quickshell execDetached).
            objective = str(payload.get("objective") or "").strip()
            result = herdr.focus(objective)
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

        if path == "/api/desk/effort":
            desk_id = payload.get("desk_id") or payload.get("id")
            value = payload.get("effort", payload.get("value"))
            if value is None:
                code, body, ct = _json_bytes({"error": "effort required (0..1)"}, 400)
                return self._send(code, body, ct)
            code, body, ct = _json_bytes(
                desks.set_effort(value, desk_id=str(desk_id) if desk_id else None)
            )
            return self._send(code, body, ct)

        if path == "/api/web":
            action = str(payload.get("action") or payload.get("mode") or "").strip().lower()
            if action in ("status", "get", ""):
                code, body, ct = _json_bytes(web_egress.status())
                return self._send(code, body, ct)
            if action in ("off", "revoke"):
                code, body, ct = _json_bytes(web_egress.revoke())
                return self._send(code, body, ct)
            if action in ("on", "once", "session"):
                mode = "session" if action == "on" else action
                if payload.get("once"):
                    mode = "once"
                elif payload.get("session"):
                    mode = "session"
                code, body, ct = _json_bytes(web_egress.set_mode(mode))
                return self._send(code, body, ct)
            code, body, ct = _json_bytes(
                {"error": "action must be on|off|once|session|status", "got": action},
                400,
            )
            return self._send(code, body, ct)

        if path in ("/api/workspace/select", "/api/workspaces/select"):
            ws_id = (
                payload.get("id")
                or payload.get("workspace_id")
                or payload.get("workspace")
                or payload.get("name")
                or ""
            )
            ws_path = payload.get("path")
            result = okbay.set_selected_workspace(
                str(ws_id), path=str(ws_path) if ws_path else None
            )
            status.write_status()
            code, body, ct = _json_bytes(
                {"ok": True, "okbay": result, "workspaces": okbay.list_workspaces()}
            )
            return self._send(code, body, ct)

        if path in ("/api/config/roles", "/api/roles/config"):
            saved = roles.save_role_config(payload)
            status.write_status()
            code, body, ct = _json_bytes({"ok": True, "roles_config": saved})
            return self._send(code, body, ct)


        if path in ("/api/harness/enable", "/api/config/harness/enable"):
            from .harness import config as harness_config

            hid = str(payload.get("id") or payload.get("harness") or "").strip()
            if not hid:
                code, body, ct = _json_bytes({"ok": False, "error": "id required"}, 400)
                return self._send(code, body, ct)
            try:
                harness_config.enable(hid)
            except ValueError as e:
                code, body, ct = _json_bytes({"ok": False, "error": str(e)}, 400)
                return self._send(code, body, ct)
            status.write_status()
            code, body, ct = _json_bytes(harness_config.list_for_api())
            return self._send(code, body, ct)

        if path in ("/api/harness/disable", "/api/config/harness/disable"):
            from .harness import config as harness_config

            hid = str(payload.get("id") or payload.get("harness") or "").strip()
            if not hid:
                code, body, ct = _json_bytes({"ok": False, "error": "id required"}, 400)
                return self._send(code, body, ct)
            try:
                harness_config.disable(hid)
            except ValueError as e:
                code, body, ct = _json_bytes({"ok": False, "error": str(e)}, 400)
                return self._send(code, body, ct)
            status.write_status()
            code, body, ct = _json_bytes(harness_config.list_for_api())
            return self._send(code, body, ct)

        if path in ("/api/harness/reload", "/api/config/harness/reload"):
            from .harness import config as harness_config

            # Re-read from disk (load is always fresh); refresh status mirror.
            snap = harness_config.list_for_api()
            status.write_status()
            code, body, ct = _json_bytes(snap)
            return self._send(code, body, ct)

        if path in ("/api/harness/set", "/api/config/harness/set"):
            from .harness import config as harness_config

            key = str(payload.get("key") or "").strip()
            value = payload.get("value")
            if value is None:
                value = ""
            if not key:
                code, body, ct = _json_bytes({"ok": False, "error": "key required"}, 400)
                return self._send(code, body, ct)
            try:
                harness_config.set_value(key, str(value))
            except ValueError as e:
                code, body, ct = _json_bytes({"ok": False, "error": str(e)}, 400)
                return self._send(code, body, ct)
            status.write_status()
            code, body, ct = _json_bytes(harness_config.list_for_api())
            return self._send(code, body, ct)

        code, body, ct = _json_bytes({"error": "not found", "path": path}, 404)
        self._send(code, body, ct)


def serve(host: str = "127.0.0.1", port: int = PORT) -> int:
    status.write_status()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(
        f"okstratr listening on http://{host}:{port}  "
        "(/health /api/status /api/desk/* /api/web /api/workspaces /api/config/roles /api/harness /api/desk_session "
        "/api/seat /api/dag /api/blackboard /api/cos/break /api/herdr/launch /api/herdr/run-ready)"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()
    return 0
