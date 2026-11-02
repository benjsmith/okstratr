"""When a cheaper author model is worth it.

A cheap model is cheaper per call, but when it fails the work comes back:
another attempt, time spent spinning on the wrong path, and finally a hand-off
to the strong model. This module prices that and learns the failure rate per
(model, task class) from finished runs.

Expected cost of a model with failure rate ``p``, at most ``R`` rework rounds
and spin factor ``s`` (extra cost of a failed attempt, as a share of a call)::

    E[C] = c * sum(p^k, k=0..R) + s * c * sum(p^k, k=1..R+1) + p^(R+1) * c_strong

Latency has the same shape. Quality loses ``p * (1 - detect)`` for failures
nobody catches. The model with the best E[U] at the user's preference wins.

A model with fewer than ``MIN_OBS`` outcomes for a task class is never picked
over the strong one: unknown means strong.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .paths import state_dir

STATE_NAME = "model_routing.json"
MIN_OBS = 3
MAX_REWORK = 2
DEFAULT_SPIN = 0.5
PRIOR_WEIGHT = 2.0
# Share of failures a later check catches, by task class (tests catch more).
DETECT = {"code": 0.9, "finance": 0.75, "science": 0.75, "research": 0.6}
DEFAULT_DETECT = 0.6
TASK_QUALITY = 0.85  # quality of a correct answer; only differences matter

_lock = threading.Lock()


def _path() -> Path:
    return state_dir() / STATE_NAME


def task_class(feat: Any) -> str:
    """Coarse class used as the learning key (finance, science, research, code, graph, general)."""
    kind = getattr(feat, "kind", None)
    if callable(kind):
        return str(kind())
    return str(feat or "general")


def prior_fail(strength: float) -> float:
    """Failure prior from the name-based strength guess (cheap ≈ 0.42, flagship ≈ 0.17)."""
    return max(0.05, min(0.6, 0.55 - 0.5 * float(strength)))


def relative_price(strength: float) -> float:
    """Per-call price relative to a mid-tier model."""
    s = float(strength)
    return 0.2 + 2.0 * s * s


@dataclass
class ModelStats:
    n: int = 0
    fails: int = 0
    rework_rounds: int = 0
    tokens_ok: float = 0.0
    tokens_fail: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> ModelStats:
        out = cls()
        if isinstance(raw, dict):
            for k in out.__dataclass_fields__:
                if k in raw:
                    setattr(out, k, type(getattr(out, k))(raw[k]))
        return out

    def p_fail(self, prior: float) -> float:
        return (self.fails + PRIOR_WEIGHT * prior) / (self.n + PRIOR_WEIGHT)

    def spin(self) -> float:
        ok = self.n - self.fails
        if ok <= 0 or self.fails <= 0 or self.tokens_ok <= 0:
            return DEFAULT_SPIN
        return max(0.0, min(3.0, (self.tokens_fail / self.fails) / (self.tokens_ok / ok) - 1.0))


def _key(model: str | None, cls: str) -> str:
    return f"{(model or '').strip().lower()}|{cls or 'general'}"


def load() -> dict[str, ModelStats]:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: ModelStats.from_dict(v) for k, v in raw.items()}


def save(stats: dict[str, ModelStats]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v.to_dict() for k, v in stats.items()}, indent=2), encoding="utf-8")
    tmp.replace(p)


def record_outcome(
    model: str | None, cls: str, *, failed: bool, rework_rounds: int = 0, tokens: float = 0.0,
    stats: dict[str, ModelStats] | None = None,
) -> ModelStats:
    """Count one author attempt. Pass ``stats`` to update in memory (bench); else the state file."""
    if not model:
        return ModelStats()
    own = stats is None
    with _lock:
        data = load() if own else stats
        st = data.setdefault(_key(model, cls), ModelStats())
        st.n += 1
        st.fails += int(bool(failed))
        st.rework_rounds += max(0, int(rework_rounds))
        if failed:
            st.tokens_fail += float(tokens or 0.0)
        else:
            st.tokens_ok += float(tokens or 0.0)
        if own:
            save(data)
    return st


@dataclass
class Estimate:
    model: str | None
    strength: float
    observed: int
    p_fail: float
    spin: float
    expected_attempts: float
    q: float
    cnorm: float
    lnorm: float
    u: float
    eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate(
    model: str | None, strong: str | None, cls: str, preference: float, *,
    stats: dict[str, ModelStats] | None = None, call_lnorm: float = 1.0,
) -> Estimate:
    """E[U] of putting ``model`` on an author seat, with ``strong`` as the fallback."""
    from . import model_policy
    from . import orchestration_utility as ou

    data = stats if stats is not None else load()
    strength = model_policy.model_strength(model)
    s_strength = model_policy.model_strength(strong)
    st = data.get(_key(model, cls), ModelStats())
    s_st = data.get(_key(strong, cls), ModelStats())
    p = st.p_fail(prior_fail(strength))
    p_s = s_st.p_fail(prior_fail(s_strength))
    spin = st.spin()
    c = relative_price(strength)
    c_s = relative_price(s_strength)
    r = MAX_REWORK
    attempts = sum(p ** k for k in range(r + 1))
    spun = spin * sum(p ** k for k in range(1, r + 2))
    escalate = p ** (r + 1) if model != strong else 0.0
    cnorm = c * (attempts + spun) + escalate * c_s
    lnorm = call_lnorm * (attempts + spun + escalate)
    detect = DETECT.get(cls, DEFAULT_DETECT)
    # A failure that escapes every check ends up in the answer.
    miss = p * (1.0 - detect) if model != strong else p_s * (1.0 - detect)
    q = TASK_QUALITY * (1.0 - miss)
    u = ou.utility(q, cnorm, lnorm, preference)
    eligible = model == strong or st.n >= MIN_OBS
    return Estimate(model, strength, st.n, round(p, 4), round(spin, 3), round(attempts, 3),
                    round(q, 4), round(cnorm, 4), round(lnorm, 4), round(u, 4), eligible)


def choose(
    pool: list[str | None], cls: str, preference: float, *,
    stats: dict[str, ModelStats] | None = None,
) -> tuple[str | None, list[Estimate]]:
    """Best author model in ``pool`` for this task class. Unknown models never beat the strong one."""
    from . import model_policy

    models = [m for m in dict.fromkeys(pool)]
    if not models:
        return None, []
    strong = max(models, key=model_policy.model_strength)
    data = stats if stats is not None else load()
    table = [estimate(m, strong, cls, preference, stats=data) for m in models]
    best = next(e for e in table if e.model == strong)
    for e in table:
        if e.eligible and e.u > best.u + 1e-6:
            best = e
    return best.model, table
