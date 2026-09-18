"""Apply parsed slash directives (cwd/web/bb/lifecycle) outside any UI."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .slash import SlashDirectives, parse_slash_directives

DEFAULT_BASE = "http://127.0.0.1:8767"


def api_base() -> str:
    return (os.environ.get("OKSTRATR_API") or DEFAULT_BASE).rstrip("/")


def http_json(method: str, path: str, body: dict | None = None, *, timeout: float = 5.0) -> dict[str, Any]:
    url = api_base() + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return {}


def apply_slash_side_effects(directives: SlashDirectives) -> str | None:
    """Apply non-env slash side effects (bb clear/duration/prune/audit + /okstratr)."""
    toasts: list[str] = []
    oc = getattr(directives, "okstratr_cmd", None)
    if oc:
        from okstratr import lifecycle

        if oc == "status":
            toasts.append(lifecycle.format_status_box())
        elif oc == "start":
            out = lifecycle.start(prompt=True, yes=False, observer=True)
            if out.get("need_consent"):
                toasts.append(out.get("message") or lifecycle.CONSENT_PROMPT)
            else:
                toasts.append(out.get("message") or ("started" if out.get("ok") else "start failed"))
        elif oc == "restart":
            out = lifecycle.restart(yes=True, observer=True)
            toasts.append(out.get("message") or "restarted")
        elif oc == "shutdown":
            out = lifecycle.shutdown()
            toasts.append(out.get("message") or "shutdown")
    if getattr(directives, "prune_board", False):
        result = http_json("POST", "/api/blackboard/prune", {})
        if not isinstance(result, dict) or not result.get("ok"):
            from okstratr import blackboard

            result = blackboard.prune()
        pruned = (result.get("retention") or {}).get("pruned") if isinstance(result, dict) else None
        toasts.append(f"bb pruned={pruned}")

    dv = getattr(directives, "duration_value", None)
    if dv is not None:
        from okstratr import bb_settings

        if dv in ("status", ""):
            toasts.append(bb_settings.mode_chip())
        else:
            bb_settings.set_value("blackboard.duration", str(dv))
            toasts.append(bb_settings.mode_chip())

    if getattr(directives, "show_audit", False):
        result = http_json("GET", "/api/audit?n=12")
        if isinstance(result, dict) and result.get("records") is not None:
            n = len(result.get("records") or [])
            ok = (result.get("verify") or {}).get("ok")
            toasts.append(f"audit tail={n} verify={ok}")
        else:
            from okstratr import ops_audit

            v = ops_audit.verify()
            toasts.append(f"audit verify={v.get('ok')} count={v.get('count')}")

    if getattr(directives, "clear_blackboard", False):
        result = http_json("POST", "/api/blackboard/clear", {})
        if isinstance(result, dict) and result.get("cleared") is True:
            toasts.append("blackboard cleared")
        else:
            try:
                from okstratr import blackboard, status as status_mod

                blackboard.clear()
                status_mod.write_status()
                toasts.append("blackboard cleared")
            except Exception as e:  # noqa: BLE001
                toasts.append(f"blackboard clear failed: {e}")

    return " | ".join(toasts) if toasts else None


def slash_is_bb_control_only(directives: SlashDirectives) -> bool:
    """True when the line is only bb/audit/okstratr control (no seating objective)."""
    if directives.objective or directives.kind or directives.harnesses or directives.model or directives.rung:
        return False
    return bool(
        directives.clear_blackboard
        or getattr(directives, "duration_value", None) is not None
        or getattr(directives, "prune_board", False)
        or getattr(directives, "show_audit", False)
        or getattr(directives, "okstratr_cmd", None)
    )


def apply_slash_env(text: str) -> tuple[str, str | None]:
    """Parse slash line → set env overrides; return (objective, kind).

    Side effects: `/cd` updates workspace cwd; `/web` toggles web_egress gate.
    Blackboard clear is handled by ``apply_slash_side_effects``.
    """
    d = parse_slash_directives(text)
    obj = d.objective or text
    if d.harnesses:
        os.environ["OKSTRATR_HARNESS_PREFER"] = ",".join(d.harnesses)
        os.environ["OKSTRATR_HERDR_KIND"] = d.harnesses[0]
    if d.model_harness:
        os.environ["OKSTRATR_HERDR_KIND"] = d.model_harness
        os.environ["OKSTRATR_HARNESS_PREFER"] = d.model_harness
    if d.model:
        os.environ["OKSTRATR_MODEL"] = d.model
    if d.rung:
        os.environ["OKSTRATR_RUNG"] = d.rung
    if getattr(d, "cwd", None):
        from okstratr import workspace

        workspace.set_cwd(d.cwd)
    if getattr(d, "web", None):
        from okstratr import web_egress

        mode = str(d.web).strip().lower()
        if mode in ("status", "?", "show"):
            pass
        elif mode in ("off", "deny", "revoke"):
            web_egress.revoke()
        elif mode in ("on", "session"):
            web_egress.set_mode("session")
        elif mode == "once":
            web_egress.set_mode("once")
        else:
            web_egress.set_mode(mode)
    return obj, d.kind
