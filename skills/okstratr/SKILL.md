---
name: okstratr
description: >-
  In-harness skill that bundles the okstratr desk-kernel server plus the
  observer panel (CE-style HTML desks/DAG/settings surface — not a second chat).
  Text I/O stays in Herdr / other CLI harnesses; Omarchy may display the observer panel.
---

# okstratr skill

## Product lock

- **Chat / text I/O** stays in Herdr (or other CLI harnesses).
- **okstratr** ships as an **in-harness skill** that starts the desk-kernel
  (`okstratr serve` on `:8767`) and exposes the **observer panel**
  (static HTML control surface: desks / DAG / buttons / settings).
- Omarchy displays the observer panel; chat stays in Herdr.
- **Consent-first:** invoking the skill checks whether serve (+ observer host)
  are running; if not, **prompt the user** before starting
  (`okstratr serve is not running. Start it on :8767 (+ observer panel)?`).
  Do not silently daemonize without consent on the skill path.
  CLI automation may pass `--yes`.

## Install / invoke

From a checkout (editable install):

```bash
pip install -e '.[tui]'   # or: uv pip install -e '.[tui]'
# Optional: copy/link this skill into the harness skill dir
#   skills/okstratr/SKILL.md  →  <harness-skills>/okstratr/SKILL.md
```

Ship paths (relative to the installed package / repo):

| Piece | Path |
|-------|------|
| Server module | `okstratr.server` / `python -m okstratr serve` |
| Lifecycle | `okstratr.lifecycle` |
| Observer panel assets | `okstratr/observer/` (`index.html`, `observer.js`, `observer.css`) |
| This skill | `skills/okstratr/SKILL.md` |

Skill helper (returns JSON-shaped dict):

```python
from okstratr.lifecycle import ensure_running, doctor
ensure_running(prompt=True)  # {running, need_consent, message, …}
doctor()                     # diagnostics + ensure_running(prompt=True)
```

CLI equivalents:

```bash
okstratr doctor
okstratr start          # consent unless already up; --yes to skip
okstratr restart
okstratr shutdown       # stop serve, observer host, okstratr seat children
okstratr status         # status box
okstratr observer       # print observer URL; --serve hosts :8768 dedicated
okstratr panel          # alias of observer
```

## Slash (in-harness / TUI)

```
/okstratr start
/okstratr restart
/okstratr shutdown
/okstratr status
```

Wired in TUI `apply_slash_side_effects`. Same consent rules as CLI (no silent start).

## Observer panel URL

When serve is up: **http://127.0.0.1:8767/observer/**

Dedicated static host (optional): **http://127.0.0.1:8768/** via
`okstratr observer --serve` or `OKSTRATR_OBSERVER_DEDICATED=1`.

The panel is an Omarchy-style desk console (DeskRail left rail + AGENT SPACE
canvas main + config strip). It polls `/api/status`, `/api/dag?desk_id=`,
`/api/desk_session`, `/api/blackboard`, `/api/lifecycle` (~2–3s) and POSTs desk
actions (`/api/desk/focus|start|stop|dismiss|delete`) like Panel.qml.
It has **no chat/objective/query input** — Herdr / CLI harness only. Desk Start
uses standing objective when present. AGENT SPACE draws DAG nodes/edges with
token-flow animation while nodes are working/running.

## See also

- [docs/ADR-003-skill-observer-vs-kernel.md](../../docs/ADR-003-skill-observer-vs-kernel.md)
- [docs/DESK-KERNEL.md](../../docs/DESK-KERNEL.md)
