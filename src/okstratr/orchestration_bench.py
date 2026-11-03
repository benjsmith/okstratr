"""Offline benchmark: utility-chosen orchestration vs one agent and vs the old template.

Runs ten scenarios against fake harnesses (no model calls, no keys). Each
scenario has a hidden set of facts; fake investigators find some of them and
sometimes add a false claim. The fake verifier is not an oracle: it marks a
true claim supported with probability ``verifier_recall``, wrongly accepts a
false one with probability ``verifier_fpr``, and only notices a missing fact
with probability ``verifier_recall``. An investigator told about a specific
missing fact (as expansion investigators are) has a better chance of finding
it. Every draw is a hash of (seed, scenario, harness, node, …), never of the
approach, so two approaches that run the same node on the same seed see the
same outcome (common random numbers) and a seed is reproducible.

    python3 -m okstratr.orchestration_bench                # one seed, table
    python3 -m okstratr.orchestration_bench --seeds 20     # mean ± SE, paired Δ, W/T/L
    python3 -m okstratr.orchestration_bench --calibrate    # learn on training seeds, test on held-out
    python3 -m okstratr.orchestration_bench --routing      # cheap vs strong author models
    python3 -m okstratr.orchestration_bench --json

Three approaches per scenario:

- ``single``: one agent that investigates and answers (one node).
- ``template``: the old shape, one investigator per configured harness, then
  a synthesizer, then a verifier that checks the answer after it is written.
- ``utility``: okstratr's choice (argmax U, adaptive expansion).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from . import orchestration as orch
from . import orchestration_utility as ou
from .orchestration import NodeResult, PlanNode

# Fake cost model per node type: (tokens, seconds).
COSTS: dict[str, tuple[int, float]] = {
    "investigate": (2000, 12.0),
    "execute": (2500, 15.0),
    "reduce": (800, 4.0),
    "verify": (1200, 6.0),
    "synthesize": (1000, 6.0),
}
SINGLE_COST = (2000, 12.0)  # one node that investigates and answers
FALSE_CLAIM_PENALTY = 0.2
TIE = 0.005  # |ΔU| below this is a tie
APPROACHES = ("utility", "single", "template")


@dataclass
class Scenario:
    name: str
    objective: str
    effort: float
    harnesses: list[str]
    n_facts: int = 4
    find_rate: float = 0.6
    false_rate: float = 0.25
    failing: list[str] = field(default_factory=list)
    task_type: str = "work"
    verifier_recall: float = 0.9
    verifier_fpr: float = 0.1
    # Run-to-run sampling: any investigator may find a fact its harness usually misses.
    sampling: float = 0.1


SCENARIOS: list[Scenario] = [
    Scenario("trivial-note", "Summarise this note", 0.5, ["grok"], n_facts=1, find_rate=0.95, false_rate=0.05),
    Scenario("trivial-many-harnesses", "Rename the config file", 0.9, ["grok", "claude", "codex"],
             n_facts=1, find_rate=0.95, false_rate=0.05),
    Scenario("research-balanced",
             "Compare the evidence on remote work productivity across sources; which claims disagree and why?",
             0.6, ["grok", "claude"], n_facts=6),
    Scenario("research-economy",
             "Compare the evidence on remote work productivity across sources; which claims disagree and why?",
             0.1, ["grok", "claude"], n_facts=6),
    Scenario("research-maximum-hard",
             "Investigate and compare the published evidence on microplastics in drinking water; "
             "which findings conflict and what explains the difference?",
             1.0, ["grok", "claude", "codex"], n_facts=8, find_rate=0.35),
    Scenario("finance-high-stakes",
             "Should we refinance the company loan now? Compare current rates, fees and covenant risk "
             "across lenders and verify the numbers.",
             0.7, ["grok", "claude"], n_facts=5, false_rate=0.4),
    Scenario("multi-question",
             "What changed in the EU AI Act timeline? Which obligations apply to us? "
             "When do they start? What evidence supports each date?",
             0.6, ["grok", "claude"], n_facts=6),
    Scenario("code-fix", "Fix the failing test in parser.py and run the test suite", 0.6,
             ["codex", "claude"], n_facts=3, find_rate=0.7, task_type="auto"),
    Scenario("research-one-harness",
             "Compare the evidence on four-day work weeks across sources; which claims disagree and why?",
             0.5, ["grok"], n_facts=5),
    Scenario("research-flaky-harness",
             "Compare the evidence on remote work productivity across sources; which claims disagree and why?",
             0.6, ["grok", "claude"], n_facts=6, failing=["claude"]),
]


def _h(*parts: Any) -> float:
    """Deterministic uniform [0, 1) from the parts."""
    d = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(d[:8], "big") / 2**64


class FakeWorld:
    """Hidden facts plus fake harness behaviour for one scenario run."""

    def __init__(self, sc: Scenario, label: str, seed: int = 0) -> None:
        self.sc = sc
        self.label = label
        self.seed = int(seed)
        self.facts = [f"fact-{i}" for i in range(sc.n_facts)]
        self.claims: dict[str, list[str]] = {}  # node id → claims
        self.supported: set[str] = set()
        self.noticed: set[str] = set()  # missing facts some verifier has flagged
        self.judged: dict[str, int] = {}  # claim -> reports seen when last judged; re-judged only on new evidence
        self.lock = threading.Lock()

    def h(self, *parts: Any) -> float:
        return _h(self.seed, self.sc.name, *parts)

    def _investigate(self, node: PlanNode) -> list[str]:
        harness = node.harness or (self.sc.harnesses[0] if self.sc.harnesses else "default")
        rate = self.sc.find_rate
        found = []
        for f in self.facts:
            # What this harness knows: the same harness tends to find the same facts.
            hit = self.h(f, harness) < rate
            # A different method finds a few more; no method hint, no extra draw.
            if not hit and node.method_hint:
                hit = self.h(f, harness, node.method_hint) < rate * 0.35
            # Sampling: any run may turn up something extra, at a low rate.
            if not hit:
                hit = self.h(f, harness, node.node_id, "sample") < rate * self.sc.sampling
            if hit:
                found.append(f)
        # An investigator told about a specific gap is more likely to close it.
        for f in self.facts:
            if f not in found and f in (node.objective or "") and self.h(f, harness, "targeted") < 0.5:
                found.append(f)
        if self.h(harness, node.node_id, "false") < self.sc.false_rate:
            found.append(f"false-{node.node_id}")
        return found

    def run(self, node: PlanNode, inputs: dict[str, NodeResult]) -> NodeResult:
        t = node.node_type
        if node.harness and node.harness in self.sc.failing:
            return NodeResult(node.node_id, False, error="harness unavailable", latency_s=1.0)
        if t in ("investigate", "execute") or (t == "synthesize" and node.node_id == "main"):
            claims = self._investigate(node)
            with self.lock:
                self.claims[node.node_id] = claims
            tok, lat = SINGLE_COST if node.node_id == "main" else COSTS[t]
            body = {"findings": [{"claim": c, "evidence": [{"source": f"{c}@{node.harness}"}], "confidence": 0.7}
                                 for c in claims]}
            text = json.dumps(body)
            if node.node_id == "main":
                text = "Answer.\nOBJECTIVE_MET: yes"
            return NodeResult(node.node_id, True, text, tokens=tok, latency_s=lat)
        if t == "reduce":
            merged: list[str] = []
            with self.lock:
                for d in node.dependencies:
                    merged.extend(self.claims.get(d, []))
                self.claims[node.node_id] = sorted(set(merged))
            body = {"findings": [{"claim": c, "evidence": [{"source": c}]} for c in sorted(set(merged))]}
            return NodeResult(node.node_id, True, json.dumps(body), *COSTS[t])
        if t == "verify":
            with self.lock:
                seen = {c for cs in self.claims.values() for c in cs}
                reports = {c: sum(1 for cs in self.claims.values() if c in cs) for c in seen}
                rejected = 0
                for c in sorted(seen - self.supported):
                    if self.judged.get(c, 0) >= reports[c]:
                        rejected += 1  # no new evidence since it was rejected; the verdict stands
                        continue
                    self.judged[c] = reports[c]
                    ok = c in self.facts
                    p = self.sc.verifier_recall if ok else self.sc.verifier_fpr
                    if self.h(c, node.node_id, "verify") < p:
                        self.supported.add(c)
                    else:
                        rejected += 1
                for f in self.facts:
                    if f not in seen and self.h(f, node.node_id, "notice") < self.sc.verifier_recall:
                        self.noticed.add(f)
                missing = sorted(f for f in self.noticed if f not in seen)
                judged = len(self.supported) + rejected + len(missing)
            v = {
                "classifications": [],
                "confidence": round(len(self.supported) / max(1, judged), 3),
                "unresolved": missing,
                "unsupported": rejected,
                "conflicts": 0,
            }
            return NodeResult(node.node_id, True, json.dumps(v), *COSTS[t])
        # synthesize after a verifier: it can only name gaps a verifier flagged.
        with self.lock:
            seen = {c for cs in self.claims.values() for c in cs}
            missing = sorted(f for f in self.noticed if f not in seen)
        tail = "OBJECTIVE_MET: yes" if not missing else f"OBJECTIVE_MET: no — missing {', '.join(missing)}"
        return NodeResult(node.node_id, True, f"Answer.\n{tail}", *COSTS["synthesize"])

    def final_claims(self, verified_only: bool) -> tuple[set[str], set[str]]:
        seen = {c for cs in self.claims.values() for c in cs}
        final = (seen & self.supported) if verified_only else seen
        true = {c for c in final if c in self.facts}
        return true, final - true

    def quality(self, verified_only: bool) -> tuple[float, int]:
        true, false = self.final_claims(verified_only)
        q = len(true) / max(1, len(self.facts)) - FALSE_CLAIM_PENALTY * len(false)
        return max(0.0, min(1.0, q)), len(false)


@dataclass
class Row:
    scenario: str
    approach: str
    recipe: str
    nodes: int
    tokens: int
    latency_s: float
    quality: float
    utility: float
    unverified_surviving: int
    expansions: int = 0
    failed_nodes: int = 0
    seed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bench_models(sc: Scenario) -> dict[str, Any]:
    """Model picks from the built-in pools, ignoring the user's config and lists."""
    from . import model_policy
    from .harness import config as harness_config

    return model_policy.assign_models(
        list(sc.harnesses), sc.effort, cfg=harness_config.default_config(),
        policy={"allowed": [], "denied": []},
    )


def features_for(sc: Scenario) -> ou.TaskFeatures:
    return ou.extract_features(
        sc.objective, preference=sc.effort, provider_diversity=len(sc.harnesses), task_type=sc.task_type
    )


def run_utility(
    sc: Scenario, seed: int = 0, *, arm: str | None = None, arms: dict[str, Any] | None = None,
    label: str = "utility",
) -> Row:
    """okstratr's run. ``arm`` forces a recipe; ``arms`` warm-starts the learner (no exploration)."""
    world = FakeWorld(sc, label, seed)
    feat = features_for(sc)
    if arm:
        decision = ou.decision_for_arm(arm, feat, reason=f"forced {arm}")
        assert decision is not None, arm
    elif arms:
        decision = ou.decide(feat, arms=arms, effort=sc.effort, explore=False)
    else:
        decision = ou.choose_initial_policy(feat, effort=sc.effort)
    models = _bench_models(sc)
    plan = orch.plan_from_decision(
        sc.objective, decision, harnesses=list(sc.harnesses), run_id=f"bench-{sc.name}",
        models_by_harness=models["authors"], critic_pairs=models["pairs"],
    )
    hook = orch.AdaptiveRun(
        plan, harnesses=list(sc.harnesses), models_by_harness=models["authors"],
        critic_pairs=models["pairs"],
    )
    state = orch.run_plan(plan, world.run, after_node=hook)
    has_verify = any(n.node_type == "verify" for n in state.plan.nodes)
    q, false_n = world.quality(verified_only=has_verify)
    tokens, lat = state.tokens(), round(state.critical_path_s(), 2)
    return Row(
        sc.name, "utility", decision.arm_id, len(state.plan.nodes), tokens, lat, round(q, 3),
        round(ou.realized_utility(quality=q, cost_tokens=tokens, latency_s=lat, preference=sc.effort), 4),
        false_n, expansions=hook.expansions + hook.continuations, failed_nodes=len(state.failed), seed=seed,
    )


def run_single(sc: Scenario, seed: int = 0) -> Row:
    """Baseline: one agent on the first working harness investigates and answers."""
    world = FakeWorld(sc, "single", seed)
    harness = next((h for h in sc.harnesses if h not in sc.failing), sc.harnesses[0] if sc.harnesses else None)
    node = PlanNode("main", "synthesize", sc.objective, harness=harness)
    res = world.run(node, {})
    q, false_n = world.quality(verified_only=False)
    return Row(
        sc.name, "single", "one-agent", 1, res.tokens, round(res.latency_s, 2), round(q, 3),
        round(ou.realized_utility(quality=q, cost_tokens=res.tokens, latency_s=res.latency_s,
                                  preference=sc.effort), 4),
        false_n, failed_nodes=0 if res.ok else 1, seed=seed,
    )


def legacy_template(sc: Scenario) -> list[PlanNode]:
    """Old work/auto shape: investigators → synthesizer → verifier."""
    harns = sc.harnesses if len(sc.harnesses) >= 2 else sc.harnesses[:1]
    invs = [
        PlanNode(f"investigator-{h}", "investigate", sc.objective, harness=h) for h in harns
    ] or [PlanNode("investigator", "investigate", sc.objective)]
    synth = PlanNode("synthesizer", "synthesize", sc.objective, dependencies=[n.node_id for n in invs])
    verify = PlanNode("verifier", "verify", sc.objective, dependencies=["synthesizer"])
    return [*invs, synth, verify]


def run_template(sc: Scenario, seed: int = 0) -> Row:
    world = FakeWorld(sc, "template", seed)
    nodes = legacy_template(sc)
    results: dict[str, NodeResult] = {}
    finish: dict[str, float] = {}
    for n in nodes:  # already in dependency order
        res = world.run(n, {d: results[d] for d in n.dependencies if d in results})
        results[n.node_id] = res
        finish[n.node_id] = max((finish.get(d, 0.0) for d in n.dependencies), default=0.0) + res.latency_s
    tokens = sum(r.tokens for r in results.values())
    lat = round(max(finish.values()), 2)
    # The answer is written before verification, so every claim reaches it.
    q, false_n = world.quality(verified_only=False)
    return Row(
        sc.name, "template", f"fixed:{sum(1 for n in nodes if n.node_type == 'investigate')}", len(nodes),
        tokens, lat, round(q, 3),
        round(ou.realized_utility(quality=q, cost_tokens=tokens, latency_s=lat, preference=sc.effort), 4),
        false_n, failed_nodes=sum(1 for r in results.values() if not r.ok), seed=seed,
    )


def run_all(scenarios: list[Scenario] | None = None, seed: int = 0) -> list[Row]:
    rows: list[Row] = []
    for sc in scenarios or SCENARIOS:
        rows.append(run_utility(sc, seed))
        rows.append(run_single(sc, seed))
        rows.append(run_template(sc, seed))
    return rows


def summary(rows: list[Row]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for approach in APPROACHES:
        rs = [r for r in rows if r.approach == approach]
        if not rs:
            continue
        out[approach] = {
            "mean_utility": round(sum(r.utility for r in rs) / len(rs), 4),
            "mean_quality": round(sum(r.quality for r in rs) / len(rs), 4),
            "total_tokens": sum(r.tokens for r in rs),
            "total_nodes": sum(r.nodes for r in rs),
            "unverified_surviving": sum(r.unverified_surviving for r in rs),
        }
    return out


def format_table(rows: list[Row]) -> str:
    head = f"{'scenario':<24} {'approach':<9} {'recipe':<18} {'nodes':>5} {'tokens':>7} {'lat_s':>6} " \
           f"{'quality':>7} {'U':>7} {'unverif':>7} {'exp':>3}"
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(
            f"{r.scenario:<24} {r.approach:<9} {r.recipe:<18} {r.nodes:>5} {r.tokens:>7} {r.latency_s:>6.1f} "
            f"{r.quality:>7.3f} {r.utility:>7.3f} {r.unverified_surviving:>7} {r.expansions:>3}"
        )
    s = summary(rows)
    lines.append("")
    for k, v in s.items():
        lines.append(
            f"{k}: mean U {v['mean_utility']:.3f}, mean quality {v['mean_quality']:.3f}, "
            f"tokens {v['total_tokens']}, nodes {v['total_nodes']}, unverified claims kept {v['unverified_surviving']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Several seeds: mean ± SE, paired differences, win/tie/loss
# ---------------------------------------------------------------------------


def mean_se(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    if n == 1:
        return m, 0.0
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, (var / n) ** 0.5


def paired(a: list[float], b: list[float], tie: float = TIE) -> dict[str, Any]:
    """a − b per seed: mean ± SE and wins/ties/losses for a."""
    d = [x - y for x, y in zip(a, b)]
    m, se = mean_se(d)
    return {
        "mean": round(m, 4), "se": round(se, 4),
        "win": sum(1 for x in d if x > tie), "tie": sum(1 for x in d if abs(x) <= tie),
        "loss": sum(1 for x in d if x < -tie),
    }


def run_multi(
    k: int = 5, scenarios: list[Scenario] | None = None, *, seed0: int = 0,
    arms_by_scenario: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Every approach on seeds seed0..seed0+k-1, paired by seed."""
    scs = scenarios or SCENARIOS
    seeds = list(range(seed0, seed0 + k))
    per: dict[str, dict[str, list[Row]]] = {}
    for sc in scs:
        arms = (arms_by_scenario or {}).get(sc.name)
        per[sc.name] = {
            "utility": [run_utility(sc, s, arms=arms) for s in seeds],
            "single": [run_single(sc, s) for s in seeds],
            "template": [run_template(sc, s) for s in seeds],
        }
    out_sc: list[dict[str, Any]] = []
    all_u: dict[str, list[float]] = {a: [] for a in APPROACHES}
    for sc in scs:
        rows = per[sc.name]
        entry: dict[str, Any] = {"scenario": sc.name, "seeds": seeds}
        for a in APPROACHES:
            us = [r.utility for r in rows[a]]
            qs = [r.quality for r in rows[a]]
            all_u[a].extend(us)
            mu, se = mean_se(us)
            mq, sq = mean_se(qs)
            entry[a] = {
                "u": round(mu, 4), "u_se": round(se, 4), "q": round(mq, 4), "q_se": round(sq, 4),
                "tokens": round(sum(r.tokens for r in rows[a]) / len(seeds), 1),
                "recipes": sorted({r.recipe for r in rows[a]}),
            }
        u = [r.utility for r in rows["utility"]]
        entry["vs_single"] = paired(u, [r.utility for r in rows["single"]])
        entry["vs_template"] = paired(u, [r.utility for r in rows["template"]])
        out_sc.append(entry)
    overall: dict[str, Any] = {}
    for a in APPROACHES:
        m, se = mean_se(all_u[a])
        overall[a] = {"u": round(m, 4), "u_se": round(se, 4)}
    overall["vs_single"] = paired(all_u["utility"], all_u["single"])
    overall["vs_template"] = paired(all_u["utility"], all_u["template"])
    return {"k": k, "seeds": seeds, "scenarios": out_sc, "overall": overall}


def format_multi(res: dict[str, Any]) -> str:
    head = (f"{'scenario':<24} {'utility U':>15} {'single U':>15} {'template U':>15} "
            f"{'Δ vs single':>16} {'W/T/L':>8} {'Δ vs template':>16} {'W/T/L':>8}")
    lines = [f"{res['k']} seeds ({res['seeds'][0]}–{res['seeds'][-1]}); mean ± SE; ties |ΔU| ≤ {TIE}",
             head, "-" * len(head)]

    def ms(d: dict[str, Any], m: str = "u", s: str = "u_se") -> str:
        return f"{d[m]:.3f} ± {d[s]:.3f}"

    def wtl(d: dict[str, Any]) -> str:
        return f"{d['win']}/{d['tie']}/{d['loss']}"

    for e in res["scenarios"]:
        lines.append(
            f"{e['scenario']:<24} {ms(e['utility']):>15} {ms(e['single']):>15} {ms(e['template']):>15} "
            f"{ms(e['vs_single'], 'mean', 'se'):>16} {wtl(e['vs_single']):>8} "
            f"{ms(e['vs_template'], 'mean', 'se'):>16} {wtl(e['vs_template']):>8}"
        )
    o = res["overall"]
    lines.append("-" * len(head))
    lines.append(
        f"{'all':<24} {ms(o['utility']):>15} {ms(o['single']):>15} {ms(o['template']):>15} "
        f"{ms(o['vs_single'], 'mean', 'se'):>16} {wtl(o['vs_single']):>8} "
        f"{ms(o['vs_template'], 'mean', 'se'):>16} {wtl(o['vs_template']):>8}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Calibration: learn on training seeds, evaluate on held-out seeds
# ---------------------------------------------------------------------------


def calibrate(
    train: int = 30, test: int = 10, scenarios: list[Scenario] | None = None,
) -> dict[str, Any]:
    """Warm-start the recipe learner on training seeds; compare on held-out seeds.

    On each training seed every recipe within the effort ceiling runs once,
    and its realized U feeds that scenario's arm stats (what the bandit would
    have after trying each arm). The report also lists each recipe's prior Q
    next to the quality it actually reached.
    """
    scs = scenarios or SCENARIOS
    arms_by: dict[str, dict[str, Any]] = {}
    prior_vs: dict[str, dict[str, list[float]]] = {}
    for sc in scs:
        feat = features_for(sc)
        arms: dict[str, Any] = {}
        for cand in ou.candidates_within_ceiling(feat, sc.effort):
            st = arms.setdefault(cand.policy_id, {"n": 0, "sum_reward": 0.0, "sum_reward_sq": 0.0,
                                                  "sum_quality_per_node": 0.0})
            pv = prior_vs.setdefault(cand.policy_id, {"prior": [], "realized": []})
            for s in range(train):
                r = run_utility(sc, s, arm=cand.policy_id, label=f"train-{cand.policy_id}")
                st["n"] += 1
                st["sum_reward"] += r.utility
                st["sum_reward_sq"] += r.utility * r.utility
                st["sum_quality_per_node"] += r.quality / max(1, r.nodes)
                pv["prior"].append(cand.q)
                pv["realized"].append(r.quality)
        arms_by[sc.name] = arms
    cold = run_multi(test, scs, seed0=train)
    warm = run_multi(test, scs, seed0=train, arms_by_scenario=arms_by)
    report = []
    for pid, pv in sorted(prior_vs.items()):
        mp, _ = mean_se(pv["prior"])
        mr, se = mean_se(pv["realized"])
        report.append({"recipe": pid, "runs": len(pv["prior"]), "prior_q": round(mp, 3),
                       "realized_q": round(mr, 3), "realized_se": round(se, 3), "gap": round(mr - mp, 3)})
    warm_vs_cold = paired(
        [r for e in warm["scenarios"] for r in [e["utility"]["u"]]],
        [r for e in cold["scenarios"] for r in [e["utility"]["u"]]],
    )
    return {"train_seeds": list(range(train)), "test_seeds": cold["seeds"], "cold": cold, "warm": warm,
            "warm_vs_cold_by_scenario": warm_vs_cold, "prior_vs_realized": report}


def format_calibration(res: dict[str, Any]) -> str:
    lines = ["Prior vs realized quality (training seeds, every recipe tried):",
             f"{'recipe':<20} {'runs':>5} {'prior Q':>8} {'realized Q':>14} {'gap':>7}"]
    for r in res["prior_vs_realized"]:
        lines.append(f"{r['recipe']:<20} {r['runs']:>5} {r['prior_q']:>8.3f} "
                     f"{r['realized_q']:>7.3f} ± {r['realized_se']:.3f} {r['gap']:>+7.3f}")
    lines.append("")
    lines.append(f"Held-out seeds {res['test_seeds'][0]}–{res['test_seeds'][-1]}, prior only (cold):")
    lines.append(format_multi(res["cold"]))
    lines.append("")
    lines.append("Held-out seeds, learner warm-started on training seeds:")
    lines.append(format_multi(res["warm"]))
    w = res["warm_vs_cold_by_scenario"]
    lines.append(f"\nwarm − cold, per scenario mean U: {w['mean']:+.3f} ± {w['se']:.3f} "
                 f"(W/T/L {w['win']}/{w['tie']}/{w['loss']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cheap vs strong author models (model_routing)
# ---------------------------------------------------------------------------


@dataclass
class RoutingScenario:
    name: str
    task_class: str
    effort: float
    # True per-attempt failure rate and spin (extra cost of a failed attempt) per model.
    fail: dict[str, float]
    spin: dict[str, float]


ROUTING_MODELS = ("claude-haiku", "claude-sonnet-4")
ROUTING_SCENARIOS: list[RoutingScenario] = [
    # Cheap wins: a small, test-checked fix the cheap model rarely gets wrong.
    RoutingScenario("cheap-wins-small-fix", "code", 0.2,
                    fail={"claude-haiku": 0.08, "claude-sonnet-4": 0.05},
                    spin={"claude-haiku": 0.3, "claude-sonnet-4": 0.3}),
    # Cheap loses: hard research where the cheap model fails often and spins long.
    RoutingScenario("cheap-loses-hard-research", "research", 0.2,
                    fail={"claude-haiku": 0.6, "claude-sonnet-4": 0.15},
                    spin={"claude-haiku": 1.5, "claude-sonnet-4": 0.4}),
]


def _routing_attempts(rs: RoutingScenario, model: str, seed: int, strong: str) -> dict[str, Any]:
    """Simulate one author seat: attempts on ``model`` with rework, then escalate to ``strong``."""
    from . import model_policy
    from . import model_routing as mr

    cost = lat = 0.0
    attempts: list[bool] = []
    detect = mr.DETECT.get(rs.task_class, mr.DEFAULT_DETECT)
    good = False
    for k in range(mr.MAX_REWORK + 1):
        failed = _h("route", rs.name, seed, model, k) < rs.fail[model]
        price = mr.relative_price(model_policy.model_strength(model))
        cost += price * (1.0 + (rs.spin[model] if failed else 0.0))
        lat += 1.0 + (rs.spin[model] if failed else 0.0)
        attempts.append(failed)
        if not failed:
            good = True
            break
        if _h("route-detect", rs.name, seed, model, k) >= detect:
            break  # nobody noticed; the bad answer ships
    else:
        if model != strong:
            failed = _h("route", rs.name, seed, strong, "escalate") < rs.fail[strong]
            cost += mr.relative_price(model_policy.model_strength(strong))
            lat += 1.0
            good = not failed
    q = mr.TASK_QUALITY if good else 0.0
    return {"attempts": attempts, "good": good, "q": q, "cnorm": cost, "lnorm": lat,
            "u": ou.utility(q, cost, lat, rs.effort)}


def routing_bench(train: int = 20, test: int = 20) -> dict[str, Any]:
    """Learn failure rates on training seeds (both models tried), then route held-out seeds."""
    from . import model_routing as mr
    from .model_policy import model_strength

    strong = max(ROUTING_MODELS, key=model_strength)
    cheap = min(ROUTING_MODELS, key=model_strength)
    rows = []
    for rs in ROUTING_SCENARIOS:
        cold_pick, _ = mr.choose(list(ROUTING_MODELS), rs.task_class, rs.effort, stats={})
        stats: dict[str, mr.ModelStats] = {}
        for s in range(train):
            for m in ROUTING_MODELS:
                for failed in _routing_attempts(rs, m, s, strong)["attempts"]:
                    mr.record_outcome(m, rs.task_class, failed=failed, tokens=2000 * (1.5 if failed else 1.0),
                                      stats=stats)
        warm_pick, table = mr.choose(list(ROUTING_MODELS), rs.task_class, rs.effort, stats=stats)
        seeds = range(train, train + test)
        by_model = {m: [_routing_attempts(rs, m, s, strong)["u"] for s in seeds] for m in ROUTING_MODELS}
        routed = by_model[warm_pick]
        rows.append({
            "scenario": rs.name, "task_class": rs.task_class, "effort": rs.effort,
            "cold_pick": cold_pick, "warm_pick": warm_pick,
            "u": {m: round(mean_se(v)[0], 4) for m, v in by_model.items()},
            "u_se": {m: round(mean_se(v)[1], 4) for m, v in by_model.items()},
            "routed_vs_strong": paired(routed, by_model[strong]),
            "routed_vs_cheap": paired(routed, by_model[cheap]),
            "estimates": [e.to_dict() for e in table],
        })
    return {"train_seeds": train, "test_seeds": test, "rows": rows}


def format_routing(res: dict[str, Any]) -> str:
    lines = [f"Author model routing; learned on {res['train_seeds']} seeds, scored on {res['test_seeds']} more",
             f"{'scenario':<28} {'unknown→':<16} {'learned→':<16} "
             + " ".join(f"{m + ' U':>22}" for m in ROUTING_MODELS)]
    for r in res["rows"]:
        lines.append(
            f"{r['scenario']:<28} {r['cold_pick']:<16} {r['warm_pick']:<16} "
            + " ".join(f"{r['u'][m]:>13.3f} ± {r['u_se'][m]:.3f}" for m in ROUTING_MODELS)
        )
        vs = r["routed_vs_strong"]
        lines.append(f"{'':<28} routed − strong ΔU {vs['mean']:+.3f} ± {vs['se']:.3f} "
                     f"(W/T/L {vs['win']}/{vs['tie']}/{vs['loss']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare utility-chosen orchestration with one agent and the old template (offline).")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    ap.add_argument("--seeds", type=int, default=0, help="run this many seeds and report mean ± SE and paired Δ")
    ap.add_argument("--seed", type=int, default=0, help="seed for the single-seed table")
    ap.add_argument("--calibrate", action="store_true", help="learn on training seeds, evaluate on held-out seeds")
    ap.add_argument("--train", type=int, default=30, help="training seeds for --calibrate (10 overfits on small tasks)")
    ap.add_argument("--routing", action="store_true", help="cheap vs strong author models")
    args = ap.parse_args(argv)
    if args.routing:
        res = routing_bench()
        print(json.dumps(res, indent=2) if args.json else format_routing(res))
        return 0
    if args.calibrate:
        res = calibrate(train=args.train, test=args.seeds or 10)
        print(json.dumps(res, indent=2) if args.json else format_calibration(res))
        return 0
    if args.seeds:
        res = run_multi(args.seeds, seed0=args.seed)
        print(json.dumps(res, indent=2) if args.json else format_multi(res))
        return 0
    rows = run_all(seed=args.seed)
    if args.json:
        print(json.dumps({"rows": [r.to_dict() for r in rows], "summary": summary(rows)}, indent=2))
    else:
        print(format_table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
