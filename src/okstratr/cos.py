"""Chief of staff — prioritize / break down / escalate — stub."""

from __future__ import annotations

from typing import Any


def advise(objective: str, blackboard_head: list[str] | None = None) -> dict[str, Any]:
    """Return a stub CoS plan for the seated objective."""
    obj = (objective or "").strip() or "(no objective)"
    notes = list(blackboard_head or [])
    return {
        "objective": obj,
        "priority": "normal",
        "breakdown": [
            f"Clarify success criteria for: {obj}",
            "Open Herdr with the seated objective",
            "Park blockers on the blackboard",
        ],
        "escalate_if": ["blocked > 30m", "needs human judgment"],
        "blackboard_context": notes[:5],
        "stub": True,
    }


def next_action(objective: str) -> str:
    plan = advise(objective)
    steps = plan.get("breakdown") or []
    return steps[0] if steps else "Seat an objective"
