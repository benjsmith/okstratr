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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="okstratr")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Print and publish status.json")
    seat = sub.add_parser("seat", help="Seat an objective")
    seat.add_argument("objective", nargs="?", default="")
    seat.add_argument("--herdr", action="store_true", help="Also launch/focus Herdr")

    hh = sub.add_parser("herdr", help="Launch/focus Herdr with objective text")
    hh.add_argument("objective", nargs="?", default="")

    bb = sub.add_parser("blackboard", help="Blackboard head or post")
    bb.add_argument("text", nargs="?", default="")
    bb.add_argument("--post", action="store_true")

    cos_p = sub.add_parser("cos", help="Chief-of-staff stub advise")
    cos_p.add_argument("objective", nargs="?", default="")

    sv = sub.add_parser("serve", help="HTTP stub on 8767")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8767)

    args = p.parse_args(argv)

    if args.cmd == "status":
        from . import status

        return _print(status.write_status())

    if args.cmd == "seat":
        from . import blackboard, cos, dag, herdr, status

        obj = (args.objective or "").strip()
        status.set_objective(obj)
        dag.seat_root(obj)
        if obj:
            blackboard.post(f"seated: {obj}", author="okstratr")
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

    return 1
