# Okstratr architecture

> Desk / kernel design authority: **[DESK-KERNEL.md](DESK-KERNEL.md)**.
> Switchbay release pending for deep parity check.

## Intent

Okstratr is the **orchestrator / desk brain** for Omarchy. It owns:

- **Kernel** — hiring manager stub (kind heuristic, always hire CoS; no live LLM)
- **Desks** — standing orgs with states `working | quiet | dismissed`
- **DAG** — durable tasks and dependencies per desk (global `dag.json` + per-desk copies)
- **Chief of staff (CoS)** — only user interface into a desk; heuristic prioritize / break down
- **Schedule** — parse named/interval cadences; attach to desk (dialog UI later)
- **Blackboard** — shared claims / notes / decisions / evidence (append JSONL + index)
- **Herdr bridge** — seat ready DAG nodes into live agent terminals via Herdr’s runtime API (**finite jobs only**)

It does **not** own the knowledge graph, Atlas, or Nautilus reveal — those stay in **okbay**.

## Role split

| Layer | Owner | What it does |
|-------|--------|----------------|
| **Runtime / multiplexer** | **Herdr** | Panes, workspaces, agent lifecycle (`working` / `blocked` / `idle`), socket/CLI to start / prompt / wait / stop agents |
| **Plan + memory of the desk** | **okstratr** | Kernel + desks, durable product DAG, CoS, human blackboard, schedule, Omarchy bar/panel desk UI |

**okstratr** owns the plan + memory; **Herdr** owns live agent terminals. Neither replaces the other.

Text input lives in **Herdr**; okstratr UI is desk list + DAG/blackboard controls (**no free text**). See [DESK-KERNEL.md](DESK-KERNEL.md#herdr-interaction).

## Desk verbs (CLI)

```
desk start [kind] [objective…]   # kinds: curate|work|code|deck|auto (defaults, not closed)
desk stop                        # quiet; keep last live DAG; CoS ready
desk dismiss                     # disband standing org; archive/clear DAG
desk status
desk schedule <spec…>            # hourly|daily|… | 90 | 1h30m | 2 wks | …
```

`seat` is a **deprecated** thin alias for one release: warns → `desk start auto …`.

## CoS v1 flow

1. **Desk start** an objective (`okstratr desk start …`, panel, or `POST /api/desk/start`).
2. **Kernel** chooses kind (heuristic / explicit) and hires CoS + default roles.
3. **CoS break** (heuristic, no LLM) expands the objective into stable child nodes under `root`:
   - `cos-clarify` → `cos-gather` → `cos-execute` → `cos-verify`
   - Idempotent; posts a blackboard `decision`; marks `root` **done**.
4. Trigger:
   - `okstratr cos break`
   - `okstratr desk start …` (default; `--no-cos` to skip)
   - `POST /api/desk/start` / deprecated `POST /api/seat`

## Herdr finite jobs

**Ben credit rule:** never leave Grok/Herdr agents running after a node finishes. Always stop/release.

1. `okstratr herdr run-ready [--limit N] [--dry-run]` (or `POST /api/herdr/run-ready`)
2. For each **ready** non-root node (up to `limit`):
   - Mark DAG node `running`
   - **Dry-run** (`--dry-run` or `OKSTRATR_HERDR_DRY_RUN=1`): record would-exec, mark `done`, post blackboard — **no real API calls**
   - **Live:** `herdr agent start` → `prompt` → `wait` (bounded) → **always** `agent stop`
   - Update DAG + blackboard
3. Agents in Herdr are labeled with **desk id + thread id** (stub labels today).

Tests must use `OKSTRATR_STATE_DIR` temp dirs and `OKSTRATR_HERDR_DRY_RUN=1`.

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
| `status.json` | Snapshot for QML `FileView` (objective, desk, dag, blackboard) |
| `desks.json` | Desk registry (active_id, standing orgs) |
| `desks/<id>/dag.json` | Per-desk live DAG (kept on stop) |
| `desks/<id>/archive/` | Archived DAGs on dismiss |
| `dag.json` | Active desk’s DAG mirror for CLI/panel |
| `blackboard.jsonl` | Append-only blackboard entries |
| `blackboard.index.json` | Optional counts / by_kind index |

- **stop**: keep last live DAG visible.
- **dismiss**: archive DAG, tear down standing org, clear active global DAG.

## HTTP

- `GET /health` — liveness
- `GET /api/status` — objective + desk brief + dag + blackboard
- `POST /api/desk/start` — `{objective, kind?, reset?, cos?, effort?, herdr?}`
- `POST /api/desk/stop` — `{desk_id?}`
- `POST /api/desk/dismiss` — `{desk_id?}`
- `GET|POST /api/desk/status`
- `POST /api/desk/schedule` — `{spec|schedule|args, desk_id?}`
- `POST /api/seat` — **deprecated** alias → desk start auto
- `POST /api/cos/break` — `{objective?}`
- `POST /api/herdr/run-ready` — `{limit?, dry_run?}`
- `GET /api/dag` — full DAG summary
- `POST /api/dag/nodes` — create node
- `POST /api/dag/nodes/{id}/state` — set state
- `GET /api/blackboard` — summary + items
- `POST /api/blackboard` — post entry

## CLI

```
okstratr status | desk start|stop|dismiss|status|schedule | serve
okstratr seat …                 # deprecated → desk start auto
okstratr cos break [objective] | cos [objective]
okstratr herdr run-ready [--limit N] [--dry-run]
okstratr herdr [objective]
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
- `bar-widget` — chip: desk objective / SETUP / STALE
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
  paths.py           OKSTRATR_STATE_DIR / ~/.local/state/okstratr
  kernel.py          stub hiring manager (kind heuristic, ensure CoS)
  roles.py           role catalog + independence notes
  desks.py           registry: start/stop/dismiss/status/schedule
  schedule_parse.py  named + interval schedule parser
  schedule.py        attention window stubs
  dag.py             persistent task graph
  cos.py             CoS heuristic breakdown + advise
  blackboard.py      persistent JSONL blackboard
  herdr.py           launch/focus + run_ready finite seats
  server.py          HTTP on 8767
  cli.py             status | desk | seat(deprecated) | …
  status.py          status.json publisher
```

## Separation from okbay

- Separate git repo / plugin id: `benjsmith.okstratr`
- No copy of okbay Atlas/static
- No nest under `/workspace/okbay`
- Optional later IPC (HTTP or status files), not a shared process

## Layout e2e gate (Ben)

Do **not** call the three-workspace layout complete until there is a **VM screenshot** of native **Herdr** showing **RUNNING AGENTS**. A separate Omarchy-VM executor owns agents + that capture; okstratr only starts desks and launches/focuses Herdr.
