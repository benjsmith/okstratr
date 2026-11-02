"""Host profiles: what "done" means for each harness, and when okstratr may go past it.

A seat's host (Herdr, the direct CLI adapter, the file queue, a Switchbay
rail agent) decides when that seat is finished. okstratr reads that signal;
it never changes the host's own completion state. What okstratr may do is
open more seats or rounds of its own after the host says done, when its
evidence says the objective is not met.

Rule (``decide_done``):

- Budget or deadline used up: stop, and say which.
- Time-boxed or scheduled runs: okstratr owns the loop. It keeps going until
  the objective is met with no open gaps, or the time box or budget ends.
- Host's stop rule at least as strong as okstratr's, and no open gaps:
  respect the host's done.
- Open gaps (OBJECTIVE_MET: no, failing checks, unresolved or conflicting
  findings): continue past the host's done. The caller still bounds this by
  ΔU at the current effort and by the node/expansion limits.
- Host weaker (e.g. stops on its first answer) and nothing was verified yet:
  add one verify round when ΔU at the current effort pays for it.

Stop-rule strength, weakest first:

- ``first_answer``: the agent stops when it writes an answer (default).
- ``self_check``: the agent re-reads its own answer before stopping.
- ``tests``: the agent runs tests or commands before saying done.
- ``verified``: an independent check runs before done.

Known harnesses all start at ``first_answer``: in headless mode they end on
their first final message, and okstratr cannot see whether they checked.
Configure a stronger rule per harness in ``harnesses.toml``::

    [harness.codex.settings]
    done = "tests"

or with ``OKSTRATR_HOST_DONE="codex=tests,claude=self_check"``.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

STRENGTHS = ("first_answer", "self_check", "tests", "verified")

# How each host reports that a seat is done.
DONE_SIGNALS = {
    "herdr": "agent wait returns (agent idle or exited)",
    "direct": "process exit",
    "queue": "okstratr queue done",
    "switchbay": "rail turn ends",
    "cli": "process exit",
}

# Known harness semantics (headless). Conservative: none verify on their own.
KNOWN_HARNESSES = {
    "grok": "first_answer",
    "claude": "first_answer",
    "codex": "first_answer",
    "pi": "first_answer",
    "opencode": "first_answer",
    "gemini": "first_answer",
    "queue": "first_answer",
    "switchbay": "first_answer",
}

# Verify round: ΔQ for checking an unchecked first answer, and its cost.
VERIFY_ROUND_DQ = 0.06
VERIFY_ROUND_DQ_PER_CONSEQUENCE = 0.10
VERIFY_ROUND_TOKENS = 4000.0
VERIFY_ROUND_SECONDS = 20.0


def strength_rank(name: str) -> int:
    try:
        return STRENGTHS.index(str(name))
    except ValueError:
        return 0


@dataclass
class HostProfile:
    harness: str = "unknown"
    host: str = "cli"
    stop_rule: str = "first_answer"
    done_signal: str = "process exit"
    source: str = "default"

    @property
    def strength(self) -> int:
        return strength_rank(self.stop_rule)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> HostProfile:
        if not isinstance(raw, dict):
            return cls()
        kw = {k: str(raw[k]) for k in cls.__dataclass_fields__ if raw.get(k)}
        p = cls(**kw)
        if p.stop_rule not in STRENGTHS:
            p.stop_rule = "first_answer"
        return p


def _env_overrides(env: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (env.get("OKSTRATR_HOST_DONE") or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if v.strip() in STRENGTHS:
                out[k.strip().lower()] = v.strip()
    return out


def detect_host(env: dict[str, str] | None = None) -> str:
    e = env if env is not None else os.environ
    explicit = (e.get("OKSTRATR_HOST") or "").strip().lower()
    if explicit in DONE_SIGNALS:
        return explicit
    if e.get("OKSTRATR_SWITCHBAY_URL") or e.get("SWITCHBAY_SESSION"):
        return "switchbay"
    if e.get("HERDR_HOME") or e.get("OKSTRATR_HERDR_HOME"):
        return "herdr"
    return "cli"


def profile_for(
    harness: str | None,
    *,
    host: str | None = None,
    cfg: Any | None = None,
    env: dict[str, str] | None = None,
) -> HostProfile:
    """Profile for one harness: env override, then harnesses.toml, then known defaults."""
    e = env if env is not None else os.environ
    hid = (harness or "unknown").strip().lower() or "unknown"
    h = host or detect_host(e)
    rule, source = KNOWN_HARNESSES.get(hid, "first_answer"), "default"
    if cfg is None:
        try:
            from .harness import config as hcfg

            cfg = hcfg.load()
        except Exception:  # noqa: BLE001
            cfg = None
    if cfg is not None:
        try:
            v = str((cfg.settings_for(hid).settings or {}).get("done") or "").strip()
            if v in STRENGTHS:
                rule, source = v, "harnesses.toml"
        except Exception:  # noqa: BLE001
            pass
    env_rule = _env_overrides(e).get(hid)
    if env_rule:
        rule, source = env_rule, "OKSTRATR_HOST_DONE"
    return HostProfile(
        harness=hid, host=h, stop_rule=rule,
        done_signal=DONE_SIGNALS.get(h, "process exit"), source=source,
    )


@dataclass
class Budget:
    """What okstratr may still spend on its own continuation."""

    max_tokens: float | None = None
    deadline: float | None = None  # epoch seconds
    spent_tokens: float = 0.0

    def tokens_left(self) -> float | None:
        if self.max_tokens is None:
            return None
        return max(0.0, float(self.max_tokens) - float(self.spent_tokens))

    def exhausted(self, need_tokens: float = 0.0) -> bool:
        left = self.tokens_left()
        return left is not None and left < max(1.0, need_tokens)

    def past_deadline(self, now: float | None = None) -> bool:
        return self.deadline is not None and (now if now is not None else time.time()) >= self.deadline

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> Budget:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            max_tokens=raw.get("max_tokens"),
            deadline=raw.get("deadline"),
            spent_tokens=float(raw.get("spent_tokens") or 0.0),
        )


@dataclass
class DoneDecision:
    action: str  # respect | continue | verify | stop
    reason: str
    override: bool = False
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def open_gaps(
    *,
    objective_met: bool | None,
    gap: str = "",
    failing_checks: int = 0,
    verification: dict[str, Any] | None = None,
) -> list[str]:
    out: list[str] = []
    if objective_met is False:
        out.append("synthesizer says objective not met" + (f": {gap}" if gap else ""))
    if failing_checks:
        out.append(f"{failing_checks} failing check(s)")
    v = verification or {}
    if int(v.get("conflicts") or 0):
        out.append(f"{int(v['conflicts'])} conflicting finding(s)")
    unresolved = v.get("unresolved") or []
    if isinstance(unresolved, list) and unresolved:
        out.append(f"{len(unresolved)} unresolved question(s)")
    return out


def verify_round_du(preference: float, consequence: float) -> float:
    from . import orchestration_utility as ou

    dq = VERIFY_ROUND_DQ + VERIFY_ROUND_DQ_PER_CONSEQUENCE * max(0.0, min(1.0, consequence))
    return ou.marginal_utility(
        dq, VERIFY_ROUND_TOKENS / ou.C0_TOKENS, VERIFY_ROUND_SECONDS / ou.L0_SEC, preference
    )


def decide_done(
    profile: HostProfile,
    *,
    okstratr_strength: int,
    objective_met: bool | None,
    gap: str = "",
    failing_checks: int = 0,
    verification: dict[str, Any] | None = None,
    verified: bool = False,
    budget: Budget | None = None,
    owner_loop: bool = False,
    preference: float = 0.5,
    consequence: float = 0.1,
    now: float | None = None,
) -> DoneDecision:
    """What to do once the host says the final seat of a round is done."""
    gaps = open_gaps(
        objective_met=objective_met, gap=gap, failing_checks=failing_checks, verification=verification,
    )
    b = budget or Budget()
    if owner_loop and objective_met is True and not gaps:
        return DoneDecision("stop", "objective met", gaps=gaps)
    wants_more = bool(gaps) or owner_loop or (profile.strength < okstratr_strength and not verified)
    if wants_more and b.past_deadline(now):
        return DoneDecision("stop", "time box reached", gaps=gaps)
    if wants_more and b.exhausted():
        return DoneDecision("stop", "budget exhausted", gaps=gaps)
    if owner_loop:
        why = "; ".join(gaps) or "objective not confirmed"
        return DoneDecision(
            "continue", f"time-boxed run: okstratr owns the loop ({why})", override=True, gaps=gaps,
        )
    if gaps:
        return DoneDecision(
            "continue",
            f"host '{profile.harness}' said done ({profile.stop_rule}) but " + "; ".join(gaps),
            override=True, gaps=gaps,
        )
    if profile.strength >= okstratr_strength:
        return DoneDecision(
            "respect",
            f"host '{profile.harness}' stop rule ({profile.stop_rule}) is at least as strong as okstratr's",
        )
    if not verified:
        du = verify_round_du(preference, consequence)
        if du > 0 and not b.exhausted(VERIFY_ROUND_TOKENS):
            return DoneDecision(
                "verify",
                f"host '{profile.harness}' stops on {profile.stop_rule} and nothing was verified "
                f"(ΔU {du:+.3f})",
                override=True,
            )
        return DoneDecision(
            "respect",
            f"host '{profile.harness}' is unverified but a verify round is not worth it here (ΔU {du:+.3f})",
        )
    if objective_met is True:
        return DoneDecision("stop", "objective met (okstratr verified it)")
    return DoneDecision("respect", "no open gaps after verification")
