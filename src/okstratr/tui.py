"""CLI/TUI desk brain — standing desks, DAG topo, blackboard, slash help."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .harness.slash import SLASH_HELP, SlashDirectives, parse_slash_directives


DEFAULT_BASE = "http://127.0.0.1:8767"
DEFAULT_POLL_SEC = 2.0


def api_base() -> str:
    return (os.environ.get("OKSTRATR_API") or DEFAULT_BASE).rstrip("/")


def http_json(method: str, path: str, body: dict | None = None, *, timeout: float = 5.0) -> dict[str, Any]:
    url = f"{api_base()}{path}"
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
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body) if err_body else {}
        except json.JSONDecodeError:
            parsed = {"error": err_body or str(e)}
        parsed.setdefault("ok", False)
        parsed.setdefault("http_status", e.code)
        return parsed
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "url": url}



def _node_list(payload: dict[str, Any] | None) -> list[Any]:
    """Extract node dicts from a DAG payload (nodes may be count or list)."""
    if not isinstance(payload, dict):
        return []
    nodes = payload.get("nodes")
    if isinstance(nodes, list):
        return nodes
    items = payload.get("items")
    if isinstance(items, list):
        return items
    if isinstance(nodes, dict):
        return list(nodes.values())
    return []


def fetch_status() -> dict[str, Any]:
    return http_json("GET", "/api/status")


def fetch_desk_status() -> dict[str, Any]:
    return http_json("GET", "/api/desk/status")


def fetch_dag(*, desk_id: str | None = None) -> dict[str, Any]:
    q = f"?desk_id={desk_id}" if desk_id else ""
    return http_json("GET", f"/api/dag{q}")


def resolve_dag_payload(
    status: dict[str, Any] | None,
    dag_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prefer /api/dag; fall back to desk_session.dag / status.dag / CoS-on-blackboard."""
    dag_payload = dag_payload if isinstance(dag_payload, dict) else {}
    nodes = _node_list(dag_payload)
    if nodes:
        out = dict(dag_payload)
        out["nodes"] = nodes
        out.setdefault("items", nodes)
        return out
    st = status if isinstance(status, dict) else {}
    ds = st.get("desk_session") if isinstance(st.get("desk_session"), dict) else {}
    for cand in (
        ds.get("dag") if isinstance(ds.get("dag"), dict) else None,
        st.get("dag") if isinstance(st.get("dag"), dict) else None,
        (st.get("cos") or {}).get("dag") if isinstance(st.get("cos"), dict) else None,
    ):
        if not isinstance(cand, dict):
            continue
        n = _node_list(cand)
        if n:
            out = dict(cand)
            out["nodes"] = n
            out.setdefault("items", n)
            out.setdefault("source", "desk_session-fallback")
            return out
    bb = st.get("blackboard") if isinstance(st.get("blackboard"), dict) else {}
    entries = bb.get("entries") or bb.get("items") or bb.get("head") or []
    cos_nodes: list[dict[str, Any]] = []
    if isinstance(entries, list):
        for e in entries[:12]:
            if not isinstance(e, dict):
                continue
            author = str(e.get("author") or e.get("kind") or "")
            text = str(e.get("text") or e.get("body") or e.get("content") or "")
            low_a = author.lower()
            if low_a in ("cos", "chief", "chief_of_staff", "plan") or text.lower().startswith("plan"):
                cos_nodes.append(
                    {
                        "id": str(e.get("id") or f"bb-{len(cos_nodes)}"),
                        "title": (text or author)[:80],
                        "state": e.get("state") or "ready",
                        "depends_on": [],
                        "role": "cos",
                    }
                )
    if cos_nodes:
        return {"nodes": cos_nodes, "source": "blackboard-cos-fallback"}
    return dag_payload or {"nodes": [], "source": "empty"}


def fetch_blackboard(n: int = 8) -> dict[str, Any]:
    return http_json("GET", f"/api/blackboard?n={n}")


def post_query(objective: str, *, kind: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"objective": objective, "drive_herdr": False}
    if kind:
        payload["kind"] = kind
    return http_json("POST", "/api/desk/start", payload)


def badge_for_state(state: str | None) -> str:
    """Map desk state → tab badge. Match Model.js deskStateLabel: empty → "".

    working/running → Running; quiet → Idle; dismissed → Dismissed;
    never-started (""), setup, legacy idle, unknown → "" (no [?] / no Idle suffix).
    """
    s = (state or "").strip().lower()
    if s in ("working", "running"):
        return "Running"
    if s == "quiet":
        return "Idle"
    if s == "dismissed":
        return "Dismissed"
    # empty / setup / legacy idle / unknown → no bracket content (tabs show "work" not "work[?]")
    return ""


def desk_rows(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize standing desks for sidebar/tabs with Running/Idle badges.

    Prefer DeskSession (P3 SSOT) when present; fall back to legacy top-level
    desks/standing or status.desk.standing.
    """
    ds = status.get("desk_session") if isinstance(status.get("desk_session"), dict) else None
    desks = None
    if ds:
        desks = ds.get("desks") or ds.get("standing")
    if not desks:
        desks = status.get("desks") or status.get("standing")
    if not desks and isinstance(status.get("desk"), dict):
        desks = status["desk"].get("standing")
    desks = desks or []
    if isinstance(desks, dict):
        rows = list(desks.values()) if desks else []
    else:
        rows = list(desks) if isinstance(desks, list) else []
    out = []
    for d in rows:
        if not isinstance(d, dict):
            continue
        # Preserve "" for never-started placeholders (do not coerce to "?" → "[?]" badge)
        raw = d.get("state")
        state = "" if raw is None else str(raw)
        out.append(
            {
                "id": d.get("id") or d.get("desk_id") or "?",
                "kind": d.get("kind") or "?",
                "state": state,
                "badge": badge_for_state(state),
                "objective": (d.get("objective") or "")[:80],
                "thread_id": d.get("thread_id"),
            }
        )
    return out


def desk_tab_line(rows: list[dict[str, Any]], *, active_id: str | None = None) -> str:
    """Compact tab strip: work[Running] | curate[Idle] | work (empty badge omits brackets)."""
    parts = []
    for r in rows:
        mark = "*" if active_id and r["id"] == active_id else ""
        badge = r.get("badge") or ""
        if badge:
            parts.append(f"{mark}{r['kind']}[{badge}]")
        else:
            parts.append(f"{mark}{r['kind']}")
    return " | ".join(parts) if parts else "(no desks)"


def dag_topo_lines(dag_payload: dict[str, Any]) -> list[str]:
    """Render DAG nodes in topo-ish order with node status."""
    items = _node_list(dag_payload if isinstance(dag_payload, dict) else {})
    by_id = {n.get("id"): n for n in items if isinstance(n, dict) and n.get("id")}
    # Kahn-ish: score by unresolved dep depth
    scored: list[tuple[int, str, str]] = []
    for n in items:
        if not isinstance(n, dict):
            continue
        deps = n.get("depends_on") or []
        if not isinstance(deps, list):
            deps = []
        depth = 0
        seen = set()
        stack = list(deps)
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            depth += 1
            parent = by_id.get(d)
            if parent:
                stack.extend(parent.get("depends_on") or [])
        nid = n.get("id") or "?"
        state = n.get("state") or "?"
        title = n.get("title") or n.get("objective") or ""
        scored.append((depth, nid, f"[{state}] {nid}: {title}"[:100]))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [s for _, _, s in scored]


def blackboard_head_lines(bb: dict[str, Any], n: int = 8) -> list[str]:
    entries = bb.get("entries") or bb.get("head") or bb.get("items") or []
    if isinstance(bb, list):
        entries = bb
    lines = []
    for e in list(entries)[:n]:
        if isinstance(e, dict):
            author = e.get("author") or "?"
            text = (e.get("text") or e.get("body") or "")[:90]
            lines.append(f"{author}: {text}")
        else:
            lines.append(str(e)[:100])
    return lines


def running_label(status: dict[str, Any]) -> str:
    state = (status.get("state") or status.get("desk_state") or "").lower()
    if state in ("working", "running"):
        return "Running"
    active = status.get("active_desk") or status.get("desk") or {}
    if isinstance(active, dict) and (active.get("state") or "").lower() == "working":
        return "Running"
    rows = desk_rows(status)
    if any(r.get("badge") == "Running" for r in rows):
        return "Running"
    return "Idle"


def merge_status_payloads(st: dict[str, Any], desk: dict[str, Any]) -> dict[str, Any]:
    merged = dict(st or {})
    if isinstance(desk, dict):
        for k, v in desk.items():
            if k not in merged or not merged.get(k):
                merged[k] = v
        if desk.get("desks") and not merged.get("desks"):
            merged["desks"] = desk["desks"]
    return merged



def _bb_chip(status: dict[str, Any] | None = None) -> str:
    try:
        from . import bb_settings

        return bb_settings.mode_chip()
    except Exception:  # noqa: BLE001
        bb = (status or {}).get("blackboard") if isinstance(status, dict) else None
        if isinstance(bb, dict) and bb.get("mode"):
            return str(bb["mode"])
        return "bb: ephemeral"

def _web_chip(status: dict[str, Any]) -> str:
    we = status.get("web_egress") if isinstance(status.get("web_egress"), dict) else {}
    if not we:
        try:
            from . import web_egress as we_mod

            we = we_mod.status()
        except Exception:  # noqa: BLE001
            we = {"chip": "Web: Off", "mode": "off"}
    chip = we.get("chip") or f"Web: {we.get('label') or we.get('mode') or 'Off'}"
    if we.get("pending_approval"):
        chip += " (needs approval)"
    return str(chip)


def _cwd_chip() -> str:
    try:
        from . import workspace

        return f"cwd: {workspace.get_cwd()}"
    except Exception:  # noqa: BLE001
        return "cwd: ?"


def _harness_status(status: dict[str, Any] | None) -> dict[str, Any]:
    """Harness payload from /api/status (preferred) or empty."""
    status = status if isinstance(status, dict) else {}
    h = status.get("harness")
    return h if isinstance(h, dict) else {}


def _backend_chip(status: dict[str, Any] | None = None) -> str:
    h = _harness_status(status)
    backend = str(h.get("backend") or (h.get("defaults") or {}).get("backend") or "").strip()
    if not backend:
        try:
            from .harness import config as harness_config

            backend = harness_config.load().preferred_backend()
        except Exception:  # noqa: BLE001
            backend = "?"
    return f"backend={backend or '?'}"


def _format_enabled_harness(row: dict[str, Any]) -> str:
    hid = str(row.get("id") or "").strip() or "?"
    model = str(row.get("default_model") or "").strip()
    settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
    reasoning = str(
        (settings or {}).get("reasoning")
        or (settings or {}).get("reasoning_effort")
        or ""
    ).strip()
    base = f"{hid}@{model}" if model else hid
    if reasoning:
        return f"{base} (reasoning={reasoning})"
    return base


def _harness_chip(status: dict[str, Any] | None = None) -> str:
    """Enabled harnesses with default_model + reasoning, comma-separated."""
    h = _harness_status(status)
    rows = h.get("harnesses") if isinstance(h.get("harnesses"), list) else []
    enabled_ids = {
        str(x).strip().lower()
        for x in (h.get("enabled") or [])
        if str(x).strip()
    }
    parts: list[str] = []
    seen: set[str] = set()
    # Prefer preference / enabled order when present
    order = [str(x).strip().lower() for x in (h.get("preference") or h.get("enabled") or []) if str(x).strip()]
    by_id = {
        str(r.get("id") or "").strip().lower(): r
        for r in rows
        if isinstance(r, dict) and r.get("id")
    }
    for hid in order:
        row = by_id.get(hid)
        if not row:
            continue
        if enabled_ids and hid not in enabled_ids and not row.get("enabled"):
            continue
        if not row.get("enabled", hid in enabled_ids or not enabled_ids):
            continue
        if hid in seen:
            continue
        seen.add(hid)
        parts.append(_format_enabled_harness(row))
    if not parts:
        for row in rows:
            if not isinstance(row, dict) or not row.get("enabled"):
                continue
            hid = str(row.get("id") or "").strip().lower()
            if hid in seen:
                continue
            seen.add(hid)
            parts.append(_format_enabled_harness(row))
    if not parts:
        return "harness: (none)"
    return "harness: " + ", ".join(parts)


def render_snapshot(
    status: dict[str, Any] | None = None,
    dag_payload: dict[str, Any] | None = None,
    bb: dict[str, Any] | None = None,
) -> str:
    """Plain-text snapshot (CI / --snapshot; no Textual interaction)."""
    status = status if status is not None else {}
    bb = bb if bb is not None else {}
    # Attach blackboard onto status for CoS fallback synthesis
    if bb and "blackboard" not in status:
        status = {**status, "blackboard": bb}
    dag_payload = resolve_dag_payload(status, dag_payload)
    rows = desk_rows(status)
    active = status.get("active_desk") or status.get("desk") or {}
    active_id = active.get("id") if isinstance(active, dict) else None
    focus = status.get("focus_desk_id") or active_id
    lines = [
        f"okstratr tui — {running_label(status)} — {api_base()}",
        f"  {_web_chip(status)}  |  {_bb_chip(status)}  |  {_cwd_chip()}  |  {_backend_chip(status)}  |  {_harness_chip(status)}",
        "",
        "## Desks (tabs)",
        f"  {desk_tab_line(rows, active_id=active_id or focus)}",
        "",
        "## Standing (left pane)",
    ]
    if not rows:
        lines.append("  (none)")
    for r in rows:
        badge = r.get("badge") or ""
        badge_s = f"[{badge}] " if badge else ""
        lines.append(f"  {badge_s}{r['kind']} {r['id']} — {r['objective']}")
    lines.append("")
    lines.append(f"## DAG (topo) focus={focus or '-'}")
    for ln in dag_topo_lines(dag_payload) or ["(empty)"]:
        lines.append(f"  {ln}" if not ln.startswith(" ") else ln)
    lines.append("")
    lines.append("## Blackboard (head)")
    for ln in blackboard_head_lines(bb) or ["(empty)"]:
        lines.append(f"  {ln}")
    lines.append("")
    lines.append(f"Query: {SLASH_HELP}")
    return "\n".join(lines)


def render_live_snapshot() -> str:
    st = fetch_status()
    desk = fetch_desk_status()
    merged = merge_status_payloads(st, desk)
    focus = None
    if isinstance(merged.get("active_desk"), dict):
        focus = merged["active_desk"].get("id")
    focus = focus or merged.get("focus_desk_id")
    dag_p = fetch_dag(desk_id=str(focus) if focus else None)
    return render_snapshot(merged, dag_p, fetch_blackboard())


def apply_slash_side_effects(directives: SlashDirectives) -> str | None:
    """Apply non-env slash side effects (bb clear/duration/prune/audit + /okstratr)."""
    toasts: list[str] = []
    oc = getattr(directives, "okstratr_cmd", None)
    if oc:
        from . import lifecycle

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
            from . import blackboard

            result = blackboard.prune()
        pruned = (result.get("retention") or {}).get("pruned") if isinstance(result, dict) else None
        toasts.append(f"bb pruned={pruned}")

    dv = getattr(directives, "duration_value", None)
    if dv is not None:
        from . import bb_settings

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
            from . import ops_audit

            v = ops_audit.verify()
            toasts.append(f"audit verify={v.get('ok')} count={v.get('count')}")

    if getattr(directives, "clear_blackboard", False):
        result = http_json("POST", "/api/blackboard/clear", {})
        if isinstance(result, dict) and result.get("cleared") is True:
            toasts.append("blackboard cleared")
        else:
            try:
                from . import blackboard, status as status_mod

                blackboard.clear()
                status_mod.write_status()
                toasts.append("blackboard cleared")
            except Exception as e:  # noqa: BLE001
                toasts.append(f"blackboard clear failed: {e}")

    return " | ".join(toasts) if toasts else None


def _slash_is_bb_control_only(directives: SlashDirectives) -> bool:
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
        from . import workspace

        workspace.set_cwd(d.cwd)
    if getattr(d, "web", None):
        from . import web_egress

        mode = str(d.web).strip().lower()
        if mode in ("status", "?", "show"):
            pass  # status shown on next refresh chip
        elif mode in ("off", "deny", "revoke"):
            web_egress.revoke()
        elif mode in ("on", "session"):
            web_egress.set_mode("session")
        elif mode == "once":
            web_egress.set_mode("once")
        else:
            web_egress.set_mode(mode)
    return obj, d.kind


def run_textual(*, poll_sec: float | None = None) -> int:
    """Run Textual app when [tui] extra is installed."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Footer, Header, Input, Static
    except ImportError:
        print(
            "textual not installed — run: pip install 'okstratr[tui]' "
            "or use: okstratr tui --snapshot",
            flush=True,
        )
        print(render_live_snapshot())
        return 0

    interval = poll_sec if poll_sec is not None else float(
        os.environ.get("OKSTRATR_TUI_POLL") or DEFAULT_POLL_SEC
    )

    class OkstratrTui(App[None]):
        CSS = """
        #desks { width: 30; border: solid $accent; }
        #main { border: solid $primary; }
        #bb { height: 10; border: solid $secondary; }
        #help { height: 1; color: $text-muted; }
        #tabs { height: 3; border-bottom: solid $accent; }
        """
        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
            ("?", "help", "Slash help"),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("tabs…", id="tabs")
            with Horizontal():
                yield Static("Desks…", id="desks")
                with Vertical(id="main"):
                    yield Static("DAG…", id="dag")
                    yield Static("Blackboard…", id="bb")
                    yield Static(f"Query help: {SLASH_HELP}", id="help")
                    yield Input(placeholder="Query / objective…", id="query")
            yield Footer()

        def on_mount(self) -> None:
            self.action_refresh()
            if interval > 0:
                self.set_interval(interval, self.action_refresh)

        def action_help(self) -> None:
            self.query_one("#help", Static).update(f"Slash: {SLASH_HELP}")

        def action_refresh(self) -> None:
            st = fetch_status()
            desk = fetch_desk_status()
            merged = merge_status_payloads(st, desk)
            active = merged.get("active_desk") or merged.get("desk") or {}
            active_id = active.get("id") if isinstance(active, dict) else None
            focus = active_id or merged.get("focus_desk_id")
            bb = fetch_blackboard()
            if bb and "blackboard" not in merged:
                merged = {**merged, "blackboard": bb}
            dag_p = resolve_dag_payload(
                merged, fetch_dag(desk_id=str(focus) if focus else None)
            )
            rows = desk_rows(merged) or desk_rows(desk)
            self.query_one("#tabs", Static).update(
                f"{desk_tab_line(rows, active_id=active_id)}  |  {_web_chip(merged)}  |  {_bb_chip(merged)}  |  {_cwd_chip()}  |  {_backend_chip(merged)}  |  {_harness_chip(merged)}"
            )
            desks_w = self.query_one("#desks", Static)
            desk_lines = []
            for r in rows:
                badge = r.get("badge") or ""
                suffix = f" [{badge}]" if badge else ""
                desk_lines.append(f"{r['kind']}{suffix}\n{r['id'][:14]}")
            desks_w.update(
                f"{running_label(merged)}\n{_web_chip(merged)}\n{_bb_chip(merged)}\n{_cwd_chip()}\n{_backend_chip(merged)}\n{_harness_chip(merged)}\n\n"
                + ("\n".join(desk_lines) or "(no desks)")
            )
            self.query_one("#dag", Static).update(
                "DAG\n" + "\n".join(dag_topo_lines(dag_p) or ["(empty)"])
            )
            self.query_one("#bb", Static).update(
                "Blackboard\n" + "\n".join(blackboard_head_lines(bb) or ["(empty)"])
            )
            self.title = f"okstratr — {running_label(merged)}"

        def on_input_submitted(self, event: Input.Submitted) -> None:
            text = (event.value or "").strip()
            if not text:
                return
            if text in ("?", "/help", "help"):
                self.action_help()
                event.input.value = ""
                return
            d = parse_slash_directives(text)
            toast = apply_slash_side_effects(d)
            if _slash_is_bb_control_only(d) or d.clear_blackboard:
                event.input.value = ""
                self.action_refresh()
                if toast:
                    self.query_one("#help", Static).update(toast)
                    try:
                        self.notify(toast)
                    except Exception:  # noqa: BLE001
                        pass
                # Control-only line: do not seat/post a query.
                if _slash_is_bb_control_only(d):
                    return
            obj, kind = apply_slash_env(text)
            if obj.strip() or kind:
                post_query(obj, kind=kind)
            event.input.value = ""
            self.action_refresh()

    OkstratrTui().run()
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="okstratr tui")
    p.add_argument(
        "--snapshot",
        action="store_true",
        help="Print a one-shot text snapshot (no interactive UI)",
    )
    p.add_argument(
        "--plain",
        action="store_true",
        help="Force plain snapshot even if textual is installed",
    )
    p.add_argument(
        "--poll",
        type=float,
        default=None,
        help=f"Live refresh interval seconds (default {DEFAULT_POLL_SEC}; 0=off)",
    )
    args = p.parse_args(argv)
    if args.snapshot or args.plain:
        print(render_live_snapshot())
        return 0
    return run_textual(poll_sec=args.poll)
