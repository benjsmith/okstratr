"""Minimal CLI/TUI desk brain (Phase 1) — talks to local daemon HTTP API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE = "http://127.0.0.1:8767"


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


def desk_rows(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize standing desks for sidebar/tabs."""
    desks = status.get("desks") or status.get("standing") or []
    if isinstance(desks, dict):
        rows = list(desks.values()) if desks else []
    else:
        rows = list(desks) if isinstance(desks, list) else []
    out = []
    for d in rows:
        if not isinstance(d, dict):
            continue
        out.append(
            {
                "id": d.get("id") or d.get("desk_id") or "?",
                "kind": d.get("kind") or "?",
                "state": d.get("state") or "?",
                "objective": (d.get("objective") or "")[:80],
            }
        )
    return out


def dag_topo_lines(dag_payload: dict[str, Any]) -> list[str]:
    """Render DAG nodes in a simple topo-ish list (deps first)."""
    nodes = dag_payload.get("nodes") or []
    if isinstance(nodes, dict):
        items = list(nodes.values())
    else:
        items = list(nodes) if isinstance(nodes, list) else []
    # Prefer summary.ready / ordered by depends depth
    scored: list[tuple[int, str]] = []
    for n in items:
        if not isinstance(n, dict):
            continue
        deps = n.get("depends_on") or []
        depth = len(deps) if isinstance(deps, list) else 0
        nid = n.get("id") or "?"
        state = n.get("state") or "?"
        title = n.get("title") or n.get("objective") or ""
        scored.append((depth, f"[{state}] {nid}: {title}"[:100]))
    scored.sort(key=lambda x: x[0])
    return [s for _, s in scored]


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
    return "Idle"


def render_snapshot(
    status: dict[str, Any] | None = None,
    dag_payload: dict[str, Any] | None = None,
    bb: dict[str, Any] | None = None,
) -> str:
    """Plain-text snapshot (used by smoke tests and non-textual fallback)."""
    status = status if status is not None else {}
    dag_payload = dag_payload if dag_payload is not None else {}
    bb = bb if bb is not None else {}
    lines = [
        f"okstratr tui — {running_label(status)} — {api_base()}",
        "",
        "## Desks",
    ]
    rows = desk_rows(status)
    if not rows:
        lines.append("  (none)")
    for r in rows:
        lines.append(f"  [{r['state']}] {r['kind']} {r['id']} — {r['objective']}")
    lines.append("")
    lines.append("## DAG")
    for ln in dag_topo_lines(dag_payload) or ["  (empty)"]:
        lines.append(f"  {ln}" if not ln.startswith(" ") else ln)
    lines.append("")
    lines.append("## Blackboard")
    for ln in blackboard_head_lines(bb) or ["  (empty)"]:
        lines.append(f"  {ln}")
    lines.append("")
    lines.append("Query: (type objective; slash /harness /model /work …)")
    return "\n".join(lines)


def run_textual() -> int:
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

    class OkstratrTui(App[None]):
        CSS = """
        #desks { width: 28; border: solid $accent; }
        #main { border: solid $primary; }
        #bb { height: 10; border: solid $secondary; }
        """
        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                yield Static("Desks…", id="desks")
                with Vertical(id="main"):
                    yield Static("DAG…", id="dag")
                    yield Static("Blackboard…", id="bb")
                    yield Input(placeholder="Query / objective…", id="query")
            yield Footer()

        def on_mount(self) -> None:
            self.action_refresh()

        def action_refresh(self) -> None:
            st = fetch_status()
            desk = fetch_desk_status()
            merged = dict(st)
            if isinstance(desk, dict):
                merged.update({k: v for k, v in desk.items() if k not in merged or not merged.get(k)})
                if desk.get("desks") and not merged.get("desks"):
                    merged["desks"] = desk["desks"]
            dag_p = fetch_dag()
            bb = fetch_blackboard()
            desks_w = self.query_one("#desks", Static)
            rows = desk_rows(merged) or desk_rows(desk)
            desks_w.update(
                f"{running_label(merged)}\n\n"
                + "\n".join(
                    f"{r['kind']} [{r['state']}]\n{r['id'][:12]}" for r in rows
                )
                or "(no desks)"
            )
            self.query_one("#dag", Static).update(
                "DAG\n" + "\n".join(dag_topo_lines(dag_p) or ["(empty)"])
            )
            self.query_one("#bb", Static).update(
                "Blackboard\n" + "\n".join(blackboard_head_lines(bb) or ["(empty)"])
            )
            self.title = f"okstratr — {running_label(merged)}"

        def on_input_submitted(self, event: Input.Submitted) -> None:
            from .harness.slash import parse_slash_directives

            text = (event.value or "").strip()
            if not text:
                return
            d = parse_slash_directives(text)
            obj = d.objective or text
            if d.harnesses:
                os.environ["OKSTRATR_HARNESS_PREFER"] = ",".join(d.harnesses)
                os.environ["OKSTRATR_HERDR_KIND"] = d.harnesses[0]
            if d.model:
                os.environ["OKSTRATR_MODEL"] = d.model
            post_query(obj, kind=d.kind)
            event.input.value = ""
            self.action_refresh()

    OkstratrTui().run()
    return 0


def render_live_snapshot() -> str:
    return render_snapshot(fetch_status(), fetch_dag(), fetch_blackboard())


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
    args = p.parse_args(argv)
    if args.snapshot or args.plain:
        print(render_live_snapshot())
        return 0
    return run_textual()
