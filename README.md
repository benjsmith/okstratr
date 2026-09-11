# Okstratr

> **Under construction. Not ready to use.**
>
> Early scaffold for a separate Omarchy plugin. Do not install yet.
> Paths, APIs, and QML will change without notice.

**Desk-brain orchestrator** for [Omarchy](https://omarchy.org/): DAG of work, chief-of-staff, scheduling, and a shared blackboard — paired with native **Herdr** as the agent session UI.

Plugin id: `benjsmith.okstratr`

HTTP: **127.0.0.1:8767** (okbay keeps **8766**)

## Relationship

| Piece | Role |
|-------|------|
| **okbay** (`benjsmith.okbay`) | Knowledge graph + Atlas + Nautilus reveal |
| **okstratr** (this repo) | Orchestrator / desk brain — DAG, CoS, schedule, blackboard |
| **Herdr** (native Omarchy) | Agent session UI — okstratr seats an objective and launches/focuses Herdr |

Either plugin can be useful alone. They share a future multi-workspace layout, not a monorepo.

### Future workspaces (vision)

1. **Fullscreen Atlas** — okbay knowledge plane
2. **Linked Nautilus** — file reveal next to Atlas
3. **okstratr + Herdr side by side** — orchestrator panel / bar + agent session

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What v0 stubs

- Omarchy kinds: `service`, `bar-widget`, `panel` (no Atlas overlay)
- Python package: `dag`, `schedule`, `cos` (chief of staff), `blackboard`, `herdr`
- Tiny HTTP: `/health`, `/api/status`, `/api/seat`
- Bar chip shows seated objective; panel links to Herdr

## Non-goals (v0 / near-term)

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
docs/ARCHITECTURE.md   three-workspace vision
```

## Local try

```sh
cd /path/to/okstratr
PYTHONPATH=src python3 -m okstratr status
PYTHONPATH=src python3 -m okstratr serve   # http://127.0.0.1:8767/health
```

## Install on Omarchy

**Not yet.** When ready:

```sh
# omarchy plugin add https://github.com/benjsmith/okstratr.git --enable
# git clone https://github.com/benjsmith/okstratr
# cd okstratr && bash contrib/setup.sh
```

## Push later

If this tree was created without a GitHub remote:

```sh
cd okstratr
git init
git add .
git commit -m "scaffold okstratr Omarchy plugin"
gh repo create benjsmith/okstratr --private --source=. --remote=origin --push
```

## Layout e2e gate

Ben: do not treat okstratr+Herdr workspace layout as done without a **VM screenshot** of Herdr showing **RUNNING AGENTS** (separate VM executor).

## License

MIT
