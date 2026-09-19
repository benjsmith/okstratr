# Migration: Switchbay Agent Dashboard → okstratr observer (Phase 1b)

- **Status:** In progress (Schedule + Edit dialogs on observer 2026-09-20; residual SB chrome remains)
- **Charter:** agent-dashboard features belong in **okstratr**; Switchbay keeps rail UI + settings that write the registry
- **Constraint:** no chat/query/objective bar on the observer; no iframes; no TUI; hosted mode keeps settings strip hidden

## Inventory (Switchbay `AgentDashboardTab` / Agents widgets)

| Switchbay surface | Notes | okstratr home |
|-------------------|-------|---------------|
| Workspace running-counts expander | Switch workspace + open Agents | Shell concern (Switchbay workspaces) — **out of scope** for observer |
| AGENT SPACE DAG + token-flow canvas | Live / recent / standing roots | **Already** observer AGENT SPACE (`/api/dag`, status.dagGraph) |
| Running list (poll `/api/runs/active`) | Fan-out groups, cancel/bg, transcript | Rail/run registry is Switchbay; desks map to Start/Stop — **partial** via desk rail |
| Desks panel Start / Edit / Schedule / Dismiss | Standing desks | **Already** Start/Stop/Dismiss/Delete + Schedule dialog + objective Edit dialog; Edit→rail composer still SB when hosted |
| Tools / Rules / Command palettes / Providers / Skills | Config + rail authorship | Settings/registry/shell — **not** observer (hosted: shell owns) |
| Chief-of-staff model allowlist | Writes orchestration models | Registry SSOT via `/api/harness*` (Phase 1a) — **not** HTML settings when hosted |
| Stats: tokens, activity, fan-out counts | From run records | Lifecycle `tokens` / `files` / desk `by_kind`·`by_state` |

## Mapping → observer (Phase 1b landed)

| Parity item | Landed? | Where |
|-------------|---------|-------|
| Desk rail Start / Stop / Dismiss / Delete | **Yes (1c)** | Left rail → `/api/desk/*` via `desk_rail.py`; Start may pass `desk_id` |
| Quiet all working desks | **Yes (1b)** | Header `Quiet all` → `POST /api/desk/quiet_standing` |
| DAG AGENT SPACE nodes/edges/token flow | Yes (pre-1b) | Main canvas |
| Blackboard + clear (non-settings) | Yes | Main panel |
| Hosted: HTML settings hidden | Yes (1a) | `?host=` / `X-Okstratr-Host` |
| Stats useful for desks (tokens, active/idle, files/lines) | **Yes (1b)** | Header chips + **Desk dashboard** panel (visible when hosted) |
| Groupings by kind / state | **Yes (1b)** | Kind chips + Working/Idle/Standing sections + filter All/Run/Idle |
| Schedule chip on desk row | **Yes (1b)** | Badge from `desk.schedule` when present |
| Schedule create/edit dialog | **Yes (1c)** | Observer modal → `POST /api/desk/schedule` (+ clear) |
| Objective Edit dialog | **Yes (1c)** | Cheap modal → `POST /api/desk/start` with `desk_id` (no chat bar) |
| Run transcript / kill / background | No | Stays Switchbay rail / future run SSOT — not desks |
| Chat / query bar | **Never** | Charter / ADR-003 |
| Workspace switcher nav | No | Switchbay shell |
| Tools / Rules / Palettes / Skills panels | No | Shell + registry |
| Schedule create dialog | **Yes (1c)** | Observer Schedule modal |

## Still TODO (before parity checklist delete)

- [ ] Richer run-oriented view if/when okstratr owns an active-run registry (optional)
- [x] Schedule attach/edit UI on desk row (dialog) — landed 2026-09-20
- [x] Objective Edit dialog (desk brief without chat bar) — landed 2026-09-20
- [ ] Interrupted-orchestration resume list (Switchbay DesksPanel) if kernel exposes equivalent
- [ ] E2E evidence in umbrella `evidence/` vs Switchbay Agents tab
- [ ] Feature-flag / dual-stack gate before thinning Switchbay Agents tab (charter #2)

## Remaining Switchbay-only chrome (do not delete yet)

Desk Start/Stop/Dismiss/Delete (+ Quiet all) now live on the observer rail and
reuse the okstratr desk lifecycle (`POST /api/desk/start|stop|dismiss|delete`,
`POST /api/desk/quiet_standing`). **Do not remove** Switchbay Agents UI until
umbrella parity marks the row ✓/▲. Still Switchbay-owned:

| Chrome | Why it stays in Switchbay |
|--------|---------------------------|
| Edit→rail composer (`sy:rail-set-input`) | Shell chat I/O when hosted; observer **Edit** updates `desk.objective` via dialog (no chat bar, ADR-003) |
| Active-run transcript / cancel / background | Switchbay run registry (`/api/runs/active`) — okstratr has herdr job status only, not run SSOT |
| Workspace switcher + open-Agents | Shell workspaces |
| Tools / Rules / Palettes / Providers / Skills | Shell + registry settings (hosted: shell owns) |
| Interrupted-orchestration resume | Switchbay orchestration API |

Contract helper: `okstratr.desk_rail` (`DESK_RAIL_ACTIONS`, `SWITCHBAY_ONLY_CHROME`).

## Verify

```bash
# Desk dashboard + rail controls + schedule/edit modals; settings still hidden when hosted
curl -s 'http://127.0.0.1:8767/observer/?host=switchbay' | grep -E 'desk-dashboard|btn-quiet-all|desk-rail|schedule-modal|edit-modal|OKSTRATR_HOSTED'
curl -s 'http://127.0.0.1:8767/observer/?host=switchbay' | grep -E 'settings-panel|class="config"'
# Lifecycle feeds stats
curl -s 'http://127.0.0.1:8767/api/lifecycle' | jq '{desks,tokens,files}'
# Desk rail APIs (dry-run herdr)
curl -s -X POST 'http://127.0.0.1:8767/api/desk/start' -H 'Content-Type: application/json' \
  -d '{"kind":"work","objective":"rail check"}' | jq '{ok,action,desk:.desk.desk.id//.desk.id}'
# Schedule attach + clear
DID=$(curl -s -X POST 'http://127.0.0.1:8767/api/desk/start' -H 'Content-Type: application/json' \
  -d '{"kind":"work","objective":"sched"}' | jq -r '.desk.desk.id//.desk.id')
curl -s -X POST 'http://127.0.0.1:8767/api/desk/schedule' -H 'Content-Type: application/json' \
  -d "{\"desk_id\":\"$DID\",\"spec\":\"daily\"}" | jq '{ok,action,schedule:.schedule.describe}'
curl -s -X POST 'http://127.0.0.1:8767/api/desk/schedule' -H 'Content-Type: application/json' \
  -d "{\"desk_id\":\"$DID\",\"clear\":true}" | jq '{ok,action}'
```

## Related

- ADR-004 hosted proxy + registry SSOT
- ADR-003 skill observer vs kernel (no chat on observer)
- Umbrella `PARITY-CHECKLIST.md` → Agents / okstratr
