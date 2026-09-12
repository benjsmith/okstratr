# Okstratr

> **Under construction. Not ready to use.**
>
> Early scaffold for a separate Omarchy plugin. Do not install yet.
> Paths, APIs, and QML will change without notice.

**Desk-brain orchestrator** for [Omarchy](https://omarchy.org/): durable DAG of work, chief-of-staff, scheduling, and a shared blackboard — paired with native **Herdr** as the agent runtime / session UI.

Plugin id: `benjsmith.okstratr`

HTTP: **127.0.0.1:8767** (okbay keeps **8766**)

## Relationship

| Piece | Role |
|-------|------|
| **okbay** (`benjsmith.okbay`) | Knowledge graph + Atlas + Nautilus reveal + work-coverage ingest |
| **okstratr** (this repo) | Orchestrator / desk brain — kernel, desks, durable DAG, CoS, schedule, blackboard, bar/panel |
| **Herdr** (native Omarchy) | Agent **runtime / multiplexer** — panes, workspaces, agent lifecycle, socket API |

Work-coverage default lives in **okbay** (magical all-`~/Work`). **Biocure** is the current demo workspace in use (not an opt-in). Optional = create more focused workspaces via okbay split (subset of Work folders → new wiki; those folders leave default coverage). okstratr desks bind the active okbay workspace / thread ids — they do not ingest.

### Does Herdr already do orchestration like okstratr?

**No.** Herdr does **runtime** orchestration (who is running, prompt them, wait for blocked/idle; agents can fan out in terminals). It does **not** own the desk-brain: durable product DAG across desks, CoS prioritization, human blackboard of claims/decisions tied to okbay knowledge, schedule/attention windows, or Omarchy bar/panel desk UI.

**okstratr** owns the **plan + memory of the desk**; **Herdr** owns **live agent terminals**. Flow: desk start → kernel hires CoS + roles → CoS expand DAG → for ready nodes `herdr run-ready` (start/prompt/wait/**stop**) → post outcomes to blackboard → advance DAG.

**Finite-job rule:** never leave Grok/Herdr agents running after a node — always stop/release.

See [docs/DESK-KERNEL.md](docs/DESK-KERNEL.md) for the hiring-manager / desk / Herdr design, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for package map + APIs.

> **Switchbay release pending** — deep parity check against Switchbay once that tree is available.

Either plugin can be useful alone. They share a future multi-workspace layout, not a monorepo.

### Future workspaces (vision)

1. **Fullscreen Atlas** — okbay knowledge plane
2. **Linked Nautilus** — file reveal next to Atlas
3. **okstratr + Herdr side by side** — orchestrator panel / bar + agent session

## What works today

- Omarchy kinds: `service`, `bar-widget`, `panel` (no Atlas overlay)
- **Desk lifecycle**: `desk start|stop|dismiss|status|schedule` (states `working|quiet|dismissed`)
- **Kernel**: live **effort-bandit** hire / ensure_cos / retire_worker; persist org + effort + model hints (no real LLM)
- **Web egress gate**: default off; `web on --once|--session`; status chip Web: Off|Once|Session
- **Schedule parse**: named cadences + intervals (`90`, `1h30m`, `2 wks`, …)
- **Persistent DAG** (`dag.json` + per-desk copies): add / ready / done / fail / reset / topo + cycle detect
- **Persistent blackboard** (`blackboard.jsonl`): post / head / search / clear (archive)
- **Planner** kind-aware templates: work/auto → investigator/synthesizer/verifier
- **Herdr** `herdr run-ready`: finite jobs, labels `okstratr-{desk}-{role}-{node}`, dry-run via `OKSTRATR_HERDR_DRY_RUN` / `--dry-run`
- CLI: `status | desk (start|stop|dismiss|status|schedule|hire|effort|retire|focus) | web | seat(deprecated) | cos | herdr | dag | bb | serve`
- HTTP: `/health`, `/api/status`, `/api/desk/*` (incl. hire/effort/retire/focus), `/api/web`, `/api/seat` (alias), `/api/cos/break`, `/api/herdr/launch`, `/api/herdr/run-ready`, `/api/dag`, `/api/blackboard`
- Bar chip shows desk kind · state + DAG count + **Web:** chip; **panel is a fullscreen desk UI** (FloatingWindow toplevel — not Overlay; stays under lock/screensaver) with standing-desk rail, DAG/blackboard, Omarchy chip actions (Open in Herdr / Refresh / web), POST /api/herdr/launch, no text input

State dir: `~/.local/state/okstratr/` (tests: `OKSTRATR_STATE_DIR`).

## Non-goals (near-term)

- Not a knowledge graph or wiki (that is okbay)
- Not an Atlas / CE overlay (do not copy okbay Atlas/static)
- Not a replacement for Herdr — okstratr *pairs* with it
- Not live Herdr focus sync (stub `focus_desk` only)
- Not real Grok/Herdr API calls from the kernel (finite dry-run)
- Not real network inside the web gate (approve → caller may search)
- Not AG-UI / A2A / model ladder
- Not inside `benjsmith/okbay`

## Layout

```
manifest.json          Omarchy plugin contract (id benjsmith.okstratr)
BarWidget.qml          bar pulse — desk objective
Panel.qml              fullscreen FloatingWindow desk UI + Herdr launch
Service.qml            headless keep-alive
Model.js               status helpers
src/okstratr/          kernel, desks, roles, schedule_parse, DAG, CoS, …
contrib/setup.sh       visible installer
contrib/hypr-bindings.lua  optional Super+Shift+O summon
docs/DESK-KERNEL.md    kernel / desk / Herdr design (authoritative)
docs/ARCHITECTURE.md   package map + APIs
tests/                 schedule parse, desk lifecycle, DAG, CoS, Herdr dry-run
```

## Panel UI

The Omarchy **panel** (`Panel.qml`) is a **fullscreen desk UI**: a Quickshell `FloatingWindow` toplevel (native window chrome / maximize), not a tiny corner Overlay layershell. Super+Shift+O (see `contrib/hypr-bindings.lua`) or the bar chip summons it. Left rail lists standing desks; main shows objective, DAG, blackboard head, and Open in Herdr. Free-text input stays in Herdr.

## Local try

```sh
cd /path/to/okstratr
PYTHONPATH=src python3 -m okstratr status

# Start a desk (kind optional; kernel may pick)
PYTHONPATH=src python3 -m okstratr desk start work "Ship desk brain"
PYTHONPATH=src python3 -m okstratr desk hire investigator
PYTHONPATH=src python3 -m okstratr desk effort 0.7
PYTHONPATH=src python3 -m okstratr desk retire investigator
PYTHONPATH=src python3 -m okstratr desk status
PYTHONPATH=src python3 -m okstratr web status
PYTHONPATH=src python3 -m okstratr web on --once
PYTHONPATH=src python3 -m okstratr web off
PYTHONPATH=src python3 -m okstratr desk schedule 1h30m
PYTHONPATH=src python3 -m okstratr desk stop      # quiet; DAG kept
PYTHONPATH=src python3 -m okstratr desk dismiss   # disband; DAG archived

# Deprecated alias (warns → desk start auto …)
PYTHONPATH=src python3 -m okstratr seat "Ship desk brain"

# Finite Herdr seat (dry-run: no real Herdr/Grok calls)
OKSTRATR_HERDR_DRY_RUN=1 PYTHONPATH=src python3 -m okstratr herdr run-ready --dry-run

PYTHONPATH=src python3 -m okstratr dag ready
PYTHONPATH=src python3 -m okstratr bb head 5
PYTHONPATH=src python3 -m okstratr serve   # http://127.0.0.1:8767/health
pytest
```

## Install on Omarchy

**Not yet.** When ready:

```sh
# omarchy plugin add https://github.com/benjsmith/okstratr.git --enable
# git clone https://github.com/benjsmith/okstratr
# cd okstratr && bash contrib/setup.sh
```

## Layout e2e gate

Ben: do not treat okstratr+Herdr workspace layout as done without a **VM screenshot** of Herdr showing **RUNNING AGENTS** (separate VM executor).

## License

MIT
