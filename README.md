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
| **okbay** (`benjsmith.okbay`) | Knowledge graph + Atlas + Nautilus reveal |
| **okstratr** (this repo) | Orchestrator / desk brain — durable DAG, CoS, schedule, blackboard, bar/panel |
| **Herdr** (native Omarchy) | Agent **runtime / multiplexer** — panes, workspaces, agent lifecycle, socket API |

### Does Herdr already do orchestration like okstratr?

**No.** Herdr does **runtime** orchestration (who is running, prompt them, wait for blocked/idle; agents can fan out in terminals). It does **not** own the desk-brain: durable product DAG across seats, CoS prioritization, human blackboard of claims/decisions tied to okbay knowledge, schedule/attention windows, or Omarchy bar/panel desk UI.

**okstratr** owns the **plan + memory of the desk**; **Herdr** owns **live agent terminals**. Flow: seat objective → CoS expand DAG → for ready nodes `herdr run-ready` (start/prompt/wait/**stop**) → post outcomes to blackboard → advance DAG.

**Finite-job rule:** never leave Grok/Herdr agents running after a node — always stop/release.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for CoS v1 + Herdr seat design.

Either plugin can be useful alone. They share a future multi-workspace layout, not a monorepo.

### Future workspaces (vision)

1. **Fullscreen Atlas** — okbay knowledge plane
2. **Linked Nautilus** — file reveal next to Atlas
3. **okstratr + Herdr side by side** — orchestrator panel / bar + agent session

## What works today

- Omarchy kinds: `service`, `bar-widget`, `panel` (no Atlas overlay)
- **Persistent DAG** (`dag.json`): add / ready / done / fail / reset / topo + cycle detect
- **Persistent blackboard** (`blackboard.jsonl`): post / head / search / clear (archive)
- **CoS v1** heuristic breakdown → stable `cos-*` child nodes (idempotent); `cos break` / `seat --cos` / auto when only root
- **Herdr seat** `herdr run-ready`: finite jobs, dry-run via `OKSTRATR_HERDR_DRY_RUN` / `--dry-run`
- CLI: `status | seat | cos | herdr | dag | bb | serve`
- HTTP: `/health`, `/api/status`, `/api/seat`, `/api/cos/break`, `/api/herdr/run-ready`, `/api/dag`, `/api/blackboard`
- Bar chip shows seated objective; panel links to Herdr

State dir: `~/.local/state/okstratr/` (tests: `OKSTRATR_STATE_DIR`).

## Non-goals (near-term)

- Not a knowledge graph or wiki (that is okbay)
- Not an Atlas / CE overlay (do not copy okbay Atlas/static)
- Not a replacement for Herdr — okstratr *pairs* with it
- Not AG-UI / A2A / model ladder
- Not inside `benjsmith/okbay`

## Layout

```
manifest.json          Omarchy plugin contract (id benjsmith.okstratr)
BarWidget.qml          bar pulse — seated objective
Panel.qml              desk brain panel + Herdr launch
Service.qml            headless keep-alive
Model.js               status helpers
src/okstratr/          DAG, schedule, CoS, blackboard, herdr, CLI, HTTP
contrib/setup.sh       visible installer
contrib/hypr-bindings.lua  optional Super+Shift+O summon
docs/ARCHITECTURE.md   CoS v1 + Herdr seat + three-workspace vision
tests/                 DAG, blackboard, CoS, Herdr dry-run tests
```

## Local try

```sh
cd /path/to/okstratr
PYTHONPATH=src python3 -m okstratr status

# Seat + CoS breakdown (auto when DAG only has root; or pass --cos)
PYTHONPATH=src python3 -m okstratr seat "Ship desk brain" --cos
# → root done; cos-clarify ready; blackboard has CoS plan

# Finite Herdr seat (dry-run: no real Herdr/Grok calls)
OKSTRATR_HERDR_DRY_RUN=1 PYTHONPATH=src python3 -m okstratr herdr run-ready --dry-run
# or: PYTHONPATH=src python3 -m okstratr herdr run-ready --limit 1 --dry-run

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
