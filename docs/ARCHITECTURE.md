# Okstratr architecture

> Desk / kernel design authority: **[DESK-KERNEL.md](DESK-KERNEL.md)**.
> Switchbay release pending for deep parity check.

## Intent

**Omarchy product = okbay (knowledge) + okstratr (orchestrator).**

Okstratr is the **orchestrator / desk brain**. It owns:

- **Kernel** — hiring manager with live effort-bandit (`hire` / `ensure_cos` / `retire_worker` / `set_effort`; no live LLM)
- **Web egress** — gate (`off`\|`once`\|`session`); all web search via `web_egress.authorize`
- **Desks** — standing orgs with states `working | quiet | dismissed` (persisted org + effort + model hints)
- **DAG** — durable tasks and dependencies per desk (global `dag.json` + per-desk copies)
- **Chief of staff (CoS)** — only user interface into a desk; kind-aware heuristic breakdown
- **Schedule** — parse named/interval cadences; attach to desk (dialog UI later)
- **Blackboard** — shared claims / notes / decisions / evidence (append JSONL + index)
- **Herdr bridge** — seat ready DAG nodes into live agent terminals via Herdr’s runtime API (**finite jobs only**); labels `o{desk8}{role6}{node6}`

It does **not** own the knowledge graph, Atlas, Nautilus reveal, or work-coverage
ingest — those stay in **okbay**. Desks bind the **active okbay workspace / thread ids**.

## Work-coverage (okbay; hooks only)

- **Default:** magical **all-`~/Work`** coverage (okbay ingest).
- **Biocure:** current **demo** workspace in use — **not** an opt-in.
- **Optional:** create additional **focused** workspaces.
- **Smooth path:** okbay **split** tool — subset of `~/Work` subfolders → new wiki;
  those folders join the new watch list and are excluded from default Work coverage.

`okstratr.okbay` is hooks/stubs only (`active_workspace`, `reviews_commit_path`,
`split_workspace`). Do not reimplement ingest here.

## Role split

| Layer | Owner | What it does |
|-------|--------|----------------|
| **Knowledge / coverage** | **okbay** | Graph, Atlas, ingest, reviews land path, workspaces |
| **Runtime / multiplexer** | **Herdr** | Panes, workspaces, agent lifecycle (`working` / `blocked` / `idle`), socket/CLI to start / prompt / wait / stop agents |
| **Plan + memory of the desk** | **okstratr** | Kernel + desks, durable product DAG, CoS, human blackboard, schedule, Omarchy bar/panel desk UI |

**okstratr** owns the plan + memory; **Herdr** owns live agent terminals. Neither replaces the other.

Text input lives in **Herdr**; okstratr UI is left-pane desk switch + DAG/blackboard (**no free text**). Close warns / suspends kernel. See [DESK-KERNEL.md](DESK-KERNEL.md#herdr-interaction).

## Desk verbs (CLI)

```
desk start [kind] [objective…]   # kinds: curate|work|code|deck|auto (defaults, not closed)
desk stop                        # quiet; keep last live DAG; CoS ready
desk dismiss                     # disband standing org; archive/clear DAG
desk status                      # includes bandit snapshot + web_egress + herdr_labels
desk schedule <spec…>            # hourly|daily|… | 90 | 1h30m | 2 wks | …
desk hire <role>                 # kernel.hire (bandit + cap + curate guards)
desk effort <0..1>               # set effort slider / utility weights
desk retire <node_id>            # retire short-lived DAG worker (+ bandit reward)
desk focus [desk_id]             # stub Herdr focus sync
okstratr web status|on|off       # web egress gate
```

`seat` is a **deprecated** thin alias for one release: warns → `desk start auto …`.

## CoS v1 flow

1. **Desk start** an objective (`okstratr desk start …`, panel, or `POST /api/desk/start`).
2. **Kernel** chooses kind (heuristic / explicit) and hires CoS + default roles (org persisted with model hints + effort).
3. **Planner / CoS break** (heuristic, no LLM) expands the objective into stable child nodes under `root`:
   - `work` / `auto` → Switchbay **investigator → synthesizer → verifier**
   - `curate` / `code` / `deck` keep kind-specific templates
   - no kind + no desk → historical `cos-clarify` chain
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
3. Agent ids: **`o{desk8}{role6}{node6}`** (capped 32). Every label includes **desk_id + thread_id**.
4. Status JSON includes `herdr_labels` and `focus_desk_id`. `focus_desk(desk_id)` is a stub for bidirectional sync.

Tests must use `OKSTRATR_STATE_DIR` temp dirs and `OKSTRATR_HERDR_DRY_RUN=1`.

**Close-warning copy** (QML later): see `herdr.CLOSE_WARNING` / `status.ui.close_warning`.

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
| `status.json` | Snapshot for QML `FileView` (desk kind/state, effort, herdr_labels, dag) |
| `ui.json` | Panel visibility `{ "panel_open": true|false }` — re-summon FloatingWindow after shell restart |
| `desks.json` | Desk registry (active_id, focus_id, standing orgs + org/effort) |
| `bandit.json` | Per-desk + global hire-policy arm stats / last decision |
| `web_egress.json` | Web gate mode (`off`\|`once`\|`session`) |
| `desks/<id>/dag.json` | Per-desk live DAG (kept on stop) |
| `desks/<id>/archive/` | Archived DAGs on dismiss |
| `dag.json` | Active desk’s DAG mirror for CLI/panel |
| `blackboard.jsonl` | Append-only blackboard entries |
| `blackboard.index.json` | Optional counts / by_kind index |

- **stop**: keep last live DAG visible.
- **dismiss**: archive DAG, tear down standing org, clear active global DAG.
- **retire**: drop short-lived node from live DAG; summary stays on blackboard.

## HTTP

- `GET /health` — liveness
- `GET /api/status` — objective + desk brief + effort + herdr_labels + dag + blackboard
- `POST /api/desk/start` — `{objective, kind?, reset?, cos?, effort?, herdr?, drive_herdr?, herdr_limit?}` — UI Start with objective sets `drive_herdr` and **kicks async** bounded `herdr.run_ready` (response includes `herdr_job`; poll `/api/status` or `GET /api/herdr/job`)
- `POST /api/desk/stop` — `{desk_id?}`
- `POST /api/desk/dismiss` — `{desk_id?}`
- `GET|POST /api/desk/status`
- `POST /api/desk/schedule` — `{spec|schedule|args, desk_id?}`
- `POST /api/desk/hire` — `{role|id, model_hint?, desk_id?}`
- `POST /api/desk/effort` — `{effort|value: 0..1, desk_id?}`
- `POST /api/desk/retire` — `{node_id|id, desk_id?}`
- `POST /api/desk/focus` — `{desk_id|id}`
- `GET|POST /api/web` — `{action: on|off|once|session}`
- `POST /api/seat` — **deprecated** alias → desk start auto
- `POST /api/cos/break` — `{objective?}`
- `POST /api/herdr/launch` — `{objective?}` → `herdr.focus` / launch UI (PATH from serve; prefers `omarchy-launch-terminal-herdr`, objective via env)
- `POST /api/herdr/run-ready` — `{limit?, dry_run?}`
- `GET /api/dag` — full DAG summary
- `POST /api/dag/nodes` — create node
- `POST /api/dag/nodes/{id}/state` — set state
- `GET /api/blackboard` — summary + items
- `POST /api/blackboard` — post entry

## CLI

```
okstratr status | desk start|stop|dismiss|status|schedule|hire|effort|retire|focus | web | serve
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
| `OKSTRATR_OKBAY_WORKSPACE` | Active okbay workspace id (`work` default; `biocure` = demo) |
| `OKSTRATR_OKBAY_WORK_ROOT` | Override workspace path |
| `OKSTRATR_OKBAY_THREAD_IDS` | Comma-separated okbay thread ids |
| `OKSTRATR_OKBAY_REVIEWS` / `OKSTRATR_CURATE_COMMIT` / `OKSTRATR_OKBAY_COMMIT_PATH` | Enable curate land path (hook) |

## Plugin kinds

- `service` — keep-loaded headless
- `bar-widget` — chip: desk **kind · state** (working|quiet) + DAG count / SETUP / STALE — not “seated”
- `panel` — fullscreen FloatingWindow desk UI (not Overlay): standing-desk rail, AGENT SPACE DAG canvas + blackboard, “Open in Herdr” (no text input)

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
  kernel.py          hire / ensure_cos / retire_worker / set_effort / route_herdr_input
  bandit.py          effort→weights, UCB1 arms, rewards
  web_egress.py      web gate off|once|session
  roles.py           role catalog + model hints
  desks.py           registry: start/stop/dismiss/status/schedule/hire/effort/retire/focus
  okbay.py           work-coverage / reviews / split stubs (no ingest)
  schedule_parse.py  named + interval schedule parser
  schedule.py        attention window stubs
  dag.py             persistent task graph (node.role)
  cos.py             kind-aware planner templates
  blackboard.py      persistent JSONL blackboard
  herdr.py           finite seats + labels + focus_desk stub
  server.py          HTTP on 8767
  cli.py             status | desk | seat(deprecated) | …
  status.py          status.json publisher
```

## Separation from okbay

- Separate git repo / plugin id: `benjsmith.okstratr`
- No copy of okbay Atlas/static
- No nest under `/workspace/okbay`
- No work-coverage ingest here — hooks only
- Optional later IPC (HTTP or status files), not a shared process

## Layout e2e gate (Ben)

Do **not** call the three-workspace layout complete until there is a **VM screenshot** of native **Herdr** showing **RUNNING AGENTS**. A separate Omarchy-VM executor owns agents + that capture; okstratr only starts desks and launches/focuses Herdr.
