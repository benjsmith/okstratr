"""Public URL base path + hosted-shell detection (Phase 1a).

Switchbay/okbay same-origin reverse-proxy okstratr under a configurable prefix
(default empty; typical embed: ``/embed/okstratr``). See charter locked decision
#1 (no iframes) and #6 (hosted mode disables HTML settings).
"""

from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import parse_qs

HOSTED_SHELLS = frozenset({"switchbay", "okbay"})
HOST_HEADER = "X-Okstratr-Host"


def public_base() -> str:
    """Normalized public base path (no trailing slash), or \"\" when unset.

    Env: ``OKSTRATR_PUBLIC_BASE`` — e.g. ``/embed/okstratr``.
    """
    raw = (os.environ.get("OKSTRATR_PUBLIC_BASE") or "").strip()
    if not raw or raw == "/":
        return ""
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw.rstrip("/")


def strip_public_base(path: str) -> str:
    """Strip configured public base from an absolute request path."""
    base = public_base()
    if not base:
        return path or "/"
    p = path or "/"
    if p == base:
        return "/"
    if p.startswith(base + "/"):
        rest = p[len(base) :]
        return rest if rest else "/"
    return p


def normalize_hosted_shell(raw: str | None) -> str | None:
    """Return ``switchbay``|``okbay`` or None."""
    if not raw:
        return None
    h = str(raw).strip().lower()
    if h in HOSTED_SHELLS:
        return h
    return None


def hosted_shell_from_request(
    headers: Mapping[str, str] | None,
    query: Mapping[str, list[str]] | None = None,
) -> str | None:
    """Resolve hosted shell from ``X-Okstratr-Host`` or ``?host=``.

    Header wins when both are present and valid.
    """
    if headers:
        # Case-insensitive header lookup
        for key, val in headers.items():
            if key.lower() == HOST_HEADER.lower():
                found = normalize_hosted_shell(val)
                if found:
                    return found
                break
    if query:
        vals = query.get("host") or []
        if vals:
            return normalize_hosted_shell(vals[0])
    return None


def hosted_shell_from_query_string(qs: str) -> str | None:
    if not qs:
        return None
    return hosted_shell_from_request(None, parse_qs(qs))


def observer_bootstrap_js(*, hosted: str | None = None, api_base: str | None = None) -> str:
    """Inline script assigning window.OKSTRATR_* for the observer panel."""
    base = public_base() if api_base is None else (api_base or "")
    base = base.rstrip("/")
    host = normalize_hosted_shell(hosted) or ""
    # Keep JSON-safe string literals
    return (
        "window.OKSTRATR_PUBLIC_BASE="
        + _js_str(base)
        + ";window.OKSTRATR_API="
        + _js_str(base)
        + ";window.OKSTRATR_HOSTED="
        + _js_str(host)
        + ";"
    )


def _js_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def inject_observer_bootstrap(html: bytes | str, *, hosted: str | None = None) -> bytes:
    """Inject bootstrap script before ``</head>`` (or start of ``<body>``)."""
    text = html.decode("utf-8") if isinstance(html, (bytes, bytearray)) else str(html)
    snippet = "<script>" + observer_bootstrap_js(hosted=hosted) + "</script>\n"
    lower = text.lower()
    idx = lower.find("</head>")
    if idx >= 0:
        text = text[:idx] + snippet + text[idx:]
    else:
        bidx = lower.find("<body")
        if bidx >= 0:
            gt = text.find(">", bidx)
            if gt >= 0:
                text = text[: gt + 1] + "\n" + snippet + text[gt + 1 :]
            else:
                text = snippet + text
        else:
            text = snippet + text
    return text.encode("utf-8")
