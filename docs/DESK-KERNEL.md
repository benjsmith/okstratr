# Desk kernel (Switchbay-style)

> Design authority for okstratr’s hiring manager, desk lifecycle, roles, and Herdr pairing.
> Implementation today: docs + stubs + desk lifecycle + schedule parse. No live Grok/Herdr
> model calls; finite-job / dry-run Herdr rules remain. Full Auto bandit and live Herdr
> focus sync are **not** in this slice.
>
> **Switchbay release pending** — deep parity check against Switchbay once that tree is
> available; vocabulary here is Switchbay-inspired and may be tightened after review.

## Vocabulary

| Term | Meaning |
|------|---------|
| **Kernel** | Hiring manager. Always uses the strongest available model (or an explicit user choice). Decides *how many* workers to buy per unit quality from the effort slider. |
| **Desk** | A standing org for one objective: CoS + hired roles, a live DAG, blackboard claims, optional schedule. |
| **CoS** | Chief of staff — the **only** user interface into a desk. Humans talk to CoS (via Herdr); CoS requests firepower from the kernel. |
| **Role** | A worker slot (planner, investigator, …) with orthogonal permissions/precedents; pi-agent-plugin style. |
| **Kind** | Desk type template (`curate`, `work`, `code`, `deck`, `auto`, …). Defaults, **not** a closed enum forever. |
| **DAG** | Durable task graph for the desk. Short-lived workers **retire** from it (no unbounded growth). |
| **Blackboard** | Shared claims / decisions / evidence (succinct summaries only from workers). |
| **Quiet** | Desk stopped: last live DAG kept visible; CoS remains ready for input; no active hiring. |
| **Dismissed** | Desk disbanded: standing org torn down; DAG cleared/archived. |

## Kernel = hiring manager

1. Read the **effort slider** → parameters of a utility function (network / info-theory framed): how many workers to buy per unit quality, when to prefer diversity vs depth.
2. Always hire a **CoS** first — CoS is the sole user-facing agent for that desk.
3. CoS requests roles / copies; kernel grants until the desk is full or CoS asks for more/different firepower.
4. If no existing desk type fits the objective, the kernel may **create a new desk type and roles** (kinds are defaults, not forever-closed).
5. Prefer **independent opinions**: orthogonal permissions and precedents, and different models when multiples of a role are allowed (pi-agent-plugin style).
6. Workers send **succinct summaries only** — never full reasoning traces (channel capacity). Token spend must land useful work.

Stub today: `okstratr.kernel` chooses a default kind from a light objective heuristic, always ensures a CoS in the role list, and does **not** call real LLMs.

## Desk kinds (defaults)

| Kind | Typical use |
|------|-------------|
| `curate` | Propose → review → **commit** pages (must have a land path; see bugs below) |
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
| `curator_worker` | Drafts curated content |
| `curator_planner` | Plans curate propose→review→commit |
| `curator_judge` | Reviews before commit |
| `researcher` | Optional web search **behind approval** |

See `okstratr.roles` for constants and independence notes.

## Desk lifecycle (CLI / HTTP)

```
desk start [kind] [objective…]   → state=working; hire CoS + defaults; seed DAG
desk stop                        → state=quiet; keep last live DAG; CoS ready
desk dismiss                     → state=dismissed; tear down standing org; archive/clear DAG
desk status                      → active + registry snapshot
desk schedule …                  → parse + attach schedule (dialog UI later)
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

1. **Short-lived workers must retire from the DAG** — no unbounded DAG growth; finished ephemeral nodes leave (or are archived), not accumulate forever.
2. **Curate path must have a commit path** — propose→review must be able to land pages. Do not spawn writers that cannot commit (no token burn without a land path).
3. **Token usage must land useful work** — summaries on the blackboard / DAG outcomes, not reasoning dumps.

## Herdr interaction

| Surface | Role |
|---------|------|
| **Herdr** | Text input + agent panes. Each live agent labeled with **desk id + thread id** (okstratr). |
| **okstratr UI** | Left pane desk list (Herdr-familiar), DAG + blackboard; start / stop / dismiss / schedule / switch. **No free text input** (that’s Herdr). |

Routing Herdr text into the kernel:

1. If targeted at an existing desk’s **CoS pane** → that standing desk.
2. If new chat / no desk → kernel spins up an appropriate desk (minimal for simple questions).

Focus sync (stubbed, not live yet):

- Switching desks in okstratr focuses that CoS in Herdr, and vice versa.
- Closing okstratr: **warn** that the kernel will shut down, desks suspend, and the session returns to regular Herdr.

Finite-job rule unchanged: never leave Grok/Herdr agents running after a node — always stop/release. Dry-run via `OKSTRATR_HERDR_DRY_RUN` / `--dry-run`.

## Effort slider → utility (sketch)

Not implemented as a live bandit yet. Intended framing:

- Effort high → more workers per quality unit, more model diversity, deeper verify.
- Effort low → minimal desk (often CoS-only or CoS+planner), shorter channels.
- Utility is information-theoretic: expected bits of useful blackboard/DAG progress per token, with a cost on redundant correlated opinions.

## Package map (this slice)

```
docs/DESK-KERNEL.md          this document
src/okstratr/kernel.py       stub hiring manager (kind heuristic, ensure CoS)
src/okstratr/roles.py        role catalog + independence notes
src/okstratr/desks.py        registry: start/stop/dismiss/status/schedule
src/okstratr/schedule_parse.py  interval / named schedule parser
CLI: desk … ; seat → deprecated alias
HTTP: /api/desk/start|stop|dismiss|status|schedule (+ /api/seat alias)
```

## What is deliberately out of scope (for now)

- Full Auto bandit / live effort optimization
- Live Herdr focus sync
- Real Grok/Herdr API calls from the kernel
- Scheduling dialog UI
- Inventing arbitrary new desk kinds at runtime (documented; stub may only pick defaults)
