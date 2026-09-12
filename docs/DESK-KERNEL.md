# Desk kernel (Switchbay-style)

> Design authority for okstratr’s hiring manager, desk lifecycle, roles, and Herdr pairing.
> Implementation today: desk lifecycle + kernel hire/retire + kind-aware planner
> templates + Herdr labels/focus stub. No live Grok/Herdr model calls; finite-job /
> dry-run Herdr rules remain. Full Auto bandit and live Herdr focus sync are
> **not** in this slice.
>
> **Switchbay release pending** — deep parity check against Switchbay once that tree is
> available; vocabulary here is Switchbay-inspired and may be tightened after review.

## Omarchy product

**Omarchy product = okbay (knowledge) + okstratr (orchestrator).**

| Piece | Owns |
|-------|------|
| **okbay** | Knowledge graph, Atlas, Nautilus reveal, **work-coverage ingest**, reviews / commit land path |
| **okstratr** | Kernel (hiring manager), desks, DAG, CoS, blackboard, schedule, Herdr pairing, bar/panel |
| **Herdr** | Text input + live agent panes (runtime / multiplexer) |

Either half should remain useful alone; side-by-side is the composed desk.

## Work-coverage and workspaces (okbay owns ingest)

Work-coverage **default lives in okbay**: magical **all-`~/Work`** watch. okstratr
does **not** ingest files; desks operate over the **active okbay workspace** and
**thread ids**.

| Workspace | Role |
|-----------|------|
| **`~/Work` (default)** | Magical all-Work coverage — okbay ingest default |
| **Biocure** | Current **demo** workspace in use (**not** an opt-in / not “optional named”) |
| **Additional focused** | Optional = *create* more focused workspaces |

**Smooth path (okbay split tool, stub here):** subset of `~/Work` subfolders → new
wiki; those folders join the new workspace watch list and are **excluded** from
default Work coverage. Hook: `okstratr.okbay.split_workspace` (no ingest).

Bind a workspace with `OKSTRATR_OKBAY_WORKSPACE` / `OKSTRATR_OKBAY_WORK_ROOT`.
Desks store `okbay_workspace_id` + `thread_id` and label Herdr with both.

## Vocabulary

| Term | Meaning |
|------|---------|
| **Kernel** | Hiring manager. Always uses the strongest available model (or an explicit user choice). Decides *how many* workers to buy per unit quality from the effort slider. |
| **Desk** | A standing org for one objective: CoS + hired roles, a live DAG, blackboard claims, optional schedule. Bound to an okbay workspace / thread ids. |
| **CoS** | Chief of staff — the **only** user interface into a desk. Humans talk to CoS (via Herdr); CoS requests firepower from the kernel. |
| **Role** | A worker slot (planner, investigator, …) with orthogonal permissions/precedents; pi-agent-plugin style. |
| **Kind** | Desk type template (`curate`, `work`, `code`, `deck`, `auto`, …). Defaults, **not** a closed enum forever. |
| **DAG** | Durable task graph for the desk. Short-lived workers **retire** from it (no unbounded growth). |
| **Blackboard** | Shared claims / decisions / evidence (succinct summaries only from workers). |
| **Quiet** | Desk stopped: last live DAG kept visible; CoS remains ready for input; no active hiring. |
| **Dismissed** | Desk disbanded: standing org torn down; DAG cleared/archived. |

## Kernel = hiring manager

1. Read the **effort slider** → parameters of a utility function (network / info-theory framed): how many workers to buy per unit quality, when to prefer diversity vs depth.
2. Always hire a **CoS** first — CoS is the sole user-facing agent for that desk (`ensure_cos`).
3. CoS requests roles / copies; `kernel.hire(desk, request)` grants until the desk is full (`hire_cap`) or CoS asks for more/different firepower.
4. Persist the desk org: CoS + granted roles with **model hints** and **effort**.
5. If no existing desk type fits the objective, the kernel may **create a new desk type and roles** (kinds are defaults, not forever-closed).
6. Prefer **independent opinions**: orthogonal permissions and precedents, and different models when multiples of a role are allowed (pi-agent-plugin style).
7. Workers send **succinct summaries only** — never full reasoning traces (channel capacity). Token spend must land useful work.
8. `kernel.retire_worker(node_id)` removes short-lived nodes from the active DAG and archives a summary to the blackboard (prevents DAG buildup).

Stub today: no real LLMs. `hire_plan` / `spin_up_desk_spec` / `hire` / `retire_worker` / `route_herdr_input` are structural.

### Planner breakdown → Switchbay roles

When desk kind is **`work` or `auto`**, planner breakdown maps to Switchbay
roles — **investigator → synthesizer → verifier** — not only the historical
`cos-clarify` chain.

Kind-specific templates (kept):

| Kind | Template nodes |
|------|----------------|
| `work` / `auto` | `investigator` → `synthesizer` → `verifier` |
| `curate` | `curate-propose` → `curate-review` → `curate-commit` |
| `code` | `code-investigate` → `code-implement` → `code-verify` |
| `deck` | `deck-outline` → `deck-synthesize` → `deck-verify` |
| no kind / no desk | historical `cos-clarify` → `cos-gather` → `cos-execute` → `cos-verify` |

## Desk kinds (defaults)

| Kind | Typical use |
|------|-------------|
| `curate` | Propose → review → **commit** pages (must have a land path; see guards below) |
| `work` | General execution toward an objective |
| `code` | Implementation / verify loops |
| `deck` | Briefing / narrative synthesis |
| `auto` | Kernel picks from objective text (heuristic today) |

Kernel may invent new kinds later when none fit.

## Default roles

Always present:

| Role | Role |
|------|------|
| `cos` | Only user interface; requests firepower; prioritizes |
| `planner` | Breaks work into DAG nodes |
| `investigator` | Gathers evidence / context |
| `verifier` | Checks outcomes against criteria |
| `synthesizer` | Merges independent opinions into succinct claims |

Optional / kind-specific:

| Role | Notes |
|------|-------|
| `curator_worker` | Drafts curated content — **refused** unless a commit/review path is configured |
| `curator_planner` | Plans curate propose→review→commit |
| `curator_judge` | Reviews before commit |
| `researcher` | Optional web search **behind approval** |

See `okstratr.roles` for constants, model hints, and independence notes.

## Desk lifecycle (CLI / HTTP)

```
desk start [kind] [objective…]   → state=working; hire CoS + defaults; seed DAG
desk stop                        → state=quiet; keep last live DAG; CoS ready
desk dismiss                     → state=dismissed; tear down standing org; archive/clear DAG
desk status                      → active + registry snapshot (effort slider stub)
desk schedule …                  → parse + attach schedule (dialog UI later)
desk hire <role>                 → kernel.hire (cap + curate guards)
desk retire <node_id>            → retire_worker; summary → blackboard
desk focus [desk_id]             → stub bidirectional Herdr sync
```

States: **`working` | `quiet` | `dismissed`**.

- **stop**: do not wipe the DAG; CoS remains the contact surface for further input.
- **dismiss**: archive the desk’s DAG under the state dir, remove it from the standing registry (or mark dismissed and drop active), clear standing org so tokens are not burned on a dead desk.

`seat` remains a **thin deprecated alias** for one release: warns, then `desk start auto …`.

## Schedule parse

`desk schedule` opens scheduling (for now: parse args; dialog is future UI).

- **Named:** `hourly`, `daily`, `weekly`, `monthly`, `yearly` | `annually`
- **Intervals:** number + optional unit; space optional; bare number ⇒ **hours**
- **Units:** `s`, `m`|`min`, `h`, `d`, `w`|`wks`
- **Combinations:** e.g. `1h30m` = 90 minutes

Implemented in `okstratr.schedule_parse` with exhaustive tests.

## Guardrails (historical Switchbay bugs)

1. **Short-lived workers must retire from the DAG** — `kernel.retire_worker(node_id)`
   removes the node from the active graph and archives a **succinct** summary on
   the blackboard. Standing `root` is refused. Do not let finished ephemeral
   nodes accumulate forever.
2. **Curate path must have a commit path** — propose→review must be able to land
   pages. `kernel.hire` / `hire_plan` **refuse** to spawn `curator_worker` unless
   a commit/review path is configured (hook stub: `okstratr.okbay.reviews_commit_path`,
   env `OKSTRATR_OKBAY_REVIEWS` / `OKSTRATR_CURATE_COMMIT` / `OKSTRATR_OKBAY_COMMIT_PATH`,
   or `desk.commit_path`). No token burn without a land path. Ingest stays in okbay.
3. **Token usage must land useful work** — summaries on the blackboard / DAG
   outcomes, not reasoning dumps.
4. **Hire cap** — effort slider sets a max granted-role count (low 2 / mid 6 / high 10).
   Further `hire` calls return `guard=hire_cap`.

## Herdr interaction

| Surface | Role |
|---------|------|
| **Herdr** | Text input + agent panes. Every agent **name/label includes `desk_id` + `thread_id`**. |
| **okstratr UI** | Left-pane desk switch (Herdr-familiar), DAG + blackboard. **No free text input** (that’s Herdr). Sync focus with Herdr. Close warns / suspends kernel. |

### Labeling

Agent ids: `okstratr-{desk}-{role}-{node}` (filesystem-safe, capped at 64).

Status JSON includes `herdr_labels` and `focus_desk_id`.

### Input passthrough → kernel

`kernel.route_herdr_input(text, desk_id=, thread_id=)`:

1. If targeted at an existing desk’s **CoS pane** (`desk_id` / `thread_id`) → that standing desk.
2. If new chat / no desk → kernel spins up an appropriate desk (minimal for simple questions).

### Focus + close

- `focus_desk(desk_id)` — stub for bidirectional sync (records focus, would focus that CoS in Herdr).
- Switching desks in okstratr focuses that CoS in Herdr, and vice versa (live sync later).
- Closing okstratr: **warn** that the kernel will shut down, desks suspend (quiet), and the session returns to regular Herdr.

**Close-warning copy (QML later — bind `status.ui.close_warning`):**

> Closing Okstratr will shut down the kernel. Standing desks will suspend (quiet) and the session returns to regular Herdr. Continue?

Finite-job rule unchanged: never leave Grok/Herdr agents running after a node — always stop/release. Dry-run via `OKSTRATR_HERDR_DRY_RUN` / `--dry-run`. Tests default dry-run.

## Effort slider → utility (sketch)

Not a live bandit yet. Stub is published on desk/kernel **status** (`effort`, `effort_slider`).

- Effort high (≥ 0.70) → cap 10; more workers per quality unit, more model diversity, deeper verify.
- Effort mid → cap 6 (default kinds).
- Effort low (< 0.35) → cap 2; minimal desk (CoS+planner), shorter channels.
- Utility is information-theoretic: expected bits of useful blackboard/DAG progress per token, with a cost on redundant correlated opinions.

## Package map (this slice)

```
docs/DESK-KERNEL.md          this document
src/okstratr/kernel.py       hire / ensure_cos / retire_worker / route_herdr_input
src/okstratr/roles.py        role catalog + model hints + Switchbay plan roles
src/okstratr/desks.py        registry: start/stop/dismiss/status/schedule/hire/retire/focus
src/okstratr/okbay.py        work-coverage / reviews / split stubs (no ingest)
src/okstratr/cos.py          kind-aware planner templates
src/okstratr/herdr.py        finite seats + okstratr-{desk}-{role}-{node} labels
src/okstratr/schedule_parse.py  interval / named schedule parser
CLI: desk … ; seat → deprecated alias
HTTP: /api/desk/start|stop|dismiss|status|schedule|hire|retire|focus (+ /api/seat alias)
```

## What is deliberately out of scope (for now)

- Full Auto bandit / live effort optimization
- Live Herdr focus sync (stub `focus_desk` only)
- Real Grok/Herdr API calls from the kernel
- Scheduling dialog UI / full left-pane desk switch UI
- okbay ingest / work-coverage implementation (hooks only)
- Inventing arbitrary new desk kinds at runtime (documented; stub may only pick defaults)
