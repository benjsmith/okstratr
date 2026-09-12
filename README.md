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

**okstratr** owns the **plan + memory of the desk**; **Herdr** owns **live agent terminals**. Flow: seat objective → expand DAG → for ready nodes `herdr agent start/prompt` → watch state → post outcomes to blackboard → advance DAG.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full **Herdr interaction design (v1)** (seat → CoS → start agents → poll → human review → stop after finite tasks / Ben credit rule).

Either plugin can be useful alone. They share a future multi-workspace layout, not a monorepo.

### Future workspaces (vision)

1. **Fullscreen Atlas** — okbay knowledge plane
2. **Linked Nautilus** — file reveal next to Atlas
3. **okstratr + Herdr side by side** — orchestrator panel / bar + agent session

## What works today

- Omarchy kinds: `service`, `bar-widget`, `panel` (no Atlas overlay)
- **Persistent DAG** (`dag.json`): add / ready / done / fail / reset / topo + cycle detect
- **Persistent blackboard** (`blackboard.jsonl`): post / head / search / clear (archive)
- CLI: `status | seat | dag | bb | serve | herdr | cos`
- HTTP: `/health`, `/api/status`, `/api/seat`, `/api/dag`, `/api/dag/nodes`, `/api/dag/nodes/{id}/state`, `/api/blackboard`
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
docs/ARCHITECTURE.md   Herdr interaction + three-workspace vision
tests/                 DAG + blackboard persistence tests
```

## Local try

```sh
cd /path/to/okstratr
PYTHONPATH=src python3 -m okstratr status
PYTHONPATH=src python3 -m okstratr seat "Ship desk brain"
PYTHONPATH=src python3 -m okstratr dag add research "Gather constraints" --depends root
PYTHONPATH=src python3 -m okstratr dag ready
PYTHONPATH=src python3 -m okstratr bb post "root looks good" --kind claim --node-id root
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
