"""okstratr command-line."""

from __future__ import annotations

import argparse
import json
import sys


def _print(data, as_json: bool = False) -> int:
    if as_json or isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)
    return 0


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _parse_deps(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.replace(" ", ",").split(",") if t.strip()]



_DEFAULT_KINDS = frozenset({"curate", "work", "code", "deck", "auto"})


def _cmd_desk(args) -> int:
    from . import desks, herdr, status

    cmd = args.desk_cmd
    if cmd == "start":
        kind = args.kind
        first = (args.kind_or_objective or "").strip()
        rest = list(args.objective or [])
        if kind:
            obj_parts = ([first] if first else []) + rest
            obj = " ".join(obj_parts).strip()
        elif first.lower() in _DEFAULT_KINDS:
            kind = first.lower()
            obj = " ".join(rest).strip()
        else:
            obj = " ".join(([first] if first else []) + rest).strip()
            kind = None
        result = desks.start(
            obj,
            kind=kind,
            reset=bool(args.reset),
            effort=args.effort,
            run_cos=not bool(args.no_cos),
        )
        out = status.write_status()
        out = dict(out)
        out["desk"] = result
        if args.herdr and obj:
            out["herdr_launch"] = herdr.launch(obj)
        return _print(out)

    if cmd == "stop":
        return _print(desks.stop())

    if cmd == "dismiss":
        return _print(desks.dismiss())

    if cmd == "delete":
        return _print(
            desks.delete(
                getattr(args, "desk_id", None),
                force=bool(getattr(args, "force", False)),
            )
        )

    if cmd == "status":
        snap = desks.status_snapshot()
        # also refresh status.json
        status.write_status()
        return _print(snap)

    if cmd == "schedule":
        return _print(desks.schedule(list(args.spec or [])))

    if cmd == "hire":
        return _print(desks.hire(args.role, desk_id=args.desk_id))

    if cmd == "effort":
        return _print(desks.set_effort(args.value, desk_id=getattr(args, "desk_id", None)))

    if cmd == "retire":
        return _print(desks.retire_worker(args.node_id, desk_id=args.desk_id))

    if cmd == "focus":
        return _print(desks.focus(args.desk_id or None))

    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="okstratr")
    sub = p.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("status", help="Print lifecycle status box (services, desks, tokens, …)")
    st.add_argument("--json", action="store_true", help="Machine-readable status payload + write status.json")
    st.add_argument("--publish", action="store_true", help="Also refresh status.json (implied by --json)")

    sub.add_parser("doctor", help="Skill helper: running? need consent? asset/port diagnostics")

    start_p = sub.add_parser("start", help="Start serve (+ observer panel) with consent unless --yes")
    start_p.add_argument("--yes", "-y", action="store_true", help="Skip consent prompt (automation)")
    start_p.add_argument("--no-observer", action="store_true", help="Do not start/ensure observer panel")
    start_p.add_argument("--host", default="127.0.0.1")
    start_p.add_argument("--port", type=int, default=8767)

    sub.add_parser("restart", help="Shutdown then start serve (+ observer panel)")

    shut = sub.add_parser("shutdown", help="Stop serve, observer host, and okstratr seat children")
    shut.add_argument("--keep-seats", action="store_true", help="Do not kill harness seat children")

    obs = sub.add_parser("observer", help="Observer panel URL / optional dedicated :8768 host")
    obs.add_argument("--serve", action="store_true", help="Start dedicated static host on :8768")
    obs.add_argument("--json", action="store_true")
    panel = sub.add_parser("panel", help="Alias for observer (observer panel)")
    panel.add_argument("--serve", action="store_true")
    panel.add_argument("--json", action="store_true")

    # --- desk (primary) ---
    desk_p = sub.add_parser("desk", help="Desk lifecycle: start|stop|dismiss|delete|status|schedule|hire|effort|retire|focus")
    desk_sub = desk_p.add_subparsers(dest="desk_cmd", required=True)

    desk_start = desk_sub.add_parser("start", help="Start a desk (hire CoS + roles)")
    desk_start.add_argument(
        "kind_or_objective",
        nargs="?",
        default="",
        help="Optional kind (curate|work|code|deck|auto) or first word of objective",
    )
    desk_start.add_argument(
        "objective",
        nargs="*",
        default=[],
        help="Objective words (if kind given first, remainder is objective)",
    )
    desk_start.add_argument(
        "--kind",
        default=None,
        help="Desk kind override (curate|work|code|deck|auto|custom)",
    )
    desk_start.add_argument("--reset", action="store_true", help="Force a fresh desk org")
    desk_start.add_argument(
        "--no-cos",
        action="store_true",
        help="Skip heuristic CoS DAG breakdown after start",
    )
    desk_start.add_argument(
        "--effort",
        type=float,
        default=None,
        help="Optional effort slider 0..1 (bandit utility weights / hire cap)",
    )
    desk_start.add_argument(
        "--herdr",
        action="store_true",
        help="Also launch/focus Herdr UI (no live agent sync yet)",
    )

    desk_sub.add_parser("stop", help="Quiet desk; keep last live DAG; CoS ready")
    desk_sub.add_parser("dismiss", help="Disband desk; archive/clear standing org")
    desk_del = desk_sub.add_parser("delete", help="Purge dismissed desk from registry")
    desk_del.add_argument("desk_id", nargs="?", default=None, help="Desk id to purge")
    desk_del.add_argument("--force", action="store_true", help="Allow purge of non-dismissed desk")
    desk_sub.add_parser("status", help="Show active desk + registry")

    desk_sched = desk_sub.add_parser(
        "schedule",
        help="Attach schedule (parse args now; dialog UI later)",
    )
    desk_sched.add_argument(
        "spec",
        nargs="*",
        help="hourly|daily|weekly|monthly|yearly|annually | 90 | 1h30m | 2 wks | …",
    )

    desk_hire = desk_sub.add_parser("hire", help="Grant a role (kernel hire; cap + curate guards)")
    desk_hire.add_argument("role", help="Role id to grant (investigator, verifier, …)")
    desk_hire.add_argument("--desk-id", dest="desk_id", default=None)

    desk_effort = desk_sub.add_parser("effort", help="Set effort slider 0..1 (bandit weights)")
    desk_effort.add_argument("value", type=float, help="Effort in [0, 1]")
    desk_effort.add_argument("--desk-id", dest="desk_id", default=None)

    desk_retire = desk_sub.add_parser("retire", help="Retire a short-lived DAG worker node")
    desk_retire.add_argument("node_id", help="DAG node id to remove (summary → blackboard)")
    desk_retire.add_argument("--desk-id", dest="desk_id", default=None)

    desk_focus = desk_sub.add_parser("focus", help="Stub: focus a desk (Herdr sync later)")
    desk_focus.add_argument("desk_id", nargs="?", default=None)

    # Deprecated alias — one release
    seat = sub.add_parser(
        "seat",
        help="DEPRECATED — use 'desk start [kind] …'; thin alias for 'desk start auto …' (warns)",
    )
    seat.add_argument("objective", nargs="*", default=[])
    seat.add_argument("--herdr", action="store_true", help="Also launch/focus Herdr")
    seat.add_argument(
        "--cos",
        action="store_true",
        help="Ignored (desk start always runs CoS breakdown unless --no-cos on desk)",
    )
    seat.add_argument(
        "--reset",
        action="store_true",
        help="Force a fresh desk org",
    )

    hh = sub.add_parser("herdr", help="Herdr bridge: launch UI or run-ready finite seats")
    hh.add_argument(
        "objective",
        nargs="?",
        default="",
        help="Objective text to launch, or 'run-ready' to seat ready DAG nodes",
    )
    hh.add_argument(
        "--limit",
        type=int,
        default=1,
        help="For run-ready: max ready nodes to seat (default 1)",
    )
    hh.add_argument(
        "--dry-run",
        action="store_true",
        help="For run-ready: no real Herdr/Grok calls (also OKSTRATR_HERDR_DRY_RUN=1)",
    )

    # Legacy alias
    bb_legacy = sub.add_parser("blackboard", help="Blackboard head or post (legacy)")
    bb_legacy.add_argument("text", nargs="?", default="")
    bb_legacy.add_argument("--post", action="store_true")

    cos_p = sub.add_parser("cos", help="Chief-of-staff advise / break")
    cos_p.add_argument(
        "action_or_objective",
        nargs="?",
        default="",
        help="'break' to expand DAG, or objective text for advise",
    )
    cos_p.add_argument(
        "objective",
        nargs="?",
        default="",
        help="Optional objective when action is 'break'",
    )

    sv = sub.add_parser("serve", help="HTTP on 8767")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8767)

    # --- dag ---
    dag_p = sub.add_parser("dag", help="Persistent work DAG")
    dag_sub = dag_p.add_subparsers(dest="dag_cmd", required=True)

    dag_add = dag_sub.add_parser("add", help="Add a node")
    dag_add.add_argument("id")
    dag_add.add_argument("title", nargs="?", default="")
    dag_add.add_argument("--depends", "--depends-on", dest="depends", default="")
    dag_add.add_argument("--kind", default=None)
    dag_add.add_argument("--objective", default="")
    dag_add.add_argument("--notes", default="")

    dag_sub.add_parser("list", help="List nodes / summary")
    dag_sub.add_parser("ready", help="List ready nodes")

    dag_done = dag_sub.add_parser("done", help="Mark node done")
    dag_done.add_argument("id")
    dag_done.add_argument("--notes", default=None)

    dag_fail = dag_sub.add_parser("fail", help="Mark node failed")
    dag_fail.add_argument("id")
    dag_fail.add_argument("--notes", default=None)

    dag_sub.add_parser("reset", help="Clear the DAG")

    dag_state = dag_sub.add_parser("state", help="Set node state")
    dag_state.add_argument("id")
    dag_state.add_argument("state")

    # --- bb ---
    bb_p = sub.add_parser("bb", help="Persistent blackboard")
    bb_sub = bb_p.add_subparsers(dest="bb_cmd", required=True)

    bb_post = bb_sub.add_parser("post", help="Post an entry")
    bb_post.add_argument("text", nargs="+")
    bb_post.add_argument("--author", default="human")
    bb_post.add_argument(
        "--kind",
        default="note",
        choices=["claim", "note", "decision", "evidence"],
    )
    bb_post.add_argument("--tags", default="")
    bb_post.add_argument("--provenance", default="")
    bb_post.add_argument("--node-id", dest="node_id", default=None)

    bb_head = bb_sub.add_parser("head", help="Show recent entries")
    bb_head.add_argument("n", nargs="?", type=int, default=10)

    bb_search = bb_sub.add_parser("search", help="Search entries")
    bb_search.add_argument("substr")

    bb_sub.add_parser("clear", help="Hard-wipe live blackboard (no archive by default)")
    bb_sub.add_parser("prune", help="Drop live entries older than blackboard.duration (0⇒ASAP agents, ≤60m)")
    bb_dur = bb_sub.add_parser("duration", help="Set/show live board duration (days; 0=ephemeral≤60m)")
    bb_dur.add_argument("value", nargs="?", default=None, help="e.g. 3, 3d, 60m, 0")

    # --- audit ---
    audit_p = sub.add_parser("audit", help="Tamper-evident ops audit log")
    audit_sub = audit_p.add_subparsers(dest="audit_cmd", required=True)
    audit_tail = audit_sub.add_parser("tail", help="Show recent audit records")
    audit_tail.add_argument("n", nargs="?", type=int, default=20)
    audit_head = audit_sub.add_parser("head", help="Show earliest audit records")
    audit_head.add_argument("n", nargs="?", type=int, default=20)
    audit_sub.add_parser("verify", help="Verify hash chain integrity")

    web_p = sub.add_parser("web", help="Web egress gate: status|on|off")
    web_sub = web_p.add_subparsers(dest="web_cmd", required=True)
    web_sub.add_parser("status", help="Show web egress mode (Off|Once|Session)")
    web_on = web_sub.add_parser("on", help="Enable web egress (choose once|session)")
    web_on.add_argument("--once", action="store_true", help="Allow a single search then auto-off")
    web_on.add_argument("--session", action="store_true", help="Allow until revoke/desk stop/dismiss")
    web_on.add_argument(
        "mode",
        nargs="?",
        default=None,
        help="Optional once|session (interactive default: prompt)",
    )
    web_off = web_sub.add_parser("off", help="Revoke web egress")
    web_off.add_argument(
        "what",
        nargs="?",
        default=None,
        help="Optional 'search' alias (web search off)",
    )
    # Alias: `okstratr web search off`
    web_search = web_sub.add_parser("search", help="Alias: web search off")
    web_search.add_argument("action", nargs="?", default="off", help="off")


    # --- harness ---
    harness_p = sub.add_parser("harness", help="Harness registry: list|detect|enable|disable")
    harness_sub = harness_p.add_subparsers(dest="harness_cmd", required=True)
    harness_sub.add_parser("list", help="List built-in harnesses + enabled/installed")
    harness_sub.add_parser("detect", help="Detect which harness CLIs are on PATH")
    h_en = harness_sub.add_parser("enable", help="Allowlist a harness in harnesses.toml")
    h_en.add_argument("id", help="Harness id (grok|claude|codex|…)")
    h_dis = harness_sub.add_parser("disable", help="Remove harness from allowlist")
    h_dis.add_argument("id", help="Harness id")

    # --- config ---
    cfg_p = sub.add_parser("config", help="Show/set harness config (harnesses.toml)")
    cfg_sub = cfg_p.add_subparsers(dest="config_cmd", required=True)
    cfg_sub.add_parser("show", help="Show harness config + path")
    cfg_set = cfg_sub.add_parser("set", help="Set a config key")
    cfg_set.add_argument("key", help="enabled|preference|models.<id>|defaults.<k>|harness.<id>.default_model|backend|…")
    cfg_set.add_argument("value", help="Value (comma-separated for lists)")

    # --- model ---
    model_p = sub.add_parser("model", help="List harness models / rungs (Switchbay-inspired)")
    model_sub = model_p.add_subparsers(dest="model_cmd", required=True)
    model_sub.add_parser("list", help="List models per enabled harness + effort rungs")


    # --- agents (Herdr grouping stub) ---
    agents_p = sub.add_parser(
        "agents",
        help="List/group agents by desk_id/thread_id (Herdr list + desk registry)",
    )
    agents_p.add_argument("--desk", dest="desk_id", default=None, help="Filter by desk_id")
    agents_p.add_argument("--thread", dest="thread_id", default=None, help="Filter by thread_id")

    args = p.parse_args(argv)


    if args.cmd == "status":
        from . import lifecycle, status as status_mod

        if getattr(args, "json", False):
            status_mod.write_status()
            return _print(lifecycle.status_payload())
        if getattr(args, "publish", False):
            status_mod.write_status()
        print(lifecycle.format_status_box())
        return 0

    if args.cmd == "doctor":
        from . import lifecycle

        return _print(lifecycle.doctor())

    if args.cmd == "start":
        from . import lifecycle

        out = lifecycle.start(
            yes=bool(getattr(args, "yes", False)),
            prompt=not bool(getattr(args, "yes", False)),
            observer=not bool(getattr(args, "no_observer", False)),
            host=getattr(args, "host", "127.0.0.1"),
            port=int(getattr(args, "port", 8767)),
        )
        return _print(out)

    if args.cmd == "restart":
        from . import lifecycle

        return _print(lifecycle.restart(yes=True, observer=True))

    if args.cmd == "shutdown":
        from . import lifecycle

        return _print(lifecycle.shutdown(kill_seats=not bool(getattr(args, "keep_seats", False))))

    if args.cmd in ("observer", "panel"):
        from . import lifecycle

        if getattr(args, "serve", False):
            spawned = lifecycle._spawn_observer_host()
            out = {
                "ok": bool(spawned.get("ok")),
                "observer_url": spawned.get("url") or lifecycle.observer_url(),
                "spawn": spawned,
            }
            return _print(out)
        url = lifecycle.observer_url()
        if getattr(args, "json", False):
            return _print({"observer_url": url, "serve_running": lifecycle.is_serve_running()})
        print(url)
        return 0

    if args.cmd == "web":
        from . import status, web_egress

        cmd = args.web_cmd
        if cmd == "status":
            snap = web_egress.status()
            status.write_status()
            return _print(snap)
        if cmd == "on":
            mode = None
            if getattr(args, "once", False):
                mode = "once"
            elif getattr(args, "session", False):
                mode = "session"
            elif getattr(args, "mode", None):
                mode = str(args.mode).strip().lower()
            if mode is None:
                # Interactive choice when a TTY is available; else session
                if sys.stdin.isatty():
                    print("Web egress: [1] once  [2] session  [0] cancel", file=sys.stderr)
                    choice = (input("Choice: ").strip() or "").lower()
                    if choice in ("1", "once", "o"):
                        mode = "once"
                    elif choice in ("2", "session", "s"):
                        mode = "session"
                    else:
                        print("cancelled", file=sys.stderr)
                        return 1
                else:
                    mode = "session"
            out = web_egress.set_mode(mode)
            status.write_status()
            return _print(out)
        if cmd == "off":
            out = web_egress.revoke()
            status.write_status()
            return _print(out)
        if cmd == "search":
            action = (getattr(args, "action", None) or "off").strip().lower()
            if action != "off":
                print("usage: okstratr web search off", file=sys.stderr)
                return 2
            out = web_egress.revoke()
            status.write_status()
            return _print(out)
        return 1

    if args.cmd == "desk":
        return _cmd_desk(args)

    if args.cmd == "seat":
        # Deprecated thin alias → desk start auto …
        print(
            "DEPRECATED: 'okstratr seat' — use 'okstratr desk start [kind] [objective…]'. "
            "This alias still calls desk start auto; it will be removed in a future release.",
            file=sys.stderr,
        )
        from . import desks, herdr, status

        obj = " ".join(args.objective).strip() if isinstance(args.objective, list) else (
            args.objective or ""
        ).strip()
        result = desks.start(obj, kind="auto", reset=bool(args.reset), run_cos=True)
        out = status.write_status()
        out = dict(out)
        out["desk"] = result
        out["deprecated"] = "seat"
        if args.herdr and obj:
            out["herdr_launch"] = herdr.launch(obj)
        return _print(out)

    if args.cmd == "herdr":
        from . import herdr, status

        obj = (args.objective or "").strip()
        if obj == "run-ready":
            return _print(
                herdr.run_ready(limit=int(args.limit), dry_run=bool(args.dry_run) or None)
            )
        obj = obj or status.get_objective()
        return _print(herdr.launch(obj))

    if args.cmd == "blackboard":
        from . import blackboard, status

        if args.post or args.text:
            if not args.text:
                print("blackboard --post requires text", file=sys.stderr)
                return 2
            blackboard.post(args.text)
            status.write_status()
            return _print(blackboard.summary())
        return _print(blackboard.summary())

    if args.cmd == "cos":
        from . import blackboard, cos, status

        action = (args.action_or_objective or "").strip()
        if action == "break":
            obj = (args.objective or "").strip() or status.get_objective()
            result = cos.break_down(obj)
            status.write_status()
            return _print(result)
        obj = action or status.get_objective()
        return _print(cos.advise(obj, blackboard.texts(5)))

    if args.cmd == "serve":
        from . import blackboard, server

        try:
            blackboard.on_serve_start()
        except Exception:  # noqa: BLE001
            pass
        return server.serve(args.host, args.port)

    if args.cmd == "dag":
        from . import dag, status

        g = dag.default_dag()
        if args.dag_cmd == "add":
            title = (args.title or args.id).strip()
            node = g.add(
                args.id,
                title,
                depends_on=_parse_deps(args.depends),
                kind=args.kind,
                objective=args.objective or "",
                notes=args.notes or "",
            )
            status.write_status()
            return _print(node.to_dict())
        if args.dag_cmd == "list":
            return _print(g.summary())
        if args.dag_cmd == "ready":
            g.refresh_ready()
            return _print([n.to_dict() for n in g.ready()])
        if args.dag_cmd == "done":
            node = g.mark_done(args.id, notes=args.notes)
            status.write_status()
            return _print(node.to_dict())
        if args.dag_cmd == "fail":
            node = g.mark_failed(args.id, notes=args.notes)
            status.write_status()
            return _print(node.to_dict())
        if args.dag_cmd == "reset":
            g.reset()
            status.write_status()
            return _print({"reset": True, "nodes": 0})
        if args.dag_cmd == "state":
            node = g.set_state(args.id, args.state)
            status.write_status()
            return _print(node.to_dict())
        return 1

    if args.cmd == "bb":
        from . import blackboard, status

        if args.bb_cmd == "post":
            text = " ".join(args.text).strip()
            entry = blackboard.post(
                text,
                author=args.author,
                kind=args.kind,
                tags=_parse_tags(args.tags),
                provenance=args.provenance,
                node_id=args.node_id,
            )
            status.write_status()
            return _print(entry)
        if args.bb_cmd == "head":
            return _print(blackboard.head(args.n))
        if args.bb_cmd == "search":
            return _print(blackboard.search(args.substr))
        if args.bb_cmd == "clear":
            out = blackboard.clear()
            status.write_status()
            return _print(out)
        if args.bb_cmd == "prune":
            out = blackboard.prune()
            status.write_status()
            return _print(out)
        if args.bb_cmd == "duration":
            from . import bb_settings

            if args.value is not None:
                out = bb_settings.set_value("blackboard.duration", str(args.value))
            else:
                out = bb_settings.load()
            out = {**out, "chip": bb_settings.mode_chip()}
            return _print(out)
        return 1

    if args.cmd == "audit":
        from . import ops_audit

        if args.audit_cmd == "tail":
            return _print({"path": ops_audit.path(), "records": ops_audit.tail(args.n)})
        if args.audit_cmd == "head":
            return _print({"path": ops_audit.path(), "records": ops_audit.head(args.n)})
        if args.audit_cmd == "verify":
            return _print(ops_audit.verify())
        return 1

    if args.cmd == "harness":
        from . import harness as harness_mod

        cmd = args.harness_cmd
        if cmd == "list":
            cfg = harness_mod.load()
            detected = harness_mod.detect_all()
            rows = []
            for h in harness_mod.list_defs():
                rows.append(
                    {
                        **h.to_dict(),
                        "enabled": cfg.is_enabled(h.id),
                        "installed": detected.get(h.id, False),
                    }
                )
            return _print(
                {
                    "path": str(harness_mod.config_path()),
                    "enabled": cfg.enabled,
                    "preference": cfg.preference_order(),
                    "harnesses": rows,
                }
            )
        if cmd == "detect":
            return _print(harness_mod.detect_all())
        if cmd == "enable":
            cfg = harness_mod.enable(args.id)
            return _print({"ok": True, "enabled": cfg.enabled, "path": str(cfg.path)})
        if cmd == "disable":
            cfg = harness_mod.disable(args.id)
            return _print({"ok": True, "enabled": cfg.enabled, "path": str(cfg.path)})
        return 1

    if args.cmd == "config":
        from . import harness as harness_mod

        if args.config_cmd == "show":
            from . import bb_settings

            cfg = harness_mod.load()
            return _print({
                **cfg.to_dict(),
                "path": str(cfg.path or harness_mod.config_path()),
                "blackboard": bb_settings.load(),
            })
        if args.config_cmd == "set":
            from . import bb_settings

            k = args.key.strip().lower()
            if k.startswith("blackboard.") or k in (
                "duration", "duration_days", "retention", "retention_days", "archive_on_clear",
            ):
                out = bb_settings.set_value(
                    k if k.startswith("blackboard.") else f"blackboard.{k}",
                    args.value,
                )
                return _print({"ok": True, "blackboard": out})
            cfg = harness_mod.set_value(args.key, args.value)
            return _print({"ok": True, **cfg.to_dict()})
        return 1


    if args.cmd == "cd":
        from . import workspace

        if getattr(args, "path", None):
            return _print(workspace.set_cwd(args.path))
        return _print(workspace.status())


    if args.cmd == "model":
        from . import harness as harness_mod

        if args.model_cmd == "list":
            cfg = harness_mod.load()
            return _print(
                {
                    "path": str(harness_mod.config_path()),
                    "backend": cfg.preferred_backend(),
                    "models": harness_mod.list_models(cfg),
                }
            )
        return 1

    if args.cmd == "agents":
        from . import desks, herdr, status

        snap = status.write_status()
        labels = snap.get("herdr_labels") or []
        desk_f = getattr(args, "desk_id", None)
        thread_f = getattr(args, "thread_id", None)
        agents = []
        try:
            dsnap = desks.status_snapshot()
        except Exception:  # noqa: BLE001
            dsnap = {}
        for d in (dsnap.get("desks") or []):
            if not isinstance(d, dict):
                continue
            did = d.get("id") or d.get("desk_id")
            tid = d.get("thread_id")
            if desk_f and did != desk_f:
                continue
            if thread_f and tid != thread_f:
                continue
            agents.append(
                {
                    "desk_id": did,
                    "thread_id": tid,
                    "kind": d.get("kind"),
                    "state": d.get("state"),
                    "objective": (d.get("objective") or "")[:80],
                    "source": "okstratr.desks",
                }
            )
        if isinstance(labels, list):
            for lab in labels:
                if isinstance(lab, dict):
                    if desk_f and lab.get("desk_id") != desk_f:
                        continue
                    if thread_f and lab.get("thread_id") != thread_f:
                        continue
                    agents.append({**lab, "source": "status.herdr_labels"})
        # Live Herdr agent list when available
        herdr_list = herdr.list_herdr_agents()
        for a in herdr_list.get("agents") or []:
            if desk_f and a.get("desk_id") != desk_f:
                continue
            if thread_f and a.get("thread_id") != thread_f:
                continue
            agents.append(a)
        grouped = herdr.group_agents_by_labels(agents)
        bin_path = herdr.herdr_bin()
        return _print(
            {
                "ok": True,
                "herdr_installed": bool(bin_path),
                "herdr_list_ok": herdr_list.get("ok"),
                "filter": {"desk_id": desk_f, "thread_id": thread_f},
                "agents": agents,
                "grouped": grouped,
                "label_convention": herdr.LABEL_CONVENTION,
                "mac_howto": (
                    "okstratr start --yes  # daemon + observer :8767\n"
                    "open http://127.0.0.1:8767/observer/  # primary visual\n"
                    "okstratr agents  # desk_id/thread_id groupings"
                ),
            }
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
