"""Parse query slash commands: /harness, /model (plus existing /kind via kernel)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SlashDirectives:
    """Directives stripped from a query line."""

    kind: str | None = None
    harnesses: list[str] = field(default_factory=list)
    model: str | None = None
    objective: str = ""
    raw_tokens: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "harnesses": list(self.harnesses),
            "model": self.model,
            "objective": self.objective,
        }


_KIND = ("work", "curate", "code", "deck", "auto")
_KIND_RE = re.compile(
    r"^/(" + "|".join(_KIND) + r")\b",
    flags=re.IGNORECASE,
)
_HARNESS_RE = re.compile(
    r"^/harness(?:es)?\s+([a-z0-9_,\-\s]+)$",
    flags=re.IGNORECASE,
)
_MODEL_RE = re.compile(
    r"^/model\s+(\S+)\s*$",
    flags=re.IGNORECASE,
)


def parse_slash_directives(text: str) -> SlashDirectives:
    """Parse leading slash directives from a query / TUI input line.

    Supported (Phase 1):
      /work|/curate|/code|/deck|/auto   — desk kind (same as kernel)
      /harness grok,claude              — prefer these harness ids (order = preference)
      /model grok-4                     — prefer model id

    Directives may appear as the first token(s); remainder is the objective.
    Multiple slash tokens can be chained: ``/harness grok,claude /model grok-4 ship it``
    """
    raw = (text or "").strip()
    if not raw:
        return SlashDirectives()

    parts = raw.split()
    kind: str | None = None
    harnesses: list[str] = []
    model: str | None = None
    i = 0
    consumed: list[str] = []

    while i < len(parts):
        tok = parts[i]
        if not tok.startswith("/"):
            break
        # /kind
        m_kind = _KIND_RE.match(tok)
        if m_kind and len(tok) == len(m_kind.group(0)):
            kind = m_kind.group(1).lower()
            consumed.append(tok)
            i += 1
            continue
        # /harness a,b  (may span: /harness grok,claude)
        if tok.lower() in ("/harness", "/harnesses"):
            if i + 1 >= len(parts):
                break
            val = parts[i + 1]
            harnesses = [x.strip().lower() for x in val.replace(" ", ",").split(",") if x.strip()]
            consumed.extend([tok, val])
            i += 2
            continue
        # /model id
        if tok.lower() == "/model":
            if i + 1 >= len(parts):
                break
            model = parts[i + 1].strip()
            consumed.extend([tok, model])
            i += 2
            continue
        # Unknown slash — leave in objective
        break

    objective = " ".join(parts[i:]).strip()
    return SlashDirectives(
        kind=kind,
        harnesses=harnesses,
        model=model,
        objective=objective,
        raw_tokens=consumed,
    )


def apply_harness_slash_to_env(directives: SlashDirectives) -> dict[str, str]:
    """Return env overrides implied by slash directives (for start path)."""
    env: dict[str, str] = {}
    if directives.harnesses:
        # First listed harness becomes OKSTRATR_HERDR_KIND override for this seat
        env["OKSTRATR_HERDR_KIND"] = directives.harnesses[0]
        env["OKSTRATR_HARNESS_PREFER"] = ",".join(directives.harnesses)
    if directives.model:
        env["OKSTRATR_MODEL"] = directives.model
    return env
