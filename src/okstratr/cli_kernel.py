"""CLI for the orchestration kernel outside desks.

``okstratr findings add|show|list``  seats file and read results (blackboard handback)
``okstratr queue list|show|claim|done``  the file-queue adapter's host side
``okstratr run``                      plan and run one objective
``okstratr loop``                     time-boxed run that okstratr owns
``okstratr host-profile``             how each harness signals done
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def parse_duration(text: str) -> float:
    """'90s', '15m', '2h', '1h30m' or plain seconds → seconds."""
    t = str(text).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", t):
        return float(t)
    parts = re.findall(r"(\d+(?:\.\d+)?)([hms])", t)
    if not parts or "".join(a + b for a, b in parts) != t:
        raise ValueError(f"bad duration: {text!r} (use e.g. 90s, 15m, 2h, 1h30m)")
    mult = {"h": 3600.0, "m": 60.0, "s": 1.0}
    return sum(float(a) * mult[b] for a, b in parts)


def register(sub: Any) -> None:
    f = sub.add_parser("findings", help="File or read seat results for an orchestration run")
    fs = f.add_subparsers(dest="findings_cmd", required=True)
    fa = fs.add_parser("add", help="File findings, verdicts or an answer (JSON) for one seat")
    fa.add_argument("--run", dest="run_id", default=None, help="Run id (default: $OKSTRATR_RUN_ID)")
    fa.add_argument("--node", dest="node_id", default=None, help="Plan node id (default: $OKSTRATR_PLAN_NODE_ID)")
    fa.add_argument("--json", dest="json_text", default=None, help="JSON object")
    fa.add_argument("--file", dest="json_file", default=None, help="Read the JSON object from a file")
    fa.add_argument("--author", default="agent")
    fa.add_argument("--no-post", action="store_true", help="Do not post to the blackboard")
    fsh = fs.add_parser("show", help="Findings in a run's evidence store")
    fsh.add_argument("--run", dest="run_id", default=None)
    fsh.add_argument("--supported", action="store_true", help="Only findings a verifier supported")
    fsh.add_argument("--node", dest="node_id", default=None, help="Show one seat's filed result")
    fl = fs.add_parser("list", help="Seats that filed a result in a run")
    fl.add_argument("--run", dest="run_id", default=None)

    q = sub.add_parser("queue", help="Host side of the file-queue seat adapter")
    qs = q.add_subparsers(dest="queue_cmd", required=True)
    ql = qs.add_parser("list", help="Queued seats")
    ql.add_argument("--run", dest="run_id", default=None)
    ql.add_argument("--state", default=None, choices=["queued", "claimed", "done", "failed"])
    for name, hlp in (("show", "Print one seat's prompt and metadata"), ("claim", "Mark a seat as started")):
        qp = qs.add_parser(name, help=hlp)
        qp.add_argument("run_id")
        qp.add_argument("node_id")
        if name == "claim":
            qp.add_argument("--by", default="")
    qd = qs.add_parser("done", help="Signal that a seat finished (the host's done)")
    qd.add_argument("run_id")
    qd.add_argument("node_id")
    qd.add_argument("--failed", action="store_true")
    qd.add_argument("--tokens", type=int, default=None, help="Tokens the seat used, if known")
    qd.add_argument("--error", default="")

    for name, hlp in (("run", "Plan and run one objective with the kernel"),
                      ("loop", "Time-boxed run: okstratr owns the loop until done, time or budget")):
        r = sub.add_parser(name, help=hlp)
        r.add_argument("objective", nargs="?", default="")
        r.add_argument("--adapter", choices=["queue", "direct"], default="queue")
        r.add_argument("--recipe", default=None, help="Force a recipe (e.g. single, parallel_diverse_k)")
        r.add_argument("--effort", type=float, default=0.5)
        r.add_argument("--harness", dest="harnesses", action="append", default=None)
        r.add_argument("--run-id", dest="run_id", default=None)
        r.add_argument("--host-harness", default=None, help="Resident harness whose done rule applies")
        r.add_argument("--budget-tokens", type=float, default=None)
        r.add_argument("--poll", type=float, default=1.0, help="Queue poll interval, seconds")
        r.add_argument("--seat-timeout", type=float, default=None, help="Seconds before a seat counts as failed")
        if name == "loop":
            r.add_argument("--for", dest="for_", default=None, help="Time box, e.g. 30m or 2h")
            r.add_argument("--max-rounds", type=int, default=12)
            r.add_argument("--resume", action="store_true", help="Continue from runs/<run-id>/loop.json")
        else:
            r.add_argument("--no-learn", action="store_true", help="Do not feed the outcome to the learner")

    h = sub.add_parser("host-profile", help="How a harness signals done and how strong its stop rule is")
    h.add_argument("harness", nargs="?", default=None)


COMMANDS = ("findings", "queue", "run", "loop", "host-profile")


def _read_payload(args: Any) -> dict[str, Any]:
    if args.json_text is not None:
        raw = args.json_text
    elif args.json_file:
        with open(args.json_file, encoding="utf-8") as fh:
            raw = fh.read()
    else:
        raw = sys.stdin.read()
    from . import evidence as ev

    data = ev.parse_json_object(raw)
    if data is None:
        raise ValueError("expected a JSON object")
    return data


def _run_id(args: Any) -> str:
    from . import handback

    rid = args.run_id or handback.default_ids()[0]
    if not rid:
        raise ValueError("run id is required (--run or $OKSTRATR_RUN_ID)")
    return rid


def _findings(args: Any) -> int:
    from . import evidence as ev
    from . import handback

    if args.findings_cmd == "add":
        rid, nid = handback.default_ids()
        out = handback.add(
            _read_payload(args), run_id=args.run_id or rid, node_id=args.node_id or nid,
            author=args.author, post=not args.no_post,
        )
        _print(out)
        return 0
    rid = _run_id(args)
    if args.findings_cmd == "list":
        _print({"run_id": rid, "nodes": handback.list_nodes(rid)})
        return 0
    if args.node_id:
        _print(handback.read(rid, args.node_id) or {})
        return 0
    store = ev.open_run(rid)
    items = ev.supported_findings(store) if args.supported else store.candidates()
    _print({
        "run_id": rid,
        "supported_only": bool(args.supported),
        "findings": [f.to_dict() for f in items],
    })
    return 0


def _queue(args: Any) -> int:
    from .harness import queue as q

    if args.queue_cmd == "list":
        _print(q.list_seats(args.run_id, state=args.state))
    elif args.queue_cmd == "show":
        m = q.show(args.run_id, args.node_id)
        print(m.pop("prompt_text"))
        print("---")
        _print(m)
    elif args.queue_cmd == "claim":
        _print(q.claim(args.run_id, args.node_id, by=args.by))
    else:
        _print(q.done(args.run_id, args.node_id, failed=args.failed, tokens=args.tokens, error=args.error))
    return 0


def _run(args: Any) -> int:
    import time

    from . import host_profile as hp
    from . import kernel_run as kr

    if not args.objective.strip() and not getattr(args, "resume", False):
        raise ValueError("objective is required")
    factory = (kr.queue_runner_factory(poll_s=args.poll, timeout_s=args.seat_timeout)
               if args.adapter == "queue" else kr.direct_runner_factory(timeout=args.seat_timeout))
    host = hp.profile_for(args.host_harness) if args.host_harness else None
    if args.cmd == "run":
        budget = hp.Budget(max_tokens=args.budget_tokens) if args.budget_tokens else None
        out = kr.run_once(
            args.objective, factory, run_id=args.run_id, recipe=args.recipe, effort=args.effort,
            harnesses=args.harnesses, host=host, budget=budget, learn=not args.no_learn,
        )
        out.pop("_run", None)
        out.pop("events", None)
        _print(out)
        return 0
    secs = parse_duration(args.for_) if args.for_ else None
    out = kr.run_loop(
        args.objective, factory, run_id=args.run_id, for_seconds=secs, max_tokens=args.budget_tokens,
        max_rounds=args.max_rounds, recipe=args.recipe, effort=args.effort, harnesses=args.harnesses,
        host=host, clock=time.time, resume=args.resume,
    )
    _print(out)
    return 0


def _host_profile(args: Any) -> int:
    from . import host_profile as hp

    names = [args.harness] if args.harness else list(hp.KNOWN_HARNESSES)
    host = hp.detect_host()
    _print([hp.profile_for(n, host=host).to_dict() for n in names])
    return 0


def dispatch(args: argparse.Namespace) -> int:
    try:
        if args.cmd == "findings":
            return _findings(args)
        if args.cmd == "queue":
            return _queue(args)
        if args.cmd in ("run", "loop"):
            return _run(args)
        return _host_profile(args)
    except (ValueError, KeyError, OSError) as exc:
        print(f"okstratr {args.cmd}: {exc}", file=sys.stderr)
        return 2
