# Okstratr architecture

## Intent

Okstratr is the **orchestrator / desk brain** for Omarchy. It owns:

- **DAG** — durable tasks and dependencies for seated work (persisted under `~/.local/state/okstratr/dag.json`)
- **Chief of staff (CoS)** — heuristic prioritize / break down / escalate into DAG nodes (v1, no LLM)
- **Schedule** — when work runs; windows on the calendar of attention
- **Blackboard** — shared claims / notes / decisions / evidence (append JSONL + index)
- **Herdr bridge** — seat ready DAG nodes into live agent terminals via Herdr’s runtime API (**finite jobs only**)

It does **not** own the knowledge graph, Atlas, or Nautilus reveal — those stay in **okbay**.

## Role split

| Layer | Owner | What it does |
|-------|--------|----------------|
| **Runtime / multiplexer** | **Herdr** | Panes, workspaces, agent lifecycle (`working` / `blocked` / `idle`), socket/CLI to start / prompt / wait / stop agents |
| **Plan + memory of the desk** | **okstratr** | Durable product DAG across seats, CoS breakdown, human blackboard, schedule/attention windows, Omarchy bar/panel desk UI |

**okstratr** owns the plan + memory; **Herdr** owns live agent terminals. Neither replaces the other.

## CoS v1 flow

1. **Seat** an objective (`okstratr seat "…"`, panel, or `POST /api/seat`).
2. **CoS break** (heuristic, no LLM) expands the objective into stable child nodes under `root`:
   - `cos-clarify` → `cos-gather` → `cos-execute` → `cos-verify`
   - Each has `depends_on` forming a chain; first depends on `root`.
   - Idempotent: re-running refreshes titles/objectives, does not duplicate ids.
   - Posts a blackboard `decision` summarizing the plan.
   - Marks `root` **done** so the first child becomes **ready**.
3. Trigger:
   - `okstratr cos break`
   - `okstratr seat "…" --cos`
   - **Auto** on seat when the DAG only has `root` (or is empty)
   - `POST /api/cos/break` or `POST /api/seat` with `"cos": true` (default auto when only root)

## Herdr seat (finite jobs)

**Ben credit rule:** never leave Grok/Herdr agents running after a node finishes. Always stop/release.

1. `okstratr herdr run-ready [--limit N] [--dry-run]` (or `POST /api/herdr/run-ready`)
2. For each **ready** non-root node (up to `limit`):
   - Mark DAG node `running`
   - **Dry-run** (`--dry-run` or `OKSTRATR_HERDR_DRY_RUN=1`): record would-exec, mark `done`, post blackboard — **no real API calls**
   - **Live:** `herdr agent start <id> --kind grok -- <prompt>` → `prompt` → `wait` (bounded by `OKSTRATR_HERDR_TIMEOUT` / `OKSTRATR_HERDR_WAIT_TIMEOUT`, default 120s) → **always** `agent stop`
   - Update DAG (`done` / `failed`) + blackboard evidence/notes
3. Existing `okstratr herdr [objective]` launch/focus helpers remain for opening the Herdr UI.

Tests must use `OKSTRATR_STATE_DIR` temp dirs and `OKSTRATR_HERDR_DRY_RUN=1`.

## Herdr interaction design (v1)

1. **Seat** an objective in okstratr (panel / CLI / HTTP `POST /api/seat`).
2. **CoS** breaks the objective into DAG nodes (see above).
3. For each **ready** node: Herdr seat via `run-ready` (start / prompt / wait / **stop**).
4. On done or failed, DAG + blackboard advance; dependents may become ready.
5. **Human** reviews blackboard claims; approve → mark follow-ups or re-seat.
6. **Never leave agents running after finite tasks.**

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
- `POST /api/seat` — body `{"objective": "...", "herdr": false, "reset": false, "cos": null|true|false}`
- `POST /api/cos/break` — body `{"objective": "..."}` (optional; uses seated objective)
- `POST /api/herdr/run-ready` — body `{"limit": 1, "dry_run": true|false|null}`
- `GET /api/dag` — full DAG summary (nodes, ready, topo, blocked_reasons)
- `POST /api/dag/nodes` — create node `{id, title, depends_on, kind, objective, notes}`
- `POST /api/dag/nodes/{id}/state` — `{state, notes?}` (`done` / `failed` / …)
- `GET /api/blackboard` — summary + items (`?n=&kind=&q=`)
- `POST /api/blackboard` — `{text, author, kind, tags, provenance, node_id}`

## CLI

```
okstratr status | seat [--reset] [--cos] [--herdr] | serve
okstratr cos break [objective] | cos [objective]   # break vs advise
okstratr herdr run-ready [--limit N] [--dry-run]
okstratr herdr [objective]                         # launch/focus UI
okstratr dag add|list|ready|done|fail|reset|state
okstratr bb post|head|search|clear
```

## Env

| Var | Role |
|-----|------|
| `OKSTRATR_STATE_DIR` | Override state dir (tests) |
| `OKSTRATR_HERDR_DRY_RUN` | `1`/`true` → no real Herdr/Grok calls |
| `OKSTRATR_HERDR_TIMEOUT` / `OKSTRATR_HERDR_WAIT_TIMEOUT` | Bounded wait seconds (default 120) |
| `OKSTRATR_HERDR_KIND` | Agent kind for start (default `grok`) |

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
  cos.py          CoS heuristic breakdown + advise
  blackboard.py   persistent JSONL blackboard
  herdr.py        launch/focus + run_ready finite seats
  server.py       HTTP on 8767
  cli.py          status | seat | cos | herdr | dag | bb | serve
  status.py       status.json publisher
```

## Separation from okbay

- Separate git repo / plugin id: `benjsmith.okstratr`
- No copy of okbay Atlas/static
- No nest under `/workspace/okbay`
- Optional later IPC (HTTP or status files), not a shared process

## Layout e2e gate (Ben)

Do **not** call the three-workspace layout complete until there is a **VM screenshot** of native **Herdr** showing **RUNNING AGENTS**. A separate Omarchy-VM executor owns agents + that capture; okstratr only seats the objective and launches/focuses Herdr.
