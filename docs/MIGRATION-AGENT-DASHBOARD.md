# Migration: Switchbay Agent Dashboard → okstratr observer (Phase 1b)

- **Status:** In progress (highest-value parity landed 2026-09-18)
- **Charter:** agent-dashboard features belong in **okstratr**; Switchbay keeps rail UI + settings that write the registry
- **Constraint:** no chat/query/objective bar on the observer; no iframes; no TUI; hosted mode keeps settings strip hidden

## Inventory (Switchbay `AgentDashboardTab` / Agents widgets)

| Switchbay surface | Notes | okstratr home |
|-------------------|-------|---------------|
| Workspace running-counts expander | Switch workspace + open Agents | Shell concern (Switchbay workspaces) — **out of scope** for observer |
| AGENT SPACE DAG + token-flow canvas | Live / recent / standing roots | **Already** observer AGENT SPACE (`/api/dag`, status.dagGraph) |
| Running list (poll `/api/runs/active`) | Fan-out groups, cancel/bg, transcript | Rail/run registry is Switchbay; desks map to Start/Stop — **partial** via desk rail |
| Desks panel Start / Edit / Schedule / Dismiss | Standing desks | **Already** Start/Stop/Dismiss/Delete; Edit→rail **out**; Schedule UI **partial** (badge only) |
| Tools / Rules / Command palettes / Providers / Skills | Config + rail authorship | Settings/registry/shell — **not** observer (hosted: shell owns) |
| Chief-of-staff model allowlist | Writes orchestration models | Registry SSOT via `/api/harness*` (Phase 1a) — **not** HTML settings when hosted |
| Stats: tokens, activity, fan-out counts | From run records | Lifecycle `tokens` / `files` / desk `by_kind`·`by_state` |

## Mapping → observer (Phase 1b landed)

| Parity item | Landed? | Where |
|-------------|---------|-------|
| Desk rail Start / Stop / Dismiss / Delete | Yes (1a) | Left rail |
| Quiet all working desks | **Yes (1b)** | Header `Quiet all` → `POST /api/desk/quiet_standing` |
| DAG AGENT SPACE nodes/edges/token flow | Yes (pre-1b) | Main canvas |
| Blackboard + clear (non-settings) | Yes | Main panel |
| Hosted: HTML settings hidden | Yes (1a) | `?host=` / `X-Okstratr-Host` |
| Stats useful for desks (tokens, active/idle, files/lines) | **Yes (1b)** | Header chips + **Desk dashboard** panel (visible when hosted) |
| Groupings by kind / state | **Yes (1b)** | Kind chips + Working/Idle/Standing sections + filter All/Run/Idle |
| Schedule chip on desk row | **Yes (1b)** | Badge from `desk.schedule` when present |
| Run transcript / kill / background | No | Stays Switchbay rail / future run SSOT — not desks |
| Chat / query bar | **Never** | Charter / ADR-003 |
| Workspace switcher nav | No | Switchbay shell |
| Tools / Rules / Palettes / Skills panels | No | Shell + registry |
| Schedule create dialog | TODO | API exists (`POST /api/desk/schedule`); UI later |

## Still TODO (before parity checklist delete)

- [ ] Richer run-oriented view if/when okstratr owns an active-run registry (optional)
- [ ] Schedule attach/edit UI on desk row (dialog)
- [ ] Interrupted-orchestration resume list (Switchbay DesksPanel) if kernel exposes equivalent
- [ ] E2E evidence in umbrella `evidence/` vs Switchbay Agents tab
- [ ] Feature-flag / dual-stack gate before thinning Switchbay Agents tab (charter #2)

## Verify

```bash
# Desk dashboard markup present; settings still hidden when hosted
curl -s 'http://127.0.0.1:8767/observer/?host=switchbay' | grep -E 'desk-dashboard|btn-quiet-all|OKSTRATR_HOSTED'
curl -s 'http://127.0.0.1:8767/observer/?host=switchbay' | grep -E 'settings-panel|class="config"'
# Lifecycle feeds stats
curl -s 'http://127.0.0.1:8767/api/lifecycle' | jq '{desks,tokens,files}'
```

## Related

- ADR-004 hosted proxy + registry SSOT
- ADR-003 skill observer vs kernel (no chat on observer)
- Umbrella `PARITY-CHECKLIST.md` → Agents / okstratr
