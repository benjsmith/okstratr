"""Slider prices quality; it does not pick N (acceptance tests A–G)."""

from __future__ import annotations

from pathlib import Path

import pytest

from okstratr import orchestration_utility as ou

RESEARCH = (
    "Research the conflicting evidence about scaling laws in this wiki. "
    "Compare sources and say which claims are actually supported. "
    "Why do the pages disagree?"
)


def feat(text: str, s: float) -> ou.TaskFeatures:
    return ou.extract_features(text, preference=s)


def test_a_simple_task_n1_at_every_slider() -> None:
    for s in (0.0, 0.25, 0.5, 0.75, 1.0):
        d = ou.choose_initial_policy(feat("summarise this paragraph in one line.", s))
        assert d.n_investigators == 1, (s, d.arm_id)
        assert not d.include_verify
        assert d.strategy == "single"


def test_b_maximum_buys_cheap_parallelism() -> None:
    f = feat(RESEARCH, 1.0)
    d = ou.choose_initial_policy(f)
    assert d.n_investigators >= 2
    assert d.independence == "high"
    cand = ou.make_candidate(d.arm_id, f)
    assert cand is not None
    # critical-path latency, not N × baseline
    assert cand.lnorm < 1.0 + 0.6 * d.n_investigators


def test_c_diminishing_returns_prefers_three_over_eight() -> None:
    f = feat(RESEARCH, 1.0)
    p3 = ou.make_candidate("ivs_diverse_3", f)
    p8 = ou.make_candidate("swarm_8", f)
    assert p3 is not None and p8 is not None
    assert p8.q - p3.q < 0.05
    assert p3.u(1.0) > p8.u(1.0)
    d = ou.choose_initial_policy(f)
    assert d.n_investigators <= 3
    assert d.arm_id != "swarm_8"


def test_d_better_topology_beats_larger_n() -> None:
    f = feat(RESEARCH, 0.7)
    two = ou.make_candidate("ivs_diverse_2", f)
    four = ou.make_candidate("homog_4", f)
    assert two is not None and four is not None
    assert two.u(0.7) > four.u(0.7)
    d = ou.choose_initial_policy(f)
    assert d.arm_id != "homog_4"


def test_e_economy_can_still_buy_a_verifier() -> None:
    f = feat(
        "Make a consequential legal decision based on conflicting wiki "
        "evidence. This must be correct; the result is irreversible.",
        0.0,
    )
    d = ou.choose_initial_policy(f)
    assert d.include_verify
    assert d.n_investigators == 1
    # fits under the Economy hire cap (2 seats)
    assert d.workers <= ou.worker_ceiling(0.0)


def test_f_maximum_refuses_zero_gain_worker() -> None:
    dq = ou.estimate_marginal_quality(
        action="redundant_copy",
        verification={"conflicts": 0, "unsupported": 0, "confidence": 0.95},
        findings_n=4,
        consequence=0.1,
    )
    assert dq <= 0.01
    dc, dl = ou.estimate_marginal_cost_latency("redundant_copy")
    assert ou.marginal_utility(dq, dc, dl, 1.0) < ou.EXPANSION_THRESHOLD


def test_g_same_n_different_policies() -> None:
    f = feat(RESEARCH, 0.6)
    homog = ou.make_candidate("parallel_homog_2", f)
    diverse = ou.make_candidate("ivs_diverse_2", f)
    assert homog is not None and diverse is not None
    assert homog.n_investigators == diverse.n_investigators == 2
    assert homog.include_verify != diverse.include_verify
    assert diverse.u(1.0) > homog.u(1.0)
    assert homog.u(0.0) != diverse.u(0.0)


def test_lambda_floors_never_zero() -> None:
    assert ou.cost_weight(1.0) == ou.LAMBDA_C_FLOOR > 0
    assert ou.latency_weight(1.0) == ou.LAMBDA_L_FLOOR > 0
    assert ou.cost_weight(0.0) == ou.LAMBDA_C_MAX
    assert ou.cost_weight(1.0) < ou.cost_weight(0.5) < ou.cost_weight(0.0)


def test_hire_cap_is_outer_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import bandit

    f = feat(RESEARCH, 1.0)
    monkeypatch.setattr(bandit, "hire_cap", lambda e: 2)
    d = ou.choose_initial_policy(f)
    assert d.workers <= 2
    # nothing fits → single is always available
    monkeypatch.setattr(bandit, "hire_cap", lambda e: 0)
    assert ou.choose_initial_policy(f).workers == 1


def test_candidates_recorded_with_utility() -> None:
    d = ou.choose_initial_policy(feat(RESEARCH, 0.5))
    assert d.candidates
    best = max(d.candidates, key=lambda c: c["u"])
    assert best["id"] == d.arm_id
    assert {"q", "c", "l", "u", "n"} <= set(best)
    assert len(d.candidates) <= 6


def test_critical_path_latency_counts_parallel_once() -> None:
    nodes = [
        {"id": "a", "deps": []},
        {"id": "b", "deps": []},
        {"id": "c", "deps": ["a", "b"]},
    ]
    cp = ou.critical_path_latency(
        nodes, lambda n: 1.0, id_of=lambda n: n["id"], deps_of=lambda n: n["deps"]
    )
    assert cp == 2.0


def test_features_roundtrip_and_bucket() -> None:
    f = feat(RESEARCH, 0.75)
    g = ou.TaskFeatures.from_dict(f.to_dict())
    assert g == f
    assert f.bucket().startswith("r|")
    assert ou.TaskFeatures.from_dict("junk") == ou.TaskFeatures()


def test_bandit_weights_keep_old_keys_and_add_lambdas() -> None:
    from okstratr import bandit

    w = bandit.utility_weights(1.0)
    for k in ("effort", "w_quality", "w_cost", "cost_unit", "lambda_n", "mu_effort"):
        assert k in w
    assert w["lambda_c"] == ou.LAMBDA_C_FLOOR


def test_maximum_hire_refuses_zero_independence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okstratr import bandit

    monkeypatch.setattr(bandit, "independence_score", lambda *a, **k: 0.0)
    r = bandit.marginal_utility("investigator", ["cos", "investigator"], 1.0)
    assert r["accept"] is False
