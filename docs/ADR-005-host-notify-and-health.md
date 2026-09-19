# ADR-005: host_notify envelope + shared health block

- **Status:** Accepted (auto-start + path-native notify slice)
- **Date:** 2026-09-19
- **Contract:** skill-shell `CONTRACT-AUTO-START-AND-NOTIFY.md`

## Decision

1. **okstratr emits** `okstratr.host_notify` v1; hosts map to one sink (rail / Herdr / bare harness I/O).
2. **Bare CLI is first-class**; `start|restart|status|shutdown` remain the verbs.
3. Schedule fire lives in `schedule.fire_due` (existing desk-schedule path); reconcile from `status.write_status`.
4. `/api/status` + CLI `status` expose `health.{ce,okstratr,wiki_build}`.

## Env

- `OKSTRATR_HOST_NOTIFY_URL` — POST target
- `OKSTRATR_HOSTED` / `OKSTRATR_HOST` — `switchbay|okbay` defaults
- `OKSTRATR_JSON_NOTIFY` / `--json-notify` — bare JSON lines
