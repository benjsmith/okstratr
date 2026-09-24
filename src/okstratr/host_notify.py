"""Path-native host notify envelope (contract C2).

okstratr **emits** ``okstratr.host_notify`` v1; the host maps it to one sink:
- Switchbay → rail (POST ``/api/okstratr/host-notify``)
- okbay → Herdr ingest (POST; stub URL OK)
- Bare CLI → harness-visible stderr/stdout summary (or JSON lines)

See skill-shell ``CONTRACT-AUTO-START-AND-NOTIFY.md``.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .logutil import get_logger
from .public_base import HOSTED_SHELLS, normalize_hosted_shell

_log = get_logger(__name__)

ENVELOPE_TYPE = "okstratr.host_notify"
ENVELOPE_V = 1

KINDS = frozenset(
    {
        "schedule.start",
        "schedule.progress",
        "schedule.done",
        "schedule.failed",
        "desk.progress",
        "desk.done",
    }
)

DESK_VALUES = frozenset({"auto", "curate", "research", "deck", "work", "code"})

ENV_NOTIFY_URL = "OKSTRATR_HOST_NOTIFY_URL"
ENV_HOSTED = "OKSTRATR_HOSTED"
ENV_HOST = "OKSTRATR_HOST"
ENV_JSON_NOTIFY = "OKSTRATR_JSON_NOTIFY"
ENV_NOTIFY_STREAM = "OKSTRATR_HOST_NOTIFY_STREAM"

_DEFAULT_URLS = {
    "switchbay": "http://127.0.0.1:8765/api/okstratr/host-notify",
    "okbay": "http://127.0.0.1:8766/api/okstratr/host-notify",
}

_json_notify_cli: bool | None = None


class HostNotifyError(ValueError):
    """Invalid host_notify envelope."""


def set_json_notify(enabled: bool | None) -> None:
    """CLI override for JSON-line bare delivery (None = use env)."""
    global _json_notify_cli
    _json_notify_cli = enabled


def json_notify_enabled() -> bool:
    if _json_notify_cli is not None:
        return bool(_json_notify_cli)
    raw = (os.environ.get(ENV_JSON_NOTIFY) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def hosted_shell() -> str | None:
    for key in (ENV_HOSTED, ENV_HOST):
        found = normalize_hosted_shell(os.environ.get(key))
        if found:
            return found
    return None


def notify_url(*, hosted: str | None = None) -> str | None:
    """Resolve POST target. Explicit URL wins; else hosted default."""
    explicit = (os.environ.get(ENV_NOTIFY_URL) or "").strip()
    if explicit:
        return explicit
    shell = hosted if hosted is not None else hosted_shell()
    if shell in _DEFAULT_URLS:
        return _DEFAULT_URLS[shell]
    return None


def _iso_ts(ts: float | str | None = None) -> str:
    if isinstance(ts, str) and ts.strip():
        return ts.strip()
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _norm_desk(desk: Any) -> str | None:
    if desk is None or desk == "" or str(desk).lower() in ("null", "none"):
        return None
    d = str(desk).strip().lower()
    aliases = {
        "auto": "auto",
        "curate": "curate",
        "research": "research",
        "deck": "deck",
        "work": "work",
        "code": "code",
        "curator": "curate",
        "investigate": "research",
        "slides": "deck",
    }
    return aliases.get(d, d)


def build_envelope(
    kind: str,
    *,
    title: str,
    body: str = "",
    schedule_id: str | None = None,
    desk: str | None = None,
    progress: dict[str, Any] | None = None,
    ts: float | str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v1 host_notify envelope (does not deliver)."""
    prog_in = progress if isinstance(progress, dict) else {}
    pct = prog_in.get("pct")
    if pct is None and "pct" in prog_in:
        pct = prog_in.get("pct")
    env: dict[str, Any] = {
        "type": ENVELOPE_TYPE,
        "v": ENVELOPE_V,
        "kind": str(kind or "").strip(),
        "schedule_id": schedule_id,
        "desk": _norm_desk(desk),
        "title": str(title or "").strip() or str(kind or "").strip() or "notify",
        "body": str(body or "").strip(),
        "progress": {
            "pct": pct,
            "phase": str(prog_in.get("phase") or ""),
            "detail": str(prog_in.get("detail") or ""),
        },
        "ts": _iso_ts(ts),
    }
    if extra:
        for key, val in extra.items():
            if key not in env:
                env[key] = val
    return env


def validate_envelope(data: Any) -> dict[str, Any]:
    """Validate and return a normalized envelope copy."""
    if not isinstance(data, dict):
        raise HostNotifyError("envelope must be a dict")
    if data.get("type") != ENVELOPE_TYPE:
        raise HostNotifyError(f"type must be {ENVELOPE_TYPE!r}")
    try:
        v = int(data.get("v"))
    except (TypeError, ValueError) as e:
        raise HostNotifyError("v must be int") from e
    if v != ENVELOPE_V:
        raise HostNotifyError(f"v must be {ENVELOPE_V}")
    kind = str(data.get("kind") or "").strip()
    if kind not in KINDS:
        raise HostNotifyError(f"kind must be one of {sorted(KINDS)}")
    desk = _norm_desk(data.get("desk"))
    if desk is not None and desk not in DESK_VALUES:
        raise HostNotifyError(
            f"desk must be one of {sorted(DESK_VALUES)} or null, got {desk!r}"
        )
    title = str(data.get("title") or "").strip()
    if not title:
        raise HostNotifyError("title required")
    prog = data.get("progress")
    if prog is None:
        prog = {}
    elif not isinstance(prog, dict):
        raise HostNotifyError("progress must be object")
    pct = prog.get("pct")
    if pct is None and "pct" in prog:
        pct = prog.get("pct")
    return {
        "type": ENVELOPE_TYPE,
        "v": ENVELOPE_V,
        "kind": kind,
        "schedule_id": data.get("schedule_id"),
        "desk": desk,
        "title": title,
        "body": str(data.get("body") or ""),
        "progress": {
            "pct": pct,
            "phase": str(prog.get("phase") or ""),
            "detail": str(prog.get("detail") or ""),
        },
        "ts": str(data.get("ts") or _iso_ts()),
    }


def format_summary(envelope: dict[str, Any]) -> str:
    """One/few-line harness-visible summary for bare CLI."""
    kind = envelope.get("kind") or "?"
    title = envelope.get("title") or ""
    desk = envelope.get("desk")
    sid = envelope.get("schedule_id")
    body = (envelope.get("body") or "").strip()
    prog = envelope.get("progress") or {}
    bits = [f"[okstratr] {kind}: {title}"]
    meta: list[str] = []
    if desk:
        meta.append(f"desk={desk}")
    if sid:
        meta.append(f"schedule={sid}")
    phase = prog.get("phase")
    pct = prog.get("pct")
    if phase:
        meta.append(f"phase={phase}")
    if pct is not None:
        meta.append(f"{pct}%")
    if meta:
        bits.append("(" + ", ".join(meta) + ")")
    line1 = " ".join(bits)
    if body:
        return f"{line1}\n  {body}"
    return line1


def _notify_stream():
    raw = (os.environ.get(ENV_NOTIFY_STREAM) or "stderr").strip().lower()
    return sys.stdout if raw == "stdout" else sys.stderr


def deliver_bare(envelope: dict[str, Any]) -> dict[str, Any]:
    stream = _notify_stream()
    if json_notify_enabled():
        line = json.dumps(envelope, default=str, separators=(",", ":"))
        print(line, file=stream, flush=True)
        return {"ok": True, "path": "bare", "mode": "json", "printed": True}
    print(format_summary(envelope), file=stream, flush=True)
    return {"ok": True, "path": "bare", "mode": "summary", "printed": True}


def deliver_http(
    envelope: dict[str, Any], url: str, *, timeout: float = 2.5
) -> dict[str, Any]:
    raw = json.dumps(envelope, default=str).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")[:500]
            return {
                "ok": 200 <= int(status) < 300,
                "path": "http",
                "url": url,
                "status": int(status),
                "body": body,
            }
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        _log.warning("host_notify HTTP %s to %s: %s", e.code, url, detail or e)
        return {
            "ok": False,
            "path": "http",
            "url": url,
            "status": int(e.code),
            "error": str(e),
            "body": detail,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _log.warning("host_notify POST failed to %s: %s", url, e)
        return {"ok": False, "path": "http", "url": url, "error": str(e)}


def emit(
    kind: str,
    *,
    title: str,
    body: str = "",
    schedule_id: str | None = None,
    desk: str | None = None,
    progress: dict[str, Any] | None = None,
    ts: float | str | None = None,
    extra: dict[str, Any] | None = None,
    force_bare: bool = False,
    url: str | None = None,
) -> dict[str, Any]:
    """Build, validate, and deliver a host_notify envelope.

    Hosted / ``OKSTRATR_HOST_NOTIFY_URL`` → POST JSON (fallback bare on failure).
    Else bare → harness-visible summary (or JSON lines).
    """
    envelope = validate_envelope(
        build_envelope(
            kind,
            title=title,
            body=body,
            schedule_id=schedule_id,
            desk=desk,
            progress=progress,
            ts=ts,
            extra=extra,
        )
    )
    return emit_envelope(envelope, force_bare=force_bare, url=url)


def emit_envelope(
    envelope: dict[str, Any],
    *,
    force_bare: bool = False,
    url: str | None = None,
) -> dict[str, Any]:
    env = validate_envelope(envelope)
    target = None if force_bare else (url if url is not None else notify_url())
    if target:
        result = deliver_http(env, target)
        result["envelope"] = env
        if result.get("ok"):
            return result
        result["fallback_bare"] = deliver_bare(env)
        return result
    bare = deliver_bare(env)
    bare["envelope"] = env
    return bare


__all__ = [
    "ENVELOPE_TYPE",
    "ENVELOPE_V",
    "KINDS",
    "DESK_VALUES",
    "HOSTED_SHELLS",
    "ENV_NOTIFY_URL",
    "ENV_JSON_NOTIFY",
    "HostNotifyError",
    "build_envelope",
    "validate_envelope",
    "format_summary",
    "notify_url",
    "hosted_shell",
    "json_notify_enabled",
    "set_json_notify",
    "deliver_bare",
    "deliver_http",
    "emit",
    "emit_envelope",
]
