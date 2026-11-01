"""Effort slider → utility weights → orchestration recipe.

The desk effort ``s ∈ [0, 1]`` (Economy → Maximum) sets how much cost and
latency are worth. It does **not** pick the number of workers. N is a
property of whichever recipe has the highest utility

    U(π, s) = Q(π) − λc(s)·Cnorm(π) − λl(s)·Lnorm(π)

with λ(s) = floor + (max − floor)·(1 − s)². Floors stay above zero so even
Maximum refuses a worker that adds no expected quality.

Cost and latency are relative to a cheap single agent (C0 = L0 = 1).
Latency is measured on the critical path, so parallel workers cost about
the slowest branch, not the sum.

``bandit.hire_cap(effort)`` stays an outer ceiling: a recipe whose worker
count does not fit under it is never offered.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

# Preference: 0.0 Economy ← 0.5 Balanced → 1.0 Maximum
PREF_ECONOMY = 0.0
PREF_BALANCED = 0.5
PREF_MAXIMUM = 1.0

# λ(s) = floor + (max − floor) * (1 − s)². Floors stay strictly
# positive so Maximum still refuses zero-gain extra workers.
LAMBDA_C_MAX = 0.30
LAMBDA_C_FLOOR = 0.015
LAMBDA_L_MAX = 0.20
LAMBDA_L_FLOOR = 0.01

# Realized telemetry: cheapest-competent single-agent priors.
C0_TOKENS = 8_000.0
L0_SEC = 25.0

EXPANSION_THRESHOLD = 0.02
EPS = 1e-9

# Recipes. N is a *property* of a recipe, never the search variable.
RECIPES: dict[str, dict[str, Any]] = {
    "single": {
        "n": 1, "verify": False, "diverse": False,
        "ladder": "cheap", "execute": False,
        "why": "cheapest competent single agent",
    },
    "single_strong": {
        "n": 1, "verify": False, "diverse": False,
        "ladder": "strong", "execute": False,
        "why": "one stronger model",
    },
    "single_verify": {
        "n": 1, "verify": True, "diverse": False,
        "ladder": "balanced", "execute": False,
        "why": "one investigator plus a verifier",
    },
    "parallel_homog_2": {
        "n": 2, "verify": False, "diverse": False,
        "ladder": "balanced", "execute": False,
        "why": "two copies of the same model",
    },
    "parallel_diverse_2": {
        "n": 2, "verify": False, "diverse": True,
        "ladder": "balanced", "execute": False,
        "why": "two independent evidence paths",
    },
    "ivs_diverse_2": {
        "n": 2, "verify": True, "diverse": True,
        "ladder": "balanced", "execute": False,
        "why": "two independent investigators then verify",
    },
    "ivs_diverse_3": {
        "n": 3, "verify": True, "diverse": True,
        "ladder": "strong", "execute": False,
        "why": "three diverse investigators then verify",
    },
    "homog_4": {
        "n": 4, "verify": False, "diverse": False,
        "ladder": "balanced", "execute": False,
        "why": "four homogeneous investigators",
    },
    "ivs_homog_4": {
        "n": 4, "verify": True, "diverse": False,
        "ladder": "balanced", "execute": False,
        "why": "four same-model investigators then verify",
    },
    "swarm_8": {
        "n": 8, "verify": True, "diverse": False,
        "ladder": "strong", "execute": False,
        "why": "eight-way swarm (diminishing returns)",
    },
    "tools_verify": {
        "n": 2, "verify": True, "diverse": True,
        "ladder": "balanced", "execute": True,
        "why": "specialists plus deterministic execute and verify",
    },
}

# Nearby policies for conservative exploration. Never a swarm jump.
NEIGHBORS: dict[str, tuple[str, ...]] = {
    "single": ("single_strong", "single_verify"),
    "single_strong": ("single", "single_verify", "parallel_diverse_2"),
    "single_verify": ("single", "ivs_diverse_2"),
    "parallel_homog_2": ("single", "parallel_diverse_2", "ivs_diverse_2"),
    "parallel_diverse_2": ("parallel_homog_2", "ivs_diverse_2", "single_verify"),
    "ivs_diverse_2": ("single_verify", "ivs_diverse_3", "parallel_diverse_2"),
    "ivs_diverse_3": ("ivs_diverse_2", "ivs_homog_4"),
    "homog_4": ("ivs_diverse_2", "parallel_diverse_2"),
    "ivs_homog_4": ("ivs_diverse_2", "ivs_diverse_3"),
    "tools_verify": ("single_verify", "ivs_diverse_2"),
}


def clamp_preference(value: Any, default: float = PREF_BALANCED) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def cost_weight(preference: float) -> float:
    """λc(s): high at Economy, low but never zero at Maximum."""
    s = clamp_preference(preference)
    return LAMBDA_C_FLOOR + (LAMBDA_C_MAX - LAMBDA_C_FLOOR) * (1.0 - s) ** 2


def latency_weight(preference: float) -> float:
    """λl(s): same shape as cost. Floored so zero-gain work is refused."""
    s = clamp_preference(preference)
    return LAMBDA_L_FLOOR + (LAMBDA_L_MAX - LAMBDA_L_FLOOR) * (1.0 - s) ** 2


def utility(q: float, cnorm: float, lnorm: float, preference: float) -> float:
    """U(π, s) = Q − λc(s) Cnorm − λl(s) Lnorm."""
    return (
        float(q)
        - cost_weight(preference) * float(cnorm)
        - latency_weight(preference) * float(lnorm)
    )


def realized_utility(
    *,
    quality: float,
    cost_tokens: float,
    latency_s: float,
    preference: float,
) -> float:
    """Telemetry-time U using observed tokens/seconds vs C0/L0."""
    cnorm = float(cost_tokens) / max(C0_TOKENS, EPS)
    lnorm = float(latency_s) / max(L0_SEC, EPS)
    return utility(quality, cnorm, lnorm, preference)


def marginal_utility(
    dq: float, dc: float, dl: float, preference: float,
) -> float:
    return utility(dq, dc, dl, preference)


@dataclass
class CandidatePolicy:
    """One feasible orchestration topology. N is a field, not the key."""
    policy_id: str
    strategy: str
    n_investigators: int
    include_verify: bool
    include_reduce: bool
    include_execute: bool
    independence: str
    allow_expand: bool
    ladder_bias: str
    diversity: str
    q: float
    cnorm: float
    lnorm: float
    reason: str
    recipe: dict[str, Any] = field(default_factory=dict)

    def u(self, preference: float) -> float:
        return utility(self.q, self.cnorm, self.lnorm, preference)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def estimate_policy_quality(recipe: dict[str, Any], feat: Any) -> float:
    """Coarse prior Q ∈ [0, 1]. Ordering matters more than calibration."""
    n = int(recipe.get("n") or 1)
    verify = bool(recipe.get("verify"))
    diverse = bool(recipe.get("diverse"))
    ladder = str(recipe.get("ladder") or "balanced")
    execute = bool(recipe.get("execute"))
    research = bool(getattr(feat, "research", False))
    difficulty = float(getattr(feat, "difficulty", 0.2) or 0.0)
    consequence = float(getattr(feat, "consequence", 0.1) or 0.0)
    n_sub = int(getattr(feat, "n_subquestions", 1) or 1)
    finance = bool(getattr(feat, "finance", False))
    science = bool(getattr(feat, "science", False))
    experiment = bool(getattr(feat, "experiment", False))
    simple = difficulty < 0.3 and not research and n_sub <= 1
    prompt_len = int(getattr(feat, "prompt_len", 0) or 0)

    q = 0.70
    if simple:
        # Easy work: a stronger model barely helps.
        q = 0.78 if ladder != "cheap" else 0.76
    else:
        if ladder == "cheap":
            q -= 0.08
        elif ladder == "strong":
            q += 0.04
        if research:
            q -= 0.06
        if difficulty >= 0.55:
            q -= 0.06
        if n_sub >= 3:
            q -= 0.05
    # Unverified error is more expensive on consequential work.
    harm = 0.28 * consequence
    if verify:
        harm *= 0.15
        q += 0.04
        if consequence >= 0.45:
            q += 0.16 * consequence
        if research and prompt_len >= 80:
            q += 0.04
        if finance or science:
            q += 0.05
    q -= harm

    # Extra investigators: diversity changes ΔQ, not a mandate to grow N.
    extra_q = {2: 0.10, 3: 0.07, 4: 0.025, 5: 0.012, 6: 0.008, 7: 0.005, 8: 0.004}
    extra_h = {2: 0.03, 3: 0.018, 4: 0.01, 5: 0.006, 6: 0.004, 7: 0.003, 8: 0.002}
    for k in range(2, n + 1):
        add = (extra_q if diverse else extra_h).get(k, 0.002)
        if simple:
            add = min(add, 0.006)
        if n_sub >= k:
            add += 0.03
        q += add
    if execute and experiment:
        q += 0.16
    if simple and n > 1:
        q = min(q, 0.76 + 0.006 * (n - 1))
    return _clip01(q)


def estimate_policy_cost(recipe: dict[str, Any], feat: Any) -> float:
    """Cnorm relative to a cheap single agent. Parallel workers still add cost."""
    n = int(recipe.get("n") or 1)
    verify = bool(recipe.get("verify"))
    execute = bool(recipe.get("execute"))
    ladder = str(recipe.get("ladder") or "balanced")
    c = 1.0
    if ladder == "strong":
        c += 0.35
    elif ladder == "balanced" and n == 1:
        c += 0.15
    if n > 1:
        c += 0.75 * (n - 1)
    if verify:
        c += 0.45 if n == 1 else 0.65
    if execute:
        c += 0.50
    return max(0.05, c)


def estimate_policy_latency(recipe: dict[str, Any], feat: Any) -> float:
    """Lnorm on the DAG critical path — parallel workers ≈ max, not sum."""
    n = int(recipe.get("n") or 1)
    verify = bool(recipe.get("verify"))
    execute = bool(recipe.get("execute"))
    ladder = str(recipe.get("ladder") or "balanced")
    diverse = bool(recipe.get("diverse"))
    l = 1.0
    if ladder == "strong":
        l += 0.12
    if n > 1:
        l = max(l, 1.10 + (0.08 if diverse else 0.02))
    if execute:
        l = max(l, 1.18)
    if verify:
        l += 0.50 if n == 1 else 0.55
    return max(0.05, l)


def _independence(recipe: dict[str, Any], feat: Any) -> str:
    if recipe.get("diverse") or int(recipe.get("n") or 1) >= 2:
        if bool(getattr(feat, "research", False)) or bool(
            getattr(feat, "finance", False) or getattr(feat, "science", False)
        ):
            return "high"
    return str(getattr(feat, "independence", "") or "") or "medium"


def make_candidate(policy_id: str, feat: Any) -> CandidatePolicy | None:
    recipe = RECIPES.get(policy_id)
    if not recipe:
        return None
    n = int(recipe["n"])
    verify = bool(recipe["verify"])
    execute = bool(recipe["execute"])
    if n <= 1 and not verify and not execute:
        strategy = "single"
    elif verify:
        strategy = "investigate_verify_synthesize"
    else:
        strategy = "parallel_investigate"
    ladder = str(recipe["ladder"])
    diverse = bool(recipe["diverse"])
    ind = _independence(recipe, feat)
    if n <= 1 and not diverse:
        # Leave independence to the caller if it already estimated one.
        est = getattr(feat, "independence", None)
        if isinstance(est, str) and est:
            ind = est
        elif bool(getattr(feat, "research", False)) and float(
            getattr(feat, "difficulty", 0) or 0
        ) >= 0.45:
            ind = "high"
        elif float(getattr(feat, "difficulty", 0) or 0) < 0.3 and not getattr(
            feat, "research", False
        ):
            ind = "low"
        else:
            ind = "medium"
    q = estimate_policy_quality(recipe, feat)
    c = estimate_policy_cost(recipe, feat)
    l = estimate_policy_latency(recipe, feat)
    return CandidatePolicy(
        policy_id=policy_id,
        strategy=strategy,
        n_investigators=n,
        include_verify=verify,
        include_reduce=n >= 5,
        include_execute=execute and (
            bool(getattr(feat, "experiment", False))
            or bool(getattr(feat, "finance", False))
        ),
        independence=ind,
        allow_expand=bool(verify),
        ladder_bias=ladder,
        diversity="diverse" if diverse else "homogeneous",
        q=q, cnorm=c, lnorm=l,
        reason=str(recipe.get("why") or policy_id),
        recipe=dict(recipe),
    )


def generate_candidates(feat: Any) -> list[CandidatePolicy]:
    """3–6 sensible policies. Simple tasks stay near single-agent."""
    research = bool(getattr(feat, "research", False))
    difficulty = float(getattr(feat, "difficulty", 0.2) or 0.0)
    n_sub = int(getattr(feat, "n_subquestions", 1) or 1)
    finance = bool(getattr(feat, "finance", False))
    science = bool(getattr(feat, "science", False))
    experiment = bool(getattr(feat, "experiment", False))
    simple = (
        difficulty < 0.3 and not research and n_sub <= 1
        and not finance and not science
    )
    ids: list[str] = ["single", "single_strong"]
    if simple:
        ids.append("parallel_homog_2")
    else:
        if experiment:
            ids.append("tools_verify")
        ids.extend(["single_verify", "parallel_diverse_2", "ivs_diverse_2"])
        hard = difficulty >= 0.55 or finance or science or n_sub >= 3
        if hard:
            ids.append("ivs_diverse_3")
            ids.append("homog_4")
        else:
            ids.append("parallel_homog_2")
    # Bounded set; swarm_8 is test-only via make_candidate.
    seen: set[str] = set()
    out: list[CandidatePolicy] = []
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        c = make_candidate(pid, feat)
        if c is not None:
            out.append(c)
        if len(out) >= 6:
            break
    return out


def choose_initial_candidate(
    feat: Any, *, preference: float | None = None,
) -> CandidatePolicy:
    s = clamp_preference(
        preference if preference is not None else getattr(feat, "preference", PREF_BALANCED)
    )
    cands = generate_candidates(feat)
    if not cands:
        c = make_candidate("single", feat)
        assert c is not None
        return c
    return max(cands, key=lambda c: c.u(s))


def estimate_marginal_quality(
    *,
    action: str,
    verification: dict[str, Any] | None,
    findings_n: int,
    consequence: float,
    unique_sources: int | None = None,
    nodes_so_far: int = 0,
) -> float:
    """Heuristic ΔQ for a proposed extra computation."""
    v = verification or {}
    conflicts = int(v.get("conflicts") or 0)
    unsupported = int(v.get("unsupported") or 0)
    unresolved = v.get("unresolved") or []
    n_unresolved = len(unresolved) if isinstance(unresolved, list) else 0
    try:
        conf = float(v.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    findings = max(1, int(findings_n or 1))
    gap = (
        conflicts > 0
        or (unsupported / findings >= 0.4)
        or n_unresolved > 0
        or conf < 0.4
    )
    if not gap:
        # No remaining uncertainty — extra computation is a copy.
        return 0.0 if action == "redundant_copy" else 0.008
    dq = 0.0
    if action in ("diverse_investigator", "investigator"):
        dq += 0.10 if action == "diverse_investigator" else 0.03
        if unique_sources is not None and nodes_so_far > 0:
            try:
                us = int(unique_sources)
            except (TypeError, ValueError):
                us = 0
            if us < max(1, nodes_so_far - 1):
                dq *= 0.4  # more of the same evidence
        if conflicts:
            dq += 0.08 * min(3, conflicts)
        if unsupported / findings >= 0.4:
            dq += 0.10
        if n_unresolved:
            dq += 0.06 * min(2, n_unresolved)
        if conf < 0.4:
            dq += 0.06
    elif action == "verifier":
        dq += 0.10
        if conflicts:
            dq += 0.10 * min(3, conflicts)
        if unsupported / findings >= 0.4:
            dq += 0.12
        if n_unresolved:
            dq += 0.05 * min(2, n_unresolved)
        dq += 0.14 * max(0.0, min(1.0, consequence))
        if conf < 0.4:
            dq += 0.08
    elif action == "redundant_copy":
        dq = 0.005
        if conflicts == 0 and unsupported == 0 and conf >= 0.8:
            dq = 0.0
    else:
        dq = 0.02
    return _clip01(dq)


def estimate_marginal_cost_latency(action: str) -> tuple[float, float]:
    """(ΔCnorm, ΔLnorm). Extra parallel workers are expensive in C, cheap in L.
    Expansion after verify sits on the critical path, so ΔL is real."""
    if action == "verifier":
        return 0.55, 0.50
    if action == "diverse_investigator":
        return 0.85, 0.70  # run then re-verify
    if action == "investigator":
        return 0.75, 0.65
    if action == "redundant_copy":
        return 0.75, 0.12  # parallel replica
    return 0.70, 0.50


# ---------------------------------------------------------------------------
# Task features (regex heuristics, no model calls)
# ---------------------------------------------------------------------------

_RESEARCH_RE = re.compile(
    r"\b(research|investigat\w*|evidence|compar(e|ison)|analy[sz]|"
    r"why\b|conflict|forecast|uncertain|debate|verif\w*|source|"
    r"contradict|ambiguous|adversarial)\b",
    re.I,
)
_CODE_RE = re.compile(
    r"\b(code|bug|test|implement|refactor|function|compile|traceback|"
    r"stack\s*trace|lint|type.?error)\b",
    re.I,
)
_GRAPH_RE = re.compile(
    r"\b(wiki|graph|vault|knowledge|what do (we|i) know|wikilink|"
    r"neighbors?|page)\b",
    re.I,
)
_LOW_IND_RE = re.compile(
    r"\b(summar(y|ise|ize)|format|rewrite|rephrase|translate|"
    r"bullet|list the|title this|shorten|plain text)\b",
    re.I,
)
_CONSEQ_RE = re.compile(
    r"\b(decision|consequential|legal|medical|safety|irreversible|"
    r"important|high.?stakes|must be (sure|correct|right))\b",
    re.I,
)
_FINANCE_RE = re.compile(
    r"\b(filings?|10-?k|10-?q|8-?k|13f|form 4|earnings|eps|ticker|"
    r"watchlist|alpha|quant|hedge fund|insider|13d|transcript|"
    r"consensus|sector rotation|short interest)\b",
    re.I,
)
_SCIENCE_RE = re.compile(
    r"\b(experiment|hypothesis|lab(oratory)?|assay|protocol|replicate|"
    r"measurement|spectrometer|p-?value|wet lab|autonomous experiment|"
    r"instrument|calibration|control group|ablation)\b",
    re.I,
)
_EXPERIMENT_RE = re.compile(
    r"\b(run the (experiment|protocol|assay)|execute (the )?(protocol|run)|"
    r"measure|instrument|lab (system|rig|device)|autonomous experiment)\b",
    re.I,
)
_MULTI_RE = re.compile(
    r"(?:\?|^\s*\d+[\.\)]\s|^\s*[-*]\s|\band also\b|\bfurthermore\b)",
    re.I | re.M,
)


@dataclass
class TaskFeatures:
    prompt_len: int = 0
    research: bool = False
    graph: bool = False
    code: bool = False
    n_subquestions: int = 1
    difficulty: float = 0.2
    consequence: float = 0.1
    provider_diversity: int = 1
    preference: float = PREF_BALANCED
    finance: bool = False
    science: bool = False
    experiment: bool = False
    task_type: str = ""

    def kind(self) -> str:
        if self.finance:
            return "finance"
        if self.science:
            return "science"
        if self.research:
            return "research"
        if self.code:
            return "code"
        if self.graph:
            return "graph"
        return "general"

    def bucket(self) -> str:
        """Coarse, stable context key for the learner."""
        length = "s" if self.prompt_len < 120 else ("m" if self.prompt_len < 600 else "l")
        kind = {"finance": "f", "science": "e", "research": "r", "code": "c", "graph": "g"}.get(
            self.kind(), "n"
        )
        diff = "h" if self.difficulty >= 0.6 else ("m" if self.difficulty >= 0.3 else "l")
        cons = "c" if self.consequence >= 0.5 else "o"
        pref = int(round(self.preference * 4))  # 0..4
        sub = "m" if self.n_subquestions >= 3 else "1"
        div = "d" if self.provider_diversity >= 2 else "s"
        return f"{kind}|{length}|{diff}|{cons}|p{pref}|{sub}|{div}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> TaskFeatures:
        out = cls()
        if not isinstance(raw, dict):
            return out
        for k in out.__dataclass_fields__:
            if k in raw:
                setattr(out, k, raw[k])
        out.preference = clamp_preference(out.preference)
        return out


def extract_features(
    text: str,
    *,
    preference: float | None = PREF_BALANCED,
    provider_diversity: int = 1,
    graph_available: bool = True,
    task_type: str = "",
) -> TaskFeatures:
    t = text or ""
    n_q = len(re.findall(r"\?", t))
    n_list = len(_MULTI_RE.findall(t))
    n_sub = max(1, n_q + max(0, n_list // 2))
    research = bool(_RESEARCH_RE.search(t))
    code = bool(_CODE_RE.search(t))
    graph = bool(_GRAPH_RE.search(t)) if graph_available else False
    finance = bool(_FINANCE_RE.search(t))
    science = bool(_SCIENCE_RE.search(t))
    experiment = bool(_EXPERIMENT_RE.search(t)) or (
        science and bool(re.search(r"\b(run|execute|measure)\b", t, re.I))
    )
    low = bool(_LOW_IND_RE.search(t))
    cons = 0.55 if _CONSEQ_RE.search(t) else (
        0.5 if finance or science else (0.35 if research else 0.1)
    )
    length = len(t.strip())
    difficulty = 0.15
    if length > 400:
        difficulty += 0.2
    if length > 1200:
        difficulty += 0.15
    if research or finance or science:
        difficulty += 0.25
    if n_sub >= 3:
        difficulty += 0.15
    if code or experiment:
        difficulty += 0.1
    if low and not finance and not science:
        difficulty = min(difficulty, 0.25)
    return TaskFeatures(
        prompt_len=length,
        research=research or finance or science,
        graph=graph,
        code=code,
        n_subquestions=min(8, n_sub),
        difficulty=max(0.0, min(1.0, difficulty)),
        consequence=max(0.0, min(1.0, cons)),
        provider_diversity=max(1, int(provider_diversity or 1)),
        preference=clamp_preference(preference),
        finance=finance,
        science=science,
        experiment=experiment,
        task_type=str(task_type or ""),
    )


def estimate_independence(features: TaskFeatures) -> str:
    if features.finance or features.science or features.consequence >= 0.5 or (
        features.research and features.difficulty >= 0.45
    ):
        return "high"
    if features.difficulty < 0.3 and not features.research and features.n_subquestions <= 1:
        return "low"
    return "medium"


# ---------------------------------------------------------------------------
# Decision: argmax U over candidates, under the hire_cap ceiling
# ---------------------------------------------------------------------------


@dataclass
class PolicyDecision:
    strategy: str
    n_investigators: int
    include_verify: bool
    include_reduce: bool
    independence: str
    allow_expand: bool
    ladder_bias: str
    reason: str
    include_execute: bool = False
    explored: bool = False
    arm_id: str = "single"
    diversity: str = "homogeneous"
    features: dict[str, Any] = field(default_factory=dict)
    preference: float = PREF_BALANCED
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def workers(self) -> int:
        return recipe_workers(self.arm_id) if self.arm_id in RECIPES else (
            self.n_investigators + int(self.include_verify) + int(self.include_execute)
        )


def recipe_workers(policy_id: str) -> int:
    """Seats a recipe needs besides the final synthesizer."""
    r = RECIPES.get(policy_id) or {}
    n = int(r.get("n") or 1)
    if n <= 1 and not r.get("verify") and not r.get("execute"):
        return 1
    return n + int(bool(r.get("verify"))) + int(bool(r.get("execute")))


def worker_ceiling(effort: float | None) -> int:
    """Outer ceiling from the legacy hire cap (never raised by learning)."""
    try:
        from . import bandit

        return max(1, int(bandit.hire_cap(effort)))
    except Exception:  # noqa: BLE001
        return 6


def candidate_table(cands: Iterable[CandidatePolicy], preference: float) -> list[dict[str, Any]]:
    return [
        {
            "id": c.policy_id,
            "n": c.n_investigators,
            "verify": c.include_verify,
            "q": round(c.q, 4),
            "c": round(c.cnorm, 4),
            "l": round(c.lnorm, 4),
            "u": round(c.u(preference), 4),
        }
        for c in cands
    ]


def candidates_within_ceiling(feat: TaskFeatures, effort: float | None = None) -> list[CandidatePolicy]:
    cap = worker_ceiling(feat.preference if effort is None else effort)
    out = [c for c in generate_candidates(feat) if recipe_workers(c.policy_id) <= cap]
    if not out:
        single = make_candidate("single", feat)
        assert single is not None
        out = [single]
    return out


def _candidate_to_decision(
    cand: CandidatePolicy,
    features: TaskFeatures,
    *,
    reason: str | None = None,
    table: list[dict[str, Any]] | None = None,
) -> PolicyDecision:
    independence = cand.independence
    if independence not in ("low", "medium", "high"):
        independence = estimate_independence(features)
    return PolicyDecision(
        strategy=cand.strategy,
        n_investigators=cand.n_investigators,
        include_verify=cand.include_verify,
        include_reduce=cand.include_reduce,
        include_execute=cand.include_execute,
        independence=independence,
        allow_expand=cand.allow_expand,
        ladder_bias=cand.ladder_bias,
        diversity=cand.diversity,
        reason=reason or cand.reason,
        arm_id=cand.policy_id,
        features=features.to_dict(),
        preference=features.preference,
        candidates=list(table or []),
    )


def decision_for_arm(arm_id: str, features: TaskFeatures, *, reason: str = "") -> PolicyDecision | None:
    cand = make_candidate(arm_id, features)
    if cand is None:
        return None
    return _candidate_to_decision(cand, features, reason=reason or None)


def choose_initial_policy(features: TaskFeatures, *, effort: float | None = None) -> PolicyDecision:
    """argmax_π U(π, s) among recipes that fit under hire_cap(effort)."""
    s = features.preference
    cands = candidates_within_ceiling(features, effort)
    best = max(cands, key=lambda c: c.u(s))
    return _candidate_to_decision(best, features, table=candidate_table(cands, s))


def critical_path_latency(
    nodes: Iterable[Any],
    cost_fn: Callable[[Any], float],
    *,
    id_of: Callable[[Any], str] = lambda n: str(getattr(n, "node_id", getattr(n, "id", ""))),
    deps_of: Callable[[Any], list[str]] = lambda n: list(
        getattr(n, "dependencies", None) or getattr(n, "depends_on", None) or []
    ),
) -> float:
    """Longest weighted path through a DAG (parallel branches count once)."""
    items = {id_of(n): n for n in nodes}
    memo: dict[str, float] = {}

    def finish(nid: str, stack: frozenset[str]) -> float:
        if nid in memo:
            return memo[nid]
        if nid in stack or nid not in items:
            return 0.0
        n = items[nid]
        start = max((finish(d, stack | {nid}) for d in deps_of(n)), default=0.0)
        memo[nid] = start + float(cost_fn(n))
        return memo[nid]

    return max((finish(i, frozenset()) for i in items), default=0.0)


# ---------------------------------------------------------------------------
# Independent slices: method hints, retrieval queries, decomposition
# ---------------------------------------------------------------------------

METHOD_HINTS = (
    "primary-sources: start from the original documents; cite each one.",
    "related-material: follow links and references outward from the obvious sources.",
    "corroboration: find a second, independent source for each key claim.",
    "contradiction-seeking: look for claims that disagree; record each conflict.",
)

METHOD_HINTS_FINANCE = (
    "filings: material changes in 10-K/10-Q/8-K; going concern, restatements, auditor changes.",
    "earnings: EPS/revenue vs consensus, guidance, tone vs prior period; cite the transcript.",
    "insider/13F: cluster buys/sells and new institutional positions; cite the form.",
    "sector: competitor, supplier, and regulatory moves that reprice the whole group.",
    "confirmation: a claim is high-conviction only with 2+ independent evidence paths.",
)

METHOD_HINTS_SCIENCE = (
    "prior-art: existing notes and sources for the hypothesis and known failure modes.",
    "protocol: methods, controls, instruments, and what would falsify the claim.",
    "measurement: data, units, replicates, and provenance of each number.",
    "contradiction-seeking: results that disagree with the hypothesis or each other.",
)

_RETRIEVAL_EXTRA = {
    "primary-sources": "source original",
    "related-material": "related references linked",
    "corroboration": "independent corroboration",
    "contradiction-seeking": "contradict disagree conflict",
    "filings": "10-K 10-Q 8-K filing",
    "earnings": "earnings EPS guidance transcript",
    "insider/13f": "Form 4 13F insider",
    "sector": "competitor sector regulatory",
    "confirmation": "independent corroboration",
    "prior-art": "prior art hypothesis",
    "protocol": "protocol controls method",
    "measurement": "measurement data units replicate",
}


def method_hints_for(n: int, independence: str, features: TaskFeatures | None = None) -> list[str]:
    """One distinct method per sibling so parallel seats do not converge."""
    if n <= 1 or independence == "low":
        return [""] * max(0, n)
    if features and features.finance:
        hints = METHOD_HINTS_FINANCE
    elif features and features.science:
        hints = METHOD_HINTS_SCIENCE
    else:
        hints = METHOD_HINTS
    return [hints[i % len(hints)] for i in range(n)]


def retrieval_query_for(objective: str, hint: str = "") -> str:
    """Short, method-specific lookup query, not a copy of the prompt."""
    words = re.findall(r"[A-Za-z0-9_./-]{2,}", objective or "")
    core = " ".join(words[:12])
    head = (hint or "").split(":", 1)[0].strip().lower()
    return f"{core} {_RETRIEVAL_EXTRA.get(head, '')}".strip()[:240]


def _split_subproblems(text: str) -> list[str]:
    items = re.findall(r"(?:^|\n)\s*(?:\d+[\.\)]\s+|[-*]\s+)(.+)", text or "")
    cleaned = [i.strip() for i in items if len(i.strip()) > 8]
    if len(cleaned) >= 2:
        return cleaned
    parts = [p.strip() for p in re.split(r"(?<=[?])\s+", text or "") if p.strip()]
    questions = [p for p in parts if p.endswith("?") and len(p) > 8]
    return questions if len(questions) >= 2 else []


def decompose_tasks(objective: str, n: int, features: TaskFeatures | None = None) -> list[dict[str, Any]]:
    """Deterministic independent slices (no planner model)."""
    n = max(1, int(n))
    obj = (objective or "").strip()
    slices = _split_subproblems(obj)
    independence = estimate_independence(features) if features else "medium"
    hints = method_hints_for(n, "high" if n > 1 else independence, features)
    diff = "hard" if features and features.difficulty >= 0.6 else "normal"
    tasks: list[dict[str, Any]] = []
    for i in range(n):
        hint = hints[i] if i < len(hints) else ""
        if i < len(slices):
            desc = f"{obj}\n\nFocus independently on this subproblem only:\n{slices[i]}"
            rq = retrieval_query_for(slices[i], hint)
        else:
            desc = obj
            rq = retrieval_query_for(obj, hint)
        tasks.append({"description": desc, "difficulty": diff, "retrieval_query": rq, "method_hint": hint})
    return tasks


# ---------------------------------------------------------------------------
# Expansion and the stop rule
# ---------------------------------------------------------------------------


@dataclass
class ExpansionDecision:
    expand: bool
    n_extra: int
    reason: str
    objectives: list[str] = field(default_factory=list)


def choose_expansion(
    *,
    preference: float,
    independence: str,
    allow_expand: bool,
    verification: dict[str, Any] | None,
    findings_n: int,
    expansions_so_far: int,
    nodes_so_far: int,
    remaining_nodes: int,
    consequence: float = 0.1,
    unique_sources: int | None = None,
    max_expansions: int | None = None,
    max_nodes: int | None = None,
) -> ExpansionDecision:
    """Buy another computation only while ΔU > threshold. Hard caps first."""
    from . import limits

    if not allow_expand:
        return ExpansionDecision(False, 0, "expansion disabled by policy")
    cap = limits.MAX_EXPANSIONS if max_expansions is None else int(max_expansions)
    if expansions_so_far >= cap:
        return ExpansionDecision(False, 0, "expansion cap reached")
    hard_nodes = limits.MAX_NODES if max_nodes is None else int(max_nodes)
    if remaining_nodes < 2 or nodes_so_far + 2 > hard_nodes:
        return ExpansionDecision(False, 0, "node budget exhausted")
    s = clamp_preference(preference)
    v = verification or {}
    unresolved = v.get("unresolved") or []
    if not isinstance(unresolved, list):
        unresolved = []

    kw = dict(
        verification=v,
        findings_n=findings_n,
        consequence=consequence,
        unique_sources=unique_sources,
        nodes_so_far=nodes_so_far,
    )
    action = "diverse_investigator" if independence != "low" else "investigator"
    dq = estimate_marginal_quality(action=action, **kw)
    dc, dl = estimate_marginal_cost_latency(action)
    du = marginal_utility(dq, dc, dl, s)
    # The same remaining gaps are worth less on each later wave.
    du -= 0.045 * max(0, expansions_so_far)
    if du <= EXPANSION_THRESHOLD:
        return ExpansionDecision(False, 0, f"ΔU={du:.3f} ≤ threshold (ΔQ={dq:.3f}); stop")

    objectives: list[str] = []
    reasons: list[str] = []
    conflicts = int(v.get("conflicts") or 0)
    unsupported = int(v.get("unsupported") or 0)
    if conflicts > 0:
        reasons.append(f"{conflicts} verification conflict(s)")
        objectives.append(
            "Resolve conflicting findings using source evidence. "
            "Re-read the cited sources and report which claim is supported."
        )
    if unsupported > 0 and findings_n > 0 and unsupported / max(1, findings_n) >= 0.4:
        reasons.append(f"{unsupported} unsupported finding(s)")
        objectives.append(
            "Gather additional evidence for claims currently marked "
            "insufficient. Cite sources; do not restate unsupported claims."
        )
    if unresolved:
        reasons.append(f"{len(unresolved)} unresolved item(s)")
        for u in unresolved[:2]:
            objectives.append(f"Investigate unresolved point: {str(u)[:240]}")
    try:
        conf = float(v.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if conf < 0.4 and findings_n >= 2:
        reasons.append(f"low verifier confidence ({conf:.2f})")
        objectives.append(
            "Independent second look at the original question; focus on evidence the first pass missed."
        )
    if not objectives:
        objectives.append("Independent second look at remaining gaps; cite sources.")
        reasons.append(f"ΔU={du:.3f}")
    extra = 1
    # A second extra worker must clear the threshold on its own.
    room = min(remaining_nodes - 1, hard_nodes - nodes_so_far - 1)
    if extra < room:
        dq2 = estimate_marginal_quality(
            action="redundant_copy" if independence == "low" else "investigator", **kw
        )
        dc2, dl2 = estimate_marginal_cost_latency("investigator")
        if marginal_utility(dq2, dc2, dl2, s) > EXPANSION_THRESHOLD:
            extra = 2
    extra = min(extra, room)
    if extra < 1:
        return ExpansionDecision(False, 0, "no room for extra nodes")
    return ExpansionDecision(True, extra, "; ".join(reasons) or f"ΔU={du:.3f}", objectives[:extra])


def should_continue(
    *,
    preference: float,
    allow_expand: bool,
    objective_met: bool | None,
    gap: str = "",
    verification: dict[str, Any] | None = None,
    findings_n: int = 0,
    expansions_so_far: int = 0,
    nodes_so_far: int = 0,
    remaining_nodes: int = 0,
    consequence: float = 0.1,
    unique_sources: int | None = None,
    last_wave_new_findings: int = 1,
    concat: bool = False,
    max_continuations: int | None = None,
) -> ExpansionDecision:
    """After a synthesizer: keep going only on an explicit 'no' *and* ΔU.

    A missing OBJECTIVE_MET line stops the run, so nothing idles by accident.
    """
    from . import limits

    if concat:
        return ExpansionDecision(False, 0, "concat merge is terminal")
    if objective_met is True:
        return ExpansionDecision(False, 0, "OBJECTIVE_MET: yes")
    if objective_met is None:
        return ExpansionDecision(False, 0, "no stop token; auto-stop")
    if last_wave_new_findings <= 0:
        return ExpansionDecision(False, 0, "no new evidence this wave")
    if not allow_expand:
        return ExpansionDecision(False, 0, "expansion disabled by policy")
    cap = limits.MAX_EXPANSIONS if max_continuations is None else int(max_continuations)
    if expansions_so_far >= cap:
        return ExpansionDecision(False, 0, "continuation cap reached")
    v = dict(verification or {})
    gap_s = (gap or "").strip()
    if gap_s:
        unresolved = v.get("unresolved") or []
        unresolved = list(unresolved) if isinstance(unresolved, list) else []
        unresolved.append(gap_s)
        v["unresolved"] = unresolved
        try:
            conf = float(v.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf >= 0.85:
            # The synthesizer still sees a gap; a high verifier score must not hide it.
            v["confidence"] = min(conf, 0.5)
    return choose_expansion(
        preference=preference,
        independence="high",
        allow_expand=allow_expand,
        verification=v,
        findings_n=findings_n,
        expansions_so_far=expansions_so_far,
        nodes_so_far=nodes_so_far,
        remaining_nodes=remaining_nodes,
        consequence=consequence,
        unique_sources=unique_sources,
        max_expansions=cap,
    )


_OBJECTIVE_MET_RE = re.compile(
    # Horizontal whitespace only, so one line never swallows the next.
    r"^OBJECTIVE_MET:[ \t]*(yes|no)\b(?:[ \t]*[—\-:]*[ \t]*(.*))?$",
    re.I | re.M,
)

OBJECTIVE_MET_INSTRUCTION = (
    "End with one line: OBJECTIVE_MET: yes, or OBJECTIVE_MET: no — <what is still missing>."
)


def parse_objective_met(text: str) -> tuple[bool | None, str]:
    """Last OBJECTIVE_MET line → (True/False/None, gap). None means missing."""
    last = None
    for m in _OBJECTIVE_MET_RE.finditer(text or ""):
        last = m
    if last is None:
        return None, ""
    return last.group(1).lower() == "yes", (last.group(2) or "").strip()


def strip_objective_met(text: str) -> str:
    cleaned = _OBJECTIVE_MET_RE.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
