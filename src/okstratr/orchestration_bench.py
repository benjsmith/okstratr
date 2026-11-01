"""Offline benchmark: utility-chosen orchestration vs the old fixed template.

Runs ten scenarios against fake harnesses (no model calls, no keys). Each
scenario has a hidden set of facts; fake investigators find some of them,
sometimes add a false claim, and a fake verifier checks claims against the
hidden set. An investigator told about a specific missing fact (as
expansion investigators are) has a better chance of finding it. Everything
is deterministic.

    python -m okstratr.orchestration_bench          # table
    python -m okstratr.orchestration_bench --json   # machine-readable

The old template is one investigator per configured harness, then a
synthesizer, then a verifier that checks the answer after it is written.
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

    def __init__(self, sc: Scenario, label: str) -> None:
        self.sc = sc
        self.label = label
        self.facts = [f"fact-{i}" for i in range(sc.n_facts)]
        self.claims: dict[str, list[str]] = {}  # node id → claims
        self.supported: set[str] = set()
        self.lock = threading.Lock()

    def _investigate(self, node: PlanNode) -> list[str]:
        harness = node.harness or (self.sc.harnesses[0] if self.sc.harnesses else "default")
        slot = node.method_hint or node.node_id
        found = [
            f for f in self.facts
            # Same harness tends to find the same facts; a different method finds a few more.
            if _h(self.sc.name, f, harness) < self.sc.find_rate
            or _h(self.sc.name, f, harness, slot) < self.sc.find_rate * 0.35
        ]
        # An investigator told about a specific gap is more likely to close it.
        for f in self.facts:
            if f not in found and f in (node.objective or "") and _h(self.sc.name, f, harness, "targeted") < 0.5:
                found.append(f)
        if _h(self.sc.name, self.label, node.node_id, "false") < self.sc.false_rate:
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
                true = {c for c in seen if c in self.facts}
                false = seen - true
                self.supported |= true
                missing = [f for f in self.facts if f not in self.supported]
            v = {
                "classifications": [],
                "confidence": round(len(self.supported) / max(1, len(self.facts)), 3),
                "unresolved": missing,
                "unsupported": len(false),
                "conflicts": 0,
            }
            return NodeResult(node.node_id, True, json.dumps(v), *COSTS[t])
        # synthesize after a verifier
        with self.lock:
            missing = [f for f in self.facts if f not in self.supported]
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_utility(sc: Scenario) -> Row:
    world = FakeWorld(sc, "utility")
    feat = ou.extract_features(
        sc.objective, preference=sc.effort, provider_diversity=len(sc.harnesses), task_type=sc.task_type
    )
    decision = ou.choose_initial_policy(feat, effort=sc.effort)
    plan = orch.plan_from_decision(sc.objective, decision, harnesses=list(sc.harnesses), run_id=f"bench-{sc.name}")
    hook = orch.AdaptiveRun(plan, harnesses=list(sc.harnesses))
    state = orch.run_plan(plan, world.run, after_node=hook)
    has_verify = any(n.node_type == "verify" for n in state.plan.nodes)
    q, false_n = world.quality(verified_only=has_verify)
    tokens, lat = state.tokens(), round(state.critical_path_s(), 2)
    return Row(
        sc.name, "utility", decision.arm_id, len(state.plan.nodes), tokens, lat, round(q, 3),
        round(ou.realized_utility(quality=q, cost_tokens=tokens, latency_s=lat, preference=sc.effort), 4),
        false_n, expansions=hook.expansions + hook.continuations, failed_nodes=len(state.failed),
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


def run_template(sc: Scenario) -> Row:
    world = FakeWorld(sc, "template")
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
        false_n, failed_nodes=sum(1 for r in results.values() if not r.ok),
    )


def run_all(scenarios: list[Scenario] | None = None) -> list[Row]:
    rows: list[Row] = []
    for sc in scenarios or SCENARIOS:
        rows.append(run_utility(sc))
        rows.append(run_template(sc))
    return rows


def summary(rows: list[Row]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for approach in ("utility", "template"):
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare utility-chosen orchestration with the old template (offline).")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = ap.parse_args(argv)
    rows = run_all()
    if args.json:
        print(json.dumps({"rows": [r.to_dict() for r in rows], "summary": summary(rows)}, indent=2))
    else:
        print(format_table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
