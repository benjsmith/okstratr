"""Parse query slash commands: /harness, /model (plus existing /kind via kernel)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .rungs import parse_model_token


@dataclass
class SlashDirectives:
    """Directives stripped from a query line."""

    kind: str | None = None
    harnesses: list[str] = field(default_factory=list)
    model: str | None = None
    model_harness: str | None = None  # from /model claude:sonnet
    # Multi: /model grok:grok-4.6,claude:haiku
    models_by_harness: dict[str, str] = field(default_factory=dict)
    rung: str | None = None
    cwd: str | None = None
    web: str | None = None  # off|once|session|on|status
    objective: str = ""
    raw_tokens: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "harnesses": list(self.harnesses),
            "model": self.model,
            "model_harness": self.model_harness,
            "models_by_harness": dict(self.models_by_harness),
            "rung": self.rung,
            "cwd": self.cwd,
            "web": self.web,
            "objective": self.objective,
        }


_KIND = ("work", "curate", "code", "deck", "auto")
_KIND_RE = re.compile(
    r"^/(" + "|".join(_KIND) + r")\b",
    flags=re.IGNORECASE,
)


def parse_slash_directives(text: str) -> SlashDirectives:
    """Parse leading slash directives from a query / TUI input line.

    Supported:
      /work|/curate|/code|/deck|/auto   — desk kind
      /harness grok,claude              — prefer these harness ids
      /model grok-4                     — prefer model id
      /model claude:sonnet              — prefer harness + model
      /rung trivial|normal|hard         — effort rung for model select

    Multiple slash tokens can be chained.
    """
    raw = (text or "").strip()
    if not raw:
        return SlashDirectives()

    parts = raw.split()
    kind: str | None = None
    harnesses: list[str] = []
    model: str | None = None
    model_harness: str | None = None
    models_by_harness: dict[str, str] = {}
    rung: str | None = None
    cwd: str | None = None
    web: str | None = None
    i = 0
    consumed: list[str] = []

    while i < len(parts):
        tok = parts[i]
        if not tok.startswith("/"):
            break
        m_kind = _KIND_RE.match(tok)
        if m_kind and len(tok) == len(m_kind.group(0)):
            kind = m_kind.group(1).lower()
            consumed.append(tok)
            i += 1
            continue
        if tok.lower() in ("/harness", "/harnesses"):
            if i + 1 >= len(parts):
                break
            val = parts[i + 1]
            harnesses = [
                x.strip().lower() for x in val.replace(" ", ",").split(",") if x.strip()
            ]
            consumed.extend([tok, val])
            i += 2
            continue
        if tok.lower() == "/model":
            if i + 1 >= len(parts):
                break
            token = parts[i + 1].strip()
            # Multi: grok:grok-4.6,claude:haiku  OR single: grok-4 / claude:sonnet
            if "," in token and ":" in token:
                for part in token.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    hid_i, mid_i = parse_model_token(part)
                    if hid_i and mid_i:
                        models_by_harness[hid_i] = mid_i
                        if hid_i not in harnesses:
                            harnesses.append(hid_i)
                        if model is None:
                            model = mid_i
                            model_harness = hid_i
                consumed.extend([tok, token])
                i += 2
                continue
            hid, mid = parse_model_token(token)
            model = mid
            model_harness = hid
            if hid and mid:
                models_by_harness[hid] = mid
            if hid and hid not in harnesses:
                harnesses = [hid] + harnesses
            consumed.extend([tok, token])
            i += 2
            continue
        if tok.lower() in ("/rung", "/effort"):
            if i + 1 >= len(parts):
                break
            rung = parts[i + 1].strip().lower()
            consumed.extend([tok, rung])
            i += 2
            continue
        if tok.lower() in ("/cd", "/cwd", "/workdir"):
            if i + 1 >= len(parts):
                break
            cwd = parts[i + 1].strip()
            consumed.extend([tok, cwd])
            i += 2
            continue
        if tok.lower() in ("/web", "/egress"):
            if i + 1 >= len(parts):
                # bare /web → status
                web = "status"
                consumed.append(tok)
                i += 1
                continue
            web = parts[i + 1].strip().lower()
            consumed.extend([tok, web])
            i += 2
            continue
        break

    objective = " ".join(parts[i:]).strip()
    return SlashDirectives(
        kind=kind,
        harnesses=harnesses,
        model=model,
        model_harness=model_harness,
        models_by_harness=models_by_harness,
        rung=rung,
        cwd=cwd,
        web=web,
        objective=objective,
        raw_tokens=consumed,
    )


def apply_harness_slash_to_env(directives: SlashDirectives) -> dict[str, str]:
    """Return env overrides implied by slash directives (for start path)."""
    env: dict[str, str] = {}
    if directives.harnesses:
        env["OKSTRATR_HERDR_KIND"] = directives.harnesses[0]
        env["OKSTRATR_HARNESS_PREFER"] = ",".join(directives.harnesses)
    if directives.model_harness and not directives.harnesses:
        env["OKSTRATR_HERDR_KIND"] = directives.model_harness
        env["OKSTRATR_HARNESS_PREFER"] = directives.model_harness
    if directives.models_by_harness:
        # Preserve multi-model map for CoS fan-out + per-node prefer_model.
        env["OKSTRATR_MODEL_BY_HARNESS"] = ",".join(
            f"{k}:{v}" for k, v in directives.models_by_harness.items()
        )
        # Also ensure harness prefer includes those ids
        if not directives.harnesses:
            env["OKSTRATR_HARNESS_PREFER"] = ",".join(directives.models_by_harness.keys())
            env["OKSTRATR_HERDR_KIND"] = next(iter(directives.models_by_harness))
    if directives.model:
        env["OKSTRATR_MODEL"] = directives.model
    if directives.rung:
        env["OKSTRATR_RUNG"] = directives.rung
    return env


SLASH_HELP = (
    "/work|/curate|/code|/deck|/auto  /harness id[,id…]  "
    "/model id|harness:model[,harness:model…]  /rung trivial|normal|hard  "
    "/cd <path>  /web off|once|session|status"
)
