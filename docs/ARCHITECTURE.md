# Okstratr architecture

## Intent

Okstratr is the **orchestrator / desk brain** for Omarchy. It owns:

- **DAG** — durable tasks and dependencies for seated work (persisted under `~/.local/state/okstratr/dag.json`)
- **Chief of staff (CoS)** — prioritize, break down, escalate (stub today; expands DAG later)
- **Schedule** — when work runs; windows on the calendar of attention
- **Blackboard** — shared claims / notes / decisions / evidence (append JSONL + index)
- **Herdr bridge** — seat objectives into live agent terminals via Herdr’s runtime API

It does **not** own the knowledge graph, Atlas, or Nautilus reveal — those stay in **okbay**.

## Does Herdr already do orchestration like okstratr?

**Short answer: no — not the desk-brain kind.**

| Layer | Owner | What it does |
|-------|--------|----------------|
| **Runtime / multiplexer** | **Herdr** | Panes, workspaces, agent lifecycle (`working` / `blocked` / `idle`), socket API to start / prompt / wait agents; agents can fan out to other agents in terminals |
| **Plan + memory of the desk** | **okstratr** | Durable product DAG across seats, CoS prioritization, human blackboard of claims/decisions tied to okbay knowledge, schedule/attention windows, Omarchy bar/panel desk UI |

Herdr does **runtime orchestration**: who is running, prompt them, wait until blocked or idle. It does **not** own:

- a durable product DAG that survives seats and sessions
- CoS prioritization / breakdown of objectives into that DAG
- a human blackboard of claims and decisions linked to okbay knowledge
- schedule / attention windows
- Omarchy bar / panel desk chrome

**Interaction (intended):** okstratr seats an objective → expands a DAG → for ready nodes calls `herdr agent start` / `prompt` → watches agent state via Herdr → posts outcomes to the blackboard → advances the DAG.

## Herdr interaction design (v1)

1. **Seat** an objective in okstratr (panel / CLI / HTTP `POST /api/seat`).
2. **CoS** (later) breaks the objective into DAG nodes; today `seat` creates/updates `root` and CoS returns a stub plan.
3. For each **ready** node: `herdr agent start <id> --kind grok -- <prompt from node>`.
4. **Poll / subscribe** agent state via Herdr; on done or blocked, update the DAG node and post to the blackboard (`claim` / `evidence` / `decision`, optionally with `node_id`).
5. **Human** reviews blackboard claims; approve → mark DAG node `done` / spawn follow-ups.
6. **Never leave agents running after finite tasks** (Ben credit rule) — stop or idle agents when the node finishes.

okstratr owns the plan + memory; Herdr owns the live agent terminals. Neither replaces the other.

## Ports

| Service | Port | Notes |
|---------|------|-------|
| okbay | **8766** | Knowledge / Atlas HTTP |
| okstratr | **8767** | Orchestrator HTTP |

Never bind okstratr to 8765 or 8766.

## Persistence

State directory: `~/.local/state/okstratr/` (override with `OKSTRATR_STATE_DIR` for tests).

| File | Role |
|------|------|
| `status.json` | Snapshot for QML `FileView` (objective, dag, blackboard summaries) |
| `dag.json` | Durable DAG nodes |
| `blackboard.jsonl` | Append-only blackboard entries |
| `blackboard.index.json` | Optional counts / by_kind index |

`seat` updates/creates the `root` node and does **not** wipe the DAG unless `seat --reset` / `{"reset": true}`.

## HTTP

- `GET /health` — liveness
- `GET /api/status` — seated objective + richer `dag` + `blackboard`
- `POST /api/seat` — body `{"objective": "...", "herdr": false, "reset": false}`
- `GET /api/dag` — full DAG summary (nodes, ready, topo, blocked_reasons)
- `POST /api/dag/nodes` — create node `{id, title, depends_on, kind, objective, notes}`
- `POST /api/dag/nodes/{id}/state` — `{state, notes?}` (`done` / `failed` / …)
- `GET /api/blackboard` — summary + items (`?n=&kind=&q=`)
- `POST /api/blackboard` — `{text, author, kind, tags, provenance, node_id}`

## CLI

```
okstratr status | seat [--reset] [--herdr] | serve | herdr | cos
okstratr dag add|list|ready|done|fail|reset|state
okstratr bb post|head|search|clear
```

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
  paths.py        OKSTRATR_STATE_DIR / ~/.local/state/okstratr
  dag.py          persistent task graph
  schedule.py     timing / windows stubs
  cos.py          chief-of-staff stub
  blackboard.py   persistent JSONL blackboard
  herdr.py        launch/focus Herdr with objective
  server.py       HTTP on 8767
  cli.py          status | seat | dag | bb | serve | herdr
  status.py       status.json publisher
```

## Separation from okbay

- Separate git repo / plugin id: `benjsmith.okstratr`
- No copy of okbay Atlas/static
- No nest under `/workspace/okbay`
- Optional later IPC (HTTP or status files), not a shared process

## Layout e2e gate (Ben)

Do **not** call the three-workspace layout complete until there is a **VM screenshot** of native **Herdr** showing **RUNNING AGENTS**. A separate Omarchy-VM executor owns agents + that capture; okstratr only seats the objective and launches/focuses Herdr.
