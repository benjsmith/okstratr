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
| **okstratr** (this repo) | Desk console + orchestrator — **query input**, workspace bind, kernel, desks, durable DAG, CoS, schedule, blackboard, bar/panel |
| **Herdr** (native Omarchy) | Normal agent **runtime / multiplexer** — panes, workspaces, agent lifecycle, socket API (no desk-kind grouping in this slice) |

Work-coverage default lives in **okbay** (magical all-`~/Work`). **Biocure** is the current demo workspace in use (not an opt-in). Optional = create more focused workspaces via okbay split (subset of Work folders → new wiki; those folders leave default coverage). okstratr desks bind the active okbay workspace / thread ids — they do not ingest.

### Does Herdr already do orchestration like okstratr?

**No.** Herdr does **runtime** orchestration (who is running, prompt them, wait for blocked/idle; agents can fan out in terminals). It does **not** own the desk-brain: durable product DAG across desks, CoS prioritization, human blackboard of claims/decisions tied to okbay knowledge, schedule/attention windows, or Omarchy bar/panel desk UI.

**okstratr** owns the **query input + plan + memory of the desk**; **Herdr** owns **live agent terminals**. Flow: desk start → kernel hires CoS + roles → CoS expand DAG → for ready nodes `herdr run-ready` (start/prompt/wait/**stop**) → post outcomes to blackboard → advance DAG.

**Finite-job rule:** never leave Grok/Herdr agents running after a node — always stop/release.

See [docs/ADR-001-cli-tui-harness.md](docs/ADR-001-cli-tui-harness.md) for the CLI/TUI-first + harness-agnostic vision, and [docs/DESK-KERNEL.md](docs/DESK-KERNEL.md) for the hiring-manager / desk / Herdr design, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for package map + APIs.



## Skill + observer panel

okstratr ships as an **in-harness skill** (`skills/okstratr/SKILL.md`) that bundles
the desk-kernel server and the **observer panel** (HTML desks/DAG/settings surface —
not a second chat). Text I/O stays in Herdr / other CLI harnesses; Omarchy may display
the observer panel.

```bash
# Install (editable) + optional skill copy into your harness skills dir
pip install -e '.[tui]'

# Lifecycle (consent on start unless --yes)
okstratr doctor
okstratr start            # prompts if serve is down
okstratr start --yes      # automation / already consented
okstratr status           # status box
okstratr restart
okstratr shutdown

# Observer panel (when serve is up)
open http://127.0.0.1:8767/observer/   # also /panel/
okstratr observer                     # prints URL
okstratr panel --serve                # optional dedicated :8768 host
```

In-harness slash:

```
/okstratr start | restart | shutdown | status
```

See [docs/ADR-003-skill-observer-vs-kernel.md](docs/ADR-003-skill-observer-vs-kernel.md).

### Mac CLI workflow (no Omarchy)

```bash
# No Herdr on Mac → direct CLI seating (grok / claude / …)
okstratr config set backend direct
okstratr config set harness.grok.default_model grok-4.6
okstratr config set harness.grok.settings.reasoning low

# Terminal 1 — desk brain daemon (restart after config/pull)
pkill -f 'okstratr serve' 2>/dev/null || true
okstratr serve          # http://127.0.0.1:8767

# Terminal 2 — TUI (Ghostty or any terminal; --snapshot for CI)
okstratr tui
# okstratr tui --snapshot   # ## DAG (topo) lists CoS nodes for active desk

# Optional multiplexer when installed
# herdr

# Observability — group seats like Omarchy desks
okstratr agents
okstratr agents --desk <desk_id>

# Harness / models (Switchbay-inspired rungs, no LiteLLM)
okstratr harness list
okstratr model list
```

`drive_herdr: true` from the Panel/TUI means **drive seats** — with `backend=direct`
that is `harness.direct` (cwd sandbox + grok-4.6 + `--reasoning-effort low`), not a
Herdr pane start. Direct `grok` seats use a **positional** prompt (not `--prompt`). `GET /api/dag` reads the focused desk's `desks/<id>/dag.json`.

Every seat (Herdr + direct) labels with `desk_id` + `thread_id`. Config file:
`~/.config/okstratr/harnesses.toml`.


> **Switchbay release pending** — deep parity check against Switchbay once that tree is available.

Either plugin can be useful alone. They share a future multi-workspace layout, not a monorepo.

### Future workspaces (vision)

1. **Fullscreen Atlas** — okbay knowledge plane
2. **Linked Nautilus** — file reveal next to Atlas
3. **okstratr + Herdr side by side** — orchestrator panel / bar + agent session

## What works today

- Omarchy kinds: `service`, `bar-widget`, `panel` (no Atlas overlay)
- **Five default standing desks** always exposed by status/API/UI: `work`, `curate`, `code`, `deck`, `auto` (`idle|working|quiet`; dismiss returns the kind to idle)
- **Desk lifecycle**: `desk start|stop|dismiss|status|schedule` (live states `working|quiet|dismissed`)
- **Kernel**: live **effort-bandit** hire / ensure_cos / retire_worker; persist org + effort + model hints (no real LLM)
- **Web egress gate**: default off; `web on --once|--session`; status chip Web: Off|Once|Session
- **Schedule parse**: named cadences + intervals (`90`, `1h30m`, `2 wks`, …)
- **Persistent DAG** (`dag.json` + per-desk copies): add / ready / done / fail / reset / topo + cycle detect
- **Persistent blackboard** (`blackboard.jsonl`): post / head / search / clear (archive)
- **Planner** kind-aware templates: work/auto → investigator/synthesizer/verifier
- **Herdr** `herdr run-ready`: finite jobs, labels `okstratr-{desk}-{role}-{node}`, dry-run via `OKSTRATR_HERDR_DRY_RUN` / `--dry-run`
- CLI: `status | desk (start|stop|dismiss|status|schedule|hire|effort|retire|focus) | web | seat(deprecated) | cos | herdr | dag | bb | serve`
- HTTP: `/health`, `/api/status`, `/api/desk/*`, `/api/workspaces`, `/api/workspace/select`, `/api/config/roles`, `/api/web`, `/api/seat` (alias), `/api/cos/break`, `/api/herdr/*`, `/api/dag`, `/api/blackboard`
- Bar chip shows desk kind · state + DAG count + **Web:** chip; **panel is a fullscreen desk console** with objective query input, okbay workspace picker (local fallback), five standing desk rows with Start/Stop/Dismiss/Schedule, persisted role Config ⚙, **AGENT SPACE**, blackboard, and Open in Herdr

State dir: `~/.local/state/okstratr/` (`status.json`, `ui.json`, `selected_workspace.json`, `config/roles.json`, desks/DAG/blackboard; tests: `OKSTRATR_STATE_DIR`).

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
Panel.qml              fullscreen desk console: input/workspace/config + Herdr launch
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

**Bar chip:** left-click opens/focuses the panel (same as Super+Shift+O); right-click is a **no-op** for now (reserved). Omarchy menu entry: `contrib/okstratr-menu.jsonc` → Panel.

The Omarchy **panel** (`Panel.qml`) is a **fullscreen desk console**: a Quickshell `FloatingWindow` toplevel (native window chrome / maximize), not a tiny corner Overlay layershell. Super+Shift+O (see `contrib/hypr-bindings.lua`) or the bar chip summons it. The left rail always shows `work`, `curate`, `code`, `deck`, and `auto`, each with state plus Start/Stop/Dismiss/Schedule. The main pane owns the **desk objective query input**, okbay workspace selection (`GET :8766/api/workspace/list`, or `local` if unavailable), **AGENT SPACE**, blackboard, Config ⚙, and Open in Herdr.

**Ownership:** okstratr owns desk query input and durable orchestration. Herdr stays the normal agent runtime; a future grouping lens belongs there, but is not part of this slice. Workspace and role config selections persist under `OKSTRATR_STATE_DIR` and are included in status.

**Query kind (locked):** Start from the query box uses **`auto`**. Prefix with `/work`, `/curate`, `/code`, `/deck`, or `/auto` to override. No free-text kind classifier. Rail **Start** uses the row’s kind unless the query has a slash.

Panel open/close is persisted in `~/.local/state/okstratr/ui.json` (`panel_open`). After an omarchy-shell restart, if the desk was open it is re-summoned automatically; an explicit close stays closed. Theme colors come from `qs.Commons` `Color` (Omarchy `colors.toml`) with Tokyo Night fallbacks.

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
