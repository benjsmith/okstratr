# Okstratr

**Desk-brain orchestrator** — durable DAG of work, chief-of-staff, scheduling, and a shared blackboard — paired with **Herdr** (or other CLI harnesses) for agent text I/O.

Plugin id: `benjsmith.okstratr` · HTTP: **127.0.0.1:8767** (okbay keeps **8766**)

## Product story

After three iterations (Omarchy QML plugin → CLI → skill + observer), the coherent shape is:

| Surface | Role |
|---------|------|
| **Kernel daemon** (`okstratr serve` / `start`) | SSOT for desks, DAG, CoS, blackboard, harness seating, HTTP API |
| **Skill** (`skills/okstratr/SKILL.md`) | In-harness entry that ships the server + **observer panel** |
| **Observer panel** (`/observer/`) | **Primary visual console** — desks / AGENT SPACE / blackboard / settings; **no chat or objective query bar** |
| **Herdr / CLI harnesses** | **Text I/O** (prompts, conversation, agent terminals) |
| **Omarchy QML** (`Panel.qml`, bar, DeskRail) | **Optional thin client** — bar chip + can open observer; **not** the main console anymore |

Mac path: install skill + run lifecycle CLI + open the observer panel. Omarchy guest may still load the QML plugin; prefer opening the observer for the shared console.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (kept vs legacy surfaces), [docs/ADR-003-skill-observer-vs-kernel.md](docs/ADR-003-skill-observer-vs-kernel.md), and [docs/ADR-001-cli-tui-harness.md](docs/ADR-001-cli-tui-harness.md).

## Relationship

| Piece | Role |
|-------|------|
| **okbay** (`benjsmith.okbay`) | Knowledge graph + Atlas + Nautilus reveal + work-coverage ingest |
| **okstratr** (this repo) | Desk brain — kernel, desks, durable DAG, CoS, schedule, blackboard, harness registry; visual = **observer panel** |
| **Herdr** (native Omarchy) | Agent **runtime / multiplexer** — panes, workspaces, agent lifecycle, socket API |

Work-coverage default lives in **okbay** (magical all-`~/Work`). **Biocure** is the current demo workspace. okstratr desks bind the active okbay workspace / thread ids — they do not ingest.

**okstratr** owns plan + memory of the desk; **Herdr / CLI** owns live agent text. Flow: desk start → kernel hires CoS + roles → CoS expand DAG → for ready nodes `herdr run-ready` (start/prompt/wait/**stop**) → post outcomes to blackboard → advance DAG.

**Finite-job rule:** never leave Grok/Herdr agents running after a node — always stop/release.

## Skill + observer panel

```bash
# Install (editable) + optional skill copy into your harness skills dir
uv pip install -e '.[dev]'   # or: pip install -e '.[dev]'

# Lifecycle (consent on start unless --yes)
okstratr doctor
okstratr start            # prompts if serve is down
okstratr start --yes      # automation / already consented
okstratr status           # status box
okstratr restart
okstratr shutdown

# Observer panel (primary visual; when serve is up)
open http://127.0.0.1:8767/observer/   # also /panel/
okstratr observer                     # prints URL
okstratr panel --serve                # optional dedicated :8768 host
```

In-harness slash:

```
/okstratr start | restart | shutdown | status
```

### Mac CLI workflow (primary path)

```bash
# No Herdr on Mac → direct CLI seating (grok / claude / …)
okstratr config set backend direct
okstratr config set harness.grok.default_model grok-4.6
okstratr config set harness.grok.settings.reasoning low

okstratr start --yes          # daemon + observer on :8767
open http://127.0.0.1:8767/observer/

# Text I/O: your harness CLI (grok / claude / …) or Herdr if installed

okstratr agents
okstratr agents --desk <desk_id>
okstratr harness list
okstratr model list
```

`drive_herdr: true` from a client means **drive seats** — with `backend=direct`
that is `harness.direct` (cwd sandbox + grok-4.6 + `--reasoning-effort low`), not a
Herdr pane start. Direct `grok` seats use a **positional** prompt (not `--prompt`).
`GET /api/dag` reads the focused desk's `desks/<id>/dag.json`.

Every seat (Herdr + direct) labels with `desk_id` + `thread_id`. Config file:
`~/.config/okstratr/harnesses.toml`.

> **Switchbay release pending** — deep parity check against Switchbay once that tree is available.

### Future workspaces (vision)

1. **Fullscreen Atlas** — okbay knowledge plane
2. **Linked Nautilus** — file reveal next to Atlas
3. **okstratr observer + Herdr side by side** — orchestrator console + agent session

## What works today

- Omarchy kinds: `service`, `bar-widget`, `panel` (optional thin client; no Atlas overlay)
- **Five default standing desks** always exposed by status/API/UI: `work`, `curate`, `code`, `deck`, `auto` (`idle|working|quiet`; dismiss returns the kind to idle)
- **Desk lifecycle**: `desk start|stop|dismiss|status|schedule`
- **Kernel**: live **effort-bandit** hire / ensure_cos / retire_worker; persist org + effort + model hints
- **Web egress gate**: default off; `web on --once|--session`
- **Schedule parse**: named cadences + intervals
- **Persistent DAG** + **blackboard**
- **Planner** kind-aware templates; **Herdr** `herdr run-ready` finite jobs
- CLI: `status | start|restart|shutdown | desk … | web | seat (deprecated) | cos | herdr | dag | bb | serve | observer`
- HTTP: `/health`, `/api/status`, `/api/desk/*`, `/observer/`, `/api/seat` (deprecated alias), …
- **Observer panel** is the primary visual: standing rail, AGENT SPACE canvas, blackboard — **no query bar**
- Omarchy **Panel.qml** remains a native twin / optional client (may still show a query box for guest; prefer observer)

State dir: `~/.local/state/okstratr/` (tests: `OKSTRATR_STATE_DIR`).

## Non-goals (near-term)

- Not a knowledge graph or wiki (that is okbay)
- Not an Atlas / CE overlay (do not copy okbay Atlas/static)
- Not a replacement for Herdr — okstratr *pairs* with it
- Not live Herdr focus sync (stub `focus_desk` only)
- Not a second chat surface in the observer
- Not AG-UI / A2A / model ladder
- Not inside `benjsmith/okbay`

## Layout

```
manifest.json          Omarchy plugin contract (id benjsmith.okstratr)
BarWidget.qml          optional bar chip (thin client)
Panel.qml              optional Omarchy native twin of observer (kept for guest)
DeskRail.qml           standing-desk rail (QML)
Service.qml            headless keep-alive
Model.js               status helpers
src/okstratr/          kernel, desks, roles, observer/, CLI, …
skills/okstratr/       in-harness skill
contrib/setup.sh       Omarchy visible installer
contrib/guest-apply-main.sh  Omarchy guest pull+restart
contrib/hypr-bindings.lua    optional Super+Shift+O
docs/ARCHITECTURE.md   package map + kept vs legacy surfaces
docs/ADR-001… / ADR-003…     CLI harness + skill/observer decisions
tests/
```

## Omarchy QML (optional)

**Bar chip:** left-click opens/focuses the panel (or observer when wired); right-click reserved. Menu: `contrib/okstratr-menu.jsonc`.

The QML **Panel** is an optional fullscreen FloatingWindow client of `:8767`. It is **not** the primary cross-platform console anymore — that is the HTML **observer panel**. QML is kept so the Omarchy guest does not break; see header comment in `Panel.qml`.

Panel open/close persists in `~/.local/state/okstratr/ui.json`. Theme colors from `qs.Commons` `Color` with Tokyo Night fallbacks.

## Local try

```sh
cd /path/to/okstratr
uv pip install -e '.[dev]'
okstratr start --yes
okstratr desk start work "Ship desk brain"
okstratr desk status
okstratr web on --once
OKSTRATR_HERDR_DRY_RUN=1 okstratr herdr run-ready --dry-run
okstratr dag ready
okstratr bb head 5
pytest
```

Deprecated: `okstratr seat "…"` → use `desk start auto …`.

## Install on Omarchy

```sh
# omarchy plugin add https://github.com/benjsmith/okstratr.git --enable
git clone https://github.com/benjsmith/okstratr
cd okstratr && bash contrib/setup.sh
# Guest refresh from Mac: ssh … 'bash -s' < contrib/guest-apply-main.sh
```

Prefer the **observer panel** even on Omarchy when you want the shared console.

## Layout e2e gate

Ben: do not treat okstratr+Herdr workspace layout as done without a **VM screenshot** of Herdr showing **RUNNING AGENTS** (separate VM executor).

## License

MIT
