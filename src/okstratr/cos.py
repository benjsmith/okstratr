"""Chief of staff — heuristic breakdown of desk objectives into DAG nodes."""

from __future__ import annotations

from time import time
from typing import Any

from . import blackboard, dag, roles, status

# (id, title, objective_fmt, depends_on, role[, prefer_harness[, prefer_model]])
_Step = tuple  # 5–7 tuple; prefer_* optional at indices 5,6

# Default / unspecified kind — keep the historical CoS clarify chain so
# callers that invoke break_down() without a desk stay stable.
_COS_CHAIN: list[_Step] = [
    (
        "cos-clarify",
        "Clarify success criteria",
        "Define done-when / acceptance for: {obj}",
        ["root"],
        roles.ROLE_COS,
    ),
    (
        "cos-gather",
        "Gather context",
        "Collect constraints, priors, and blockers for: {obj}",
        ["cos-clarify"],
        roles.ROLE_COS,
    ),
    (
        "cos-execute",
        "Execute core work",
        "Do the main work toward: {obj}",
        ["cos-gather"],
        roles.ROLE_COS,
    ),
    (
        "cos-verify",
        "Verify outcomes",
        "Check results against success criteria for: {obj}",
        ["cos-execute"],
        roles.ROLE_VERIFIER,
    ),
]

# work / auto — Switchbay investigator / synthesizer / verifier (not only CoS).
_SWITCHBAY: list[_Step] = [
    (
        "investigator",
        "Investigate",
        "Gather evidence and context for: {obj}",
        ["root"],
        roles.ROLE_INVESTIGATOR,
    ),
    (
        "synthesizer",
        "Synthesize",
        "Merge independent opinions into succinct claims for: {obj}",
        ["investigator"],
        roles.ROLE_SYNTHESIZER,
    ),
    (
        "verifier",
        "Verify",
        "Check outcomes against success criteria for: {obj}",
        ["synthesizer"],
        roles.ROLE_VERIFIER,
    ),
]

_CURATE: list[_Step] = [
    (
        "curate-propose",
        "Propose pages",
        "Draft curated pages to land for: {obj}",
        ["root"],
        roles.ROLE_CURATOR_PLANNER,
    ),
    (
        "curate-review",
        "Review drafts",
        "Review proposed pages before commit for: {obj}",
        ["curate-propose"],
        roles.ROLE_CURATOR_JUDGE,
    ),
    (
        "curate-commit",
        "Commit / land",
        "Land reviewed pages (okbay reviews path) for: {obj}",
        ["curate-review"],
        roles.ROLE_CURATOR_JUDGE,
    ),
]

_CODE: list[_Step] = [
    (
        "code-investigate",
        "Investigate",
        "Scope the change and gather context for: {obj}",
        ["root"],
        roles.ROLE_INVESTIGATOR,
    ),
    (
        "code-implement",
        "Implement",
        "Implement the change for: {obj}",
        ["code-investigate"],
        roles.ROLE_PLANNER,
    ),
    (
        "code-verify",
        "Verify",
        "Verify the implementation against criteria for: {obj}",
        ["code-implement"],
        roles.ROLE_VERIFIER,
    ),
]

_DECK: list[_Step] = [
    (
        "deck-outline",
        "Outline",
        "Outline the narrative / brief for: {obj}",
        ["root"],
        roles.ROLE_PLANNER,
    ),
    (
        "deck-synthesize",
        "Synthesize narrative",
        "Merge material into a succinct deck for: {obj}",
        ["deck-outline"],
        roles.ROLE_SYNTHESIZER,
    ),
    (
        "deck-verify",
        "Verify brief",
        "Check the brief against the objective for: {obj}",
        ["deck-synthesize"],
        roles.ROLE_VERIFIER,
    ),
]


def _parse_models_by_harness(raw: str | None = None) -> dict[str, str]:
    """Parse ``grok:grok-4.6,claude:haiku`` (or JSON) into harness→model."""
    import json
    import os

    s = (raw if raw is not None else os.environ.get("OKSTRATR_MODEL_BY_HARNESS") or "").strip()
    if not s:
        return {}
    if s.startswith("{"):
        try:
            data = json.loads(s)
            if isinstance(data, dict):
                return {
                    str(k).strip().lower(): str(v).strip()
                    for k, v in data.items()
                    if str(k).strip() and str(v).strip()
                }
        except json.JSONDecodeError:
            pass
    out: dict[str, str] = {}
    for part in s.replace(" ", ",").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        hid, _, mid = part.partition(":")
        hid = hid.strip().lower()
        mid = mid.strip()
        if hid and mid:
            out[hid] = mid
    return out


def _fanout_harness_ids() -> list[str]:
    """Enabled harnesses for investigator fan-out (preference order).

    Uses OKSTRATR_HARNESS_PREFER when set (≥1 ids); otherwise config enabled list.
    """
    import os

    raw = (os.environ.get("OKSTRATR_HARNESS_PREFER") or "").strip()
    if raw:
        ids = [x.strip().lower() for x in raw.split(",") if x.strip()]
        if ids:
            return ids
    try:
        from .harness import config as harness_config

        cfg = harness_config.load()
        return list(cfg.preference_order())
    except Exception:  # noqa: BLE001
        return []


def _default_model_for(hid: str, models_by: dict[str, str] | None = None) -> str | None:
    models_by = models_by or {}
    if hid in models_by:
        return models_by[hid]
    try:
        from .harness import config as harness_config

        return harness_config.load().default_model_for(hid)
    except Exception:  # noqa: BLE001
        return None


def switchbay_steps(
    *,
    harnesses: list[str] | None = None,
    models_by_harness: dict[str, str] | None = None,
    force_fanout: bool | None = None,
) -> list[_Step]:
    """work/auto template; fan-out parallel investigators when ≥2 harnesses."""
    harns = [h.strip().lower() for h in (harnesses if harnesses is not None else _fanout_harness_ids()) if h and h.strip()]
    models_by = dict(models_by_harness or _parse_models_by_harness())
    do_fan = bool(force_fanout) if force_fanout is not None else len(harns) >= 2
    if not do_fan or len(harns) < 2:
        return list(_SWITCHBAY)

    inv_ids: list[str] = []
    steps: list[_Step] = []
    for hid in harns:
        nid = f"investigator-{hid}"
        inv_ids.append(nid)
        model = _default_model_for(hid, models_by)
        title = f"Investigate ({hid})"
        obj_fmt = f"Gather evidence and context via {hid} for: {{obj}}"
        steps.append(
            (nid, title, obj_fmt, ["root"], roles.ROLE_INVESTIGATOR, hid, model)
        )
    steps.append(
        (
            "synthesizer",
            "Synthesize",
            "Merge independent opinions into succinct claims for: {obj}",
            list(inv_ids),
            roles.ROLE_SYNTHESIZER,
        )
    )
    steps.append(
        (
            "verifier",
            "Verify",
            "Check outcomes against success criteria for: {obj}",
            ["synthesizer"],
            roles.ROLE_VERIFIER,
        )
    )
    return steps


def _unpack_step(step: _Step) -> tuple[str, str, str, list[str], str, str | None, str | None]:
    nid = step[0]
    title = step[1]
    obj_fmt = step[2]
    deps = list(step[3])
    role = step[4]
    prefer_harness = step[5] if len(step) > 5 else None
    prefer_model = step[6] if len(step) > 6 else None
    return nid, title, obj_fmt, deps, role, prefer_harness, prefer_model


def _step_extra(step: _Step) -> dict[str, Any]:
    """Optional plan fields carried at index 7 (node_type, run_id, …)."""
    extra = step[7] if len(step) > 7 else None
    return dict(extra) if isinstance(extra, dict) else {}


# ── utility-chosen shape for work / auto ───────────────────────────

_TITLE_FOR_TYPE = {
    "investigate": "Investigate",
    "verify": "Verify",
    "synthesize": "Synthesize",
    "reduce": "Reduce",
    "execute": "Execute",
}
_ROLE_FOR_TYPE = {
    "investigate": roles.ROLE_INVESTIGATOR,
    "verify": roles.ROLE_VERIFIER,
    "synthesize": roles.ROLE_SYNTHESIZER,
    "reduce": "reducer",
    "execute": "executor",
}


def _escape(text: str) -> str:
    return str(text).replace("{", "{{").replace("}", "}}")


def _models_for_run(
    harnesses: list[str] | None,
    models_by_harness: dict[str, str] | None,
    *,
    effort: float,
    desk_id: str | None = None,
) -> tuple[list[str], dict[str, str], list[tuple[str, str | None]]]:
    """Allowed harnesses, authors' models by effort, and the critic's candidates.

    Pinned models (``OKSTRATR_MODEL_BY_HARNESS`` or ``models_by_harness``)
    win for authors when allowed. If the workspace's lists leave nothing
    allowed, the run falls back to the unfiltered harnesses.
    """
    from . import model_policy

    harns = [
        h.strip().lower()
        for h in (harnesses if harnesses is not None else _fanout_harness_ids())
        if h and h.strip()
    ]
    pinned = dict(models_by_harness or _parse_models_by_harness())
    try:
        out = model_policy.assign_models(
            harns, effort, workspace_id=model_policy.current_workspace_id(desk_id), pinned=pinned
        )
    except Exception:  # noqa: BLE001 — a bad policy file must not block planning
        out = {"harnesses": [], "authors": {}, "pairs": []}
    if not out["harnesses"]:
        models_by = dict(pinned)
        for h in harns:
            if h not in models_by:
                m = _default_model_for(h, models_by)
                if m:
                    models_by[h] = m
        return harns, models_by, []
    models_by = {h: m for h, m in out["authors"].items() if m}
    return list(out["harnesses"]), models_by, list(out["pairs"])


def plan_for(
    objective: str,
    *,
    effort: float | None = None,
    harnesses: list[str] | None = None,
    models_by_harness: dict[str, str] | None = None,
    desk_id: str | None = None,
    run_id: str | None = None,
    task_type: str = "",
) -> tuple[Any, Any]:
    """Pick a recipe by utility and build its plan → (decision, plan).

    Desk runs use what this desk has learned but do not explore: desk panes
    do not report the structured outcomes exploration would learn from.
    """
    from . import bandit, orchestration, orchestration_utility as ou

    harns, models_by, pairs = _models_for_run(
        harnesses, models_by_harness, effort=bandit.clamp_effort(effort), desk_id=desk_id
    )
    e = bandit.clamp_effort(effort)
    feat = ou.extract_features(
        objective, preference=e, provider_diversity=len(harns) or 1, task_type=task_type
    )
    try:
        decision = bandit.choose_recipe(feat, desk_id=desk_id, effort=e, explore=False)
    except Exception:  # noqa: BLE001 — a bad bandit file must not block planning
        decision = ou.choose_initial_policy(feat, effort=e)
    plan = orchestration.plan_from_decision(
        objective, decision, harnesses=harns, models_by_harness=models_by, run_id=run_id,
        critic_pairs=pairs,
    )
    plan = orchestration.ensure_valid(plan)
    return decision, plan


def steps_from_plan(plan: Any) -> list[_Step]:
    """Map plan nodes onto desk DAG steps (stable, readable ids)."""
    investigators = [n for n in plan.nodes if n.node_type == "investigate"]
    single = len(plan.nodes) == 1
    ids: dict[str, str] = {}
    used: set[str] = set()

    def _claim(base: str) -> str:
        nid, k = base, 2
        while nid in used:
            nid = f"{base}-{k}"
            k += 1
        used.add(nid)
        return nid

    for n in plan.nodes:
        t = n.node_type
        if single or (t == "investigate" and len(investigators) == 1):
            ids[n.node_id] = _claim("investigator")
        elif t == "investigate":
            idx = investigators.index(n) + 1
            ids[n.node_id] = _claim(f"investigator-{n.harness}" if n.harness else f"investigator-{idx}")
        elif t == "verify":
            ids[n.node_id] = _claim("verifier")
        elif t == "synthesize":
            ids[n.node_id] = _claim("synthesizer")
        elif t == "reduce":
            ids[n.node_id] = _claim(f"reducer-{n.node_id.split('-')[-1]}")
        else:
            ids[n.node_id] = _claim("executor")

    steps: list[_Step] = []
    for n in plan.nodes:
        t = "investigate" if single else n.node_type
        title = _TITLE_FOR_TYPE.get(t, "Work")
        if t == "investigate" and n.harness and len(investigators) > 1:
            title = f"{title} ({n.harness})"
        if single:
            obj_fmt = "Do the work and answer directly for: {obj}"
        elif t == "investigate":
            obj_fmt = "Gather evidence and context for: " + _escape(n.objective)
        elif t == "verify":
            obj_fmt = "Check each finding against its sources (mark supported / unsupported / conflicting) for: {obj}"
        elif t == "synthesize":
            obj_fmt = "Merge the verified findings into succinct claims for: {obj}"
        elif t == "reduce":
            obj_fmt = _escape(n.objective)
        else:
            obj_fmt = _escape(n.objective)
        deps = [ids[d] for d in n.dependencies if d in ids] or ["root"]
        extra = {
            "node_type": t,
            "run_id": plan.run_id,
            "method_hint": n.method_hint,
            "retrieval_query": n.retrieval_query,
            "independence": n.independence,
        }
        steps.append(
            (ids[n.node_id], title, obj_fmt, deps, _ROLE_FOR_TYPE.get(t, "worker"), n.harness, n.model, extra)
        )
    return steps


KIND_TEMPLATES: dict[str, list[_Step]] = {
    "work": _SWITCHBAY,  # expanded via switchbay_steps() in template_for
    "auto": _SWITCHBAY,
    "curate": _CURATE,
    "code": _CODE,
    "deck": _DECK,
}


def resolve_kind(kind: str | None = None) -> str | None:
    """Explicit kind, else the active desk kind, else None (default CoS chain)."""
    if kind:
        k = kind.strip().lower()
        if k:
            return k
    try:
        from . import desks

        active = desks.default_registry().active()
        if active is not None and active.kind:
            return str(active.kind).strip().lower() or None
    except Exception:  # noqa: BLE001
        return None
    return None


def template_for(kind: str | None) -> list[_Step]:
    """Kind-specific planner template. work/auto → Switchbay (+ multi-harness fan-out)."""
    k = resolve_kind(kind) if kind is None else (kind or "").strip().lower()
    if k in ("work", "auto"):
        return switchbay_steps()
    if k in KIND_TEMPLATES:
        return KIND_TEMPLATES[k]
    return _COS_CHAIN


def advise(
    objective: str,
    blackboard_head: list[str] | None = None,
    *,
    kind: str | None = None,
    steps: list[_Step] | None = None,
    effort: float | None = None,
) -> dict[str, Any]:
    """Return a CoS plan summary (no DAG mutation)."""
    obj = (objective or "").strip() or "(no objective)"
    notes = list(blackboard_head or [])
    if steps is None:
        k = resolve_kind(kind) if kind is None else (kind or "").strip().lower()
        if k in ("work", "auto"):
            try:
                steps = steps_from_plan(plan_for(obj, effort=effort)[1])
            except Exception:  # noqa: BLE001
                steps = None
        if steps is None:
            steps = template_for(kind)
    breakdown = []
    for step in steps:
        nid, title, obj_fmt, deps, role, ph, pm = _unpack_step(step)
        row = {
            "id": nid,
            "title": title,
            "objective": obj_fmt.format(obj=obj),
            "depends_on": list(deps),
            "role": role,
        }
        if ph:
            row["prefer_harness"] = ph
        if pm:
            row["prefer_model"] = pm
        breakdown.append(row)
    return {
        "objective": obj,
        "kind": resolve_kind(kind) if kind is not None else resolve_kind(None),
        "priority": "normal",
        "breakdown": [b["title"] + ": " + b["objective"] for b in breakdown],
        "nodes": breakdown,
        "escalate_if": ["blocked > 30m", "needs human judgment"],
        "blackboard_context": notes[:5],
        "stub": False,
        "heuristic": True,
        "switchbay_roles": [b["role"] for b in breakdown],
    }


def next_action(objective: str, *, kind: str | None = None) -> str:
    plan = advise(objective, kind=kind)
    steps = plan.get("breakdown") or []
    return steps[0] if steps else "Start a desk"


def break_down(
    objective: str | None = None,
    *,
    kind: str | None = None,
    desk_id: str | None = None,
    mark_root_done: bool = True,
    save: bool = True,
    effort: float | None = None,
) -> dict[str, Any]:
    """
    Heuristic (no LLM) expansion of the seated objective into child DAG nodes.

    work/auto → shape chosen by the orchestration utility (investigators →
    verifier → synthesizer, sized by the task); the fixed template is the
    fallback if planning fails.
    Other kinds keep their templates. No kind and no active desk → cos-* chain.
    Idempotent: existing template nodes are left in place (title/objective refreshed).
    """
    g = dag.default_dag()
    obj = (objective or "").strip()
    if not obj:
        root = g.nodes.get("root")
        if root is not None:
            obj = (root.objective or root.title or "").strip()
        if not obj:
            obj = status.get_objective()
    if not obj:
        obj = "(no objective)"

    resolved = resolve_kind(kind)
    decision = None
    plan = None
    if resolved in ("work", "auto"):
        if effort is None:
            effort = _active_effort(desk_id)
        prior_run = next(
            (n.run_id for n in g.nodes.values() if n.run_id and n.role in _AUTO_ROLES), None
        )
        try:
            decision, plan = plan_for(
                obj, effort=effort, desk_id=desk_id, run_id=prior_run, task_type=resolved or ""
            )
            steps = steps_from_plan(plan)
        except Exception:  # noqa: BLE001 — never block a desk on planning
            decision, plan = None, None
            steps = template_for(resolved)
    else:
        steps = template_for(resolved)

    # Ensure root exists
    if "root" not in g.nodes:
        g.seat_root(obj, save=False)
    else:
        root = g.nodes["root"]
        if not (root.objective or "").strip():
            root.objective = obj
        if not (root.title or "").strip() or root.title == "(untitled)":
            root.title = obj

    created: list[str] = []
    updated: list[str] = []
    plan_lines: list[str] = []

    if plan is not None:
        # Drop pending nodes left by an earlier breakdown with another shape.
        keep = {_unpack_step(st)[0] for st in steps}
        for nid, n in list(g.nodes.items()):
            if nid in keep or nid == "root":
                continue
            if n.role in _AUTO_ROLES and n.state in ("pending", "ready"):
                g.remove(nid, save=False)

    for step in steps:
        nid, title, obj_fmt, deps, role, prefer_harness, prefer_model = _unpack_step(step)
        extra = _step_extra(step)
        child_obj = obj_fmt.format(obj=obj)
        tag = f"{nid}: {title} [{role}]"
        if prefer_harness:
            tag += f" harness={prefer_harness}"
        if prefer_model:
            tag += f" model={prefer_model}"
        plan_lines.append(tag)
        if nid in g.nodes:
            n = g.nodes[nid]
            n.title = title
            n.objective = child_obj
            n.depends_on = list(deps)
            n.kind = n.kind or role
            n.role = role
            if prefer_harness:
                n.prefer_harness = prefer_harness
            if prefer_model:
                n.prefer_model = prefer_model
            for k, v in extra.items():
                setattr(n, k, v or ("" if k in ("method_hint", "retrieval_query") else None))
            n.updated_at = time()
            updated.append(nid)
        else:
            g.add(
                nid,
                title,
                depends_on=list(deps),
                kind=role,
                role=role,
                objective=child_obj,
                state="pending",
                prefer_harness=prefer_harness,
                prefer_model=prefer_model,
                save=False,
                **extra,
            )
            created.append(nid)

    if mark_root_done and "root" in g.nodes and g.nodes["root"].state not in ("done", "failed"):
        g.mark_done("root", notes="CoS / planner breakdown complete", save=False)

    g.refresh_ready(save=False)
    if save:
        g.save()

    recipe_line = ""
    if decision is not None:
        recipe_line = f"recipe: {decision.arm_id} — {decision.reason}\n"
        _save_run_plan(plan, decision)
    summary_text = (
        f"CoS plan for: {obj} (kind={resolved or 'default'})\n"
        + recipe_line
        + "\n".join(f"- {line}" for line in plan_lines)
        + f"\n(created={len(created)}, updated={len(updated)})"
    )
    tags = ["cos", "breakdown", resolved or "default"]
    if desk_id:
        tags.append(str(desk_id))
        tags.append(f"desk:{desk_id}")

    def _plan_core(t: str) -> str:
        # Ignore trailing (created=N, updated=M) counters when matching twins.
        lines = [ln.rstrip() for ln in str(t).splitlines() if not ln.startswith("(created=")]
        return "\n".join(lines).strip()

    # Soft dedupe across recent history (not only the last line) so interleaved
    # desk plans do not re-post identical CoS decisions.
    note: dict[str, Any] | None = None
    deduped = False
    core = _plan_core(summary_text)
    for prev in reversed(blackboard.head(24)):
        if str(prev.get("provenance") or "") != "okstratr.cos.break_down":
            continue
        if str(prev.get("kind") or "") != "decision":
            continue
        if str(prev.get("author") or "") != "cos":
            continue
        if _plan_core(str(prev.get("text") or "")) == core:
            note = prev
            deduped = True
            break
    if note is None:
        note = blackboard.post(
            summary_text,
            author="cos",
            kind="decision",
            tags=tags,
            provenance="okstratr.cos.break_down",
            node_id="root",
        )

    ready_ids = [n.id for n in g.ready()]
    node_ids = [_unpack_step(s)[0] for s in steps]
    return {
        "ok": True,
        "objective": obj,
        "kind": resolved,
        "created": created,
        "updated": updated,
        "nodes": node_ids,
        "ready": ready_ids,
        "plan": advise(obj, kind=resolved, steps=steps),
        "blackboard_note_id": note.get("id"),
        "blackboard_deduped": deduped,
        "idempotent": not created and bool(updated),
        "run_id": plan.run_id if plan is not None else None,
        "decision": _decision_summary(decision),
    }


_AUTO_ROLES = frozenset(
    {roles.ROLE_INVESTIGATOR, roles.ROLE_VERIFIER, roles.ROLE_SYNTHESIZER, "reducer", "executor"}
)


def _active_effort(desk_id: str | None) -> float | None:
    try:
        from . import desks

        reg = desks.default_registry()
        d = reg.desks.get(desk_id) if desk_id else reg.active()
        return d.effort if d is not None else None
    except Exception:  # noqa: BLE001
        return None


def _decision_summary(decision: Any) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "recipe": decision.arm_id,
        "reason": decision.reason,
        "explored": decision.explored,
        "n_investigators": decision.n_investigators,
        "include_verify": decision.include_verify,
        "bucket": (decision.features or {}) and _bucket(decision.features),
        "candidates": list(decision.candidates),
    }


def _bucket(features: dict[str, Any]) -> str:
    from . import orchestration_utility as ou

    return ou.TaskFeatures.from_dict(features).bucket()


def _save_run_plan(plan: Any, decision: Any) -> None:
    """Each run gets its own folder: plan.json plus an empty evidence store."""
    try:
        import json

        from . import evidence

        rid = evidence.safe_run_id(plan.run_id)
        d = evidence.run_dir(rid)
        d.mkdir(parents=True, exist_ok=True)
        payload = plan.to_dict()
        payload["decision"] = decision.to_dict()
        (d / "plan.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if not evidence.run_evidence_path(rid).exists():
            evidence.save_run(evidence.open_run(rid))
    except Exception:  # noqa: BLE001
        pass


def should_auto_break(g: dag.Dag | None = None) -> bool:
    """True when the DAG only has root (or is empty) — start may auto-run CoS."""
    graph = g if g is not None else dag.default_dag()
    ids = set(graph.nodes.keys())
    if not ids:
        return True
    return ids == {"root"}
