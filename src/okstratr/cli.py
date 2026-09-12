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

    sub.add_parser("status", help="Print and publish status.json")

    # --- desk (primary) ---
    desk_p = sub.add_parser("desk", help="Desk lifecycle: start|stop|dismiss|status|schedule|hire|effort|retire|focus")
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
        help="DEPRECATED: alias for 'desk start auto …' (warns once)",
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

    bb_sub.add_parser("clear", help="Archive and clear blackboard")

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

    args = p.parse_args(argv)

    if args.cmd == "status":
        from . import status

        return _print(status.write_status())

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
            "warning: 'seat' is deprecated; use 'desk start [kind] [objective…]' "
            "(alias calls desk start auto for one release)",
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
        from . import server

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
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
