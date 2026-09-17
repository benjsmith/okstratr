"""CLI/TUI desk brain — standing desks, DAG topo, blackboard, slash help."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .harness.slash import SLASH_HELP, parse_slash_directives


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


def fetch_status() -> dict[str, Any]:
    return http_json("GET", "/api/status")


def fetch_desk_status() -> dict[str, Any]:
    return http_json("GET", "/api/desk/status")


def fetch_dag() -> dict[str, Any]:
    return http_json("GET", "/api/dag")


def fetch_blackboard(n: int = 8) -> dict[str, Any]:
    return http_json("GET", f"/api/blackboard?n={n}")


def post_query(objective: str, *, kind: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"objective": objective, "drive_herdr": False}
    if kind:
        payload["kind"] = kind
    return http_json("POST", "/api/desk/start", payload)


def badge_for_state(state: str | None) -> str:
    s = (state or "").lower()
    if s in ("working", "running"):
        return "Running"
    if s in ("quiet", "idle", "setup", ""):
        return "Idle"
    if s == "dismissed":
        return "Dismissed"
    return state or "?"


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
        state = d.get("state") or "?"
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
    """Compact tab strip: work[Running] | curate[Idle] | …"""
    parts = []
    for r in rows:
        mark = "*" if active_id and r["id"] == active_id else ""
        parts.append(f"{mark}{r['kind']}[{r['badge']}]")
    return " | ".join(parts) if parts else "(no desks)"


def dag_topo_lines(dag_payload: dict[str, Any]) -> list[str]:
    """Render DAG nodes in topo-ish order with node status."""
    nodes = dag_payload.get("nodes") or []
    if isinstance(nodes, dict):
        items = list(nodes.values())
    else:
        items = list(nodes) if isinstance(nodes, list) else []
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


def render_snapshot(
    status: dict[str, Any] | None = None,
    dag_payload: dict[str, Any] | None = None,
    bb: dict[str, Any] | None = None,
) -> str:
    """Plain-text snapshot (CI / --snapshot; no Textual interaction)."""
    status = status if status is not None else {}
    dag_payload = dag_payload if dag_payload is not None else {}
    bb = bb if bb is not None else {}
    rows = desk_rows(status)
    active = status.get("active_desk") or status.get("desk") or {}
    active_id = active.get("id") if isinstance(active, dict) else None
    lines = [
        f"okstratr tui — {running_label(status)} — {api_base()}",
        "",
        "## Desks (tabs)",
        f"  {desk_tab_line(rows, active_id=active_id)}",
        "",
        "## Standing",
    ]
    if not rows:
        lines.append("  (none)")
    for r in rows:
        lines.append(
            f"  [{r['badge']}] {r['kind']} {r['id']} — {r['objective']}"
        )
    lines.append("")
    lines.append("## DAG (topo)")
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
    return render_snapshot(merge_status_payloads(st, desk), fetch_dag(), fetch_blackboard())


def apply_slash_env(text: str) -> tuple[str, str | None]:
    """Parse slash line → set env overrides; return (objective, kind)."""
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
            dag_p = fetch_dag()
            bb = fetch_blackboard()
            rows = desk_rows(merged) or desk_rows(desk)
            active = merged.get("active_desk") or merged.get("desk") or {}
            active_id = active.get("id") if isinstance(active, dict) else None
            self.query_one("#tabs", Static).update(
                desk_tab_line(rows, active_id=active_id)
            )
            desks_w = self.query_one("#desks", Static)
            desks_w.update(
                f"{running_label(merged)}\n\n"
                + (
                    "\n".join(
                        f"{r['kind']} [{r['badge']}]\n{r['id'][:14]}" for r in rows
                    )
                    or "(no desks)"
                )
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
            obj, kind = apply_slash_env(text)
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
