# Okstratr architecture

## Intent

Okstratr is the **orchestrator / desk brain** for Omarchy. It owns:

- **DAG** — tasks and dependencies for seated work
- **Chief of staff (CoS)** — prioritize, break down, escalate
- **Schedule** — when work runs; windows on the calendar of attention
- **Blackboard** — shared scratch for agents and the human
- **Herdr bridge** — launch/focus native Herdr with the seated objective text

It does **not** own the knowledge graph, Atlas, or Nautilus reveal — those stay in **okbay**.

## Ports

| Service | Port | Notes |
|---------|------|-------|
| okbay | **8766** | Knowledge / Atlas HTTP |
| okstratr | **8767** | Orchestrator HTTP stub |

Never bind okstratr to 8765 or 8766.

## HTTP (v0 stub)

- `GET /health` — liveness
- `GET /api/status` — seated objective, DAG summary, blackboard head
- `POST /api/seat` — body `{"objective": "..."}` — seat work and optionally hand off to Herdr

Status is also mirrored to `~/.local/state/okstratr/status.json` for QML `FileView`.

## Plugin kinds

- `service` — keep-loaded headless
- `bar-widget` — chip: seated objective / SETUP / STALE
- `panel` — desk brain UI + “Open in Herdr”

No overlay kind in v0 (okbay owns Atlas overlay).

## Three-workspace vision

Future Omarchy workspaces (separate from plugin install):

```
┌─────────────────────────────┐  Workspace A
│     fullscreen Atlas        │  okbay knowledge plane
└─────────────────────────────┘

┌──────────────┬──────────────┐  Workspace B
│ Atlas / graph│   Nautilus   │  linked reveal
└──────────────┴──────────────┘

┌──────────────┬──────────────┐  Workspace C
│   okstratr   │    Herdr     │  orchestrator + agent session
│   panel/bar  │  session UI  │
└──────────────┴──────────────┘
```

Either okbay or okstratr should remain useful alone; side-by-side is the composed desk.

## Package map

```
src/okstratr/
  dag.py          task graph stubs
  schedule.py     timing / windows stubs
  cos.py          chief-of-staff stub
  blackboard.py   shared notes stub
  herdr.py        launch/focus Herdr with objective
  server.py       HTTP on 8767
  cli.py          status | seat | serve | herdr
```

## Separation from okbay

- Separate git repo / plugin id: `benjsmith.okstratr`
- No copy of okbay Atlas/static
- No nest under `/workspace/okbay`
- Optional later IPC (HTTP or status files), not a shared process

## Layout e2e gate (Ben)

Do **not** call the three-workspace layout complete until there is a **VM screenshot** of native **Herdr** showing **RUNNING AGENTS**. A separate Omarchy-VM executor owns agents + that capture; okstratr only seats the objective and launches/focuses Herdr.

