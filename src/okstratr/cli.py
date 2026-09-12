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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="okstratr")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Print and publish status.json")

    seat = sub.add_parser("seat", help="Seat an objective")
    seat.add_argument("objective", nargs="?", default="")
    seat.add_argument("--herdr", action="store_true", help="Also launch/focus Herdr")
    seat.add_argument(
        "--reset",
        action="store_true",
        help="Clear DAG before seating a fresh root (default: keep existing nodes)",
    )

    hh = sub.add_parser("herdr", help="Launch/focus Herdr with objective text")
    hh.add_argument("objective", nargs="?", default="")

    # Legacy alias
    bb_legacy = sub.add_parser("blackboard", help="Blackboard head or post (legacy)")
    bb_legacy.add_argument("text", nargs="?", default="")
    bb_legacy.add_argument("--post", action="store_true")

    cos_p = sub.add_parser("cos", help="Chief-of-staff stub advise")
    cos_p.add_argument("objective", nargs="?", default="")

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

    args = p.parse_args(argv)

    if args.cmd == "status":
        from . import status

        return _print(status.write_status())

    if args.cmd == "seat":
        from . import blackboard, cos, dag, herdr, status

        obj = (args.objective or "").strip()
        status.set_objective(obj)
        dag.seat_root(obj, reset=bool(args.reset))
        if obj:
            blackboard.post(f"seated: {obj}", author="okstratr", kind="note")
        plan = cos.advise(obj, blackboard.texts(5))
        out = status.write_status()
        out = dict(out)
        out["cos"] = plan
        if args.herdr and obj:
            out["herdr_launch"] = herdr.launch(obj)
        return _print(out)

    if args.cmd == "herdr":
        from . import herdr, status

        obj = (args.objective or "").strip() or status.get_objective()
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

        obj = (args.objective or "").strip() or status.get_objective()
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
