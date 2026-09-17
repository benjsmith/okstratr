# ADR-002: Board duration, visible names, ops audit

- **Status:** Accepted
- **Date:** 2026-09-18
- **Deciders:** Ben / okstratr

## Context

Long-lived blackboard entries and archive files created a privacy problem.
A separate “durable agents” switch added complexity without matching how Ben
wants retention to work.

## Decision

### 1. Single parameter: board duration

- Config: `blackboard.duration` / `blackboard.duration_days` (default **3 days**).
- Env: `OKSTRATR_BB_DURATION` (aliases: `OKSTRATR_BB_DURATION_DAYS`,
  legacy `OKSTRATR_BB_RETENTION_DAYS`).
- Slash: `/bb duration <value>` — accepts `3`, `3d`, `72h`, `60m`, `0`.
- CLI: `okstratr bb duration [value]`;
  `okstratr config set blackboard.duration 3`.
- On read / post / serve start / `okstratr bb prune`: drop live entries older
  than duration and **rewrite** `blackboard.jsonl`.
- **There is no `durable_agents` flag.** Longer boarding = longer duration.

### 2. `duration = 0` ⇒ ephemeral

- CoS / agent posts clear **as soon as possible** (prune on post/read,
  desk quiet/stop/dismiss, serve start).
- Hard max age for **all** entries: **60 minutes** (never retain >60m).
- TUI chip: `bb: ephemeral(≤60m)` vs `bb: 3d`.

### 3. Clear = hard wipe, no archives

- `bb clear` / `/bb clear` hard-wipes the live board.
- No archives by default (`OKSTRATR_BB_ARCHIVE_ON_CLEAR=0`).
- Legacy `blackboard.jsonl.archive.*` cleaned on clear/prune/Mac apply.

### 4. Invisible filename writes impossible

- `workspace.assert_visible_name(name) -> ok|error`.
- Reject leading `.`, trailing spaces/dots, Unicode Cf / bidi / RTLO.
- Hooked into `resolve_in_sandbox` + harness_logs naming
  (`investigator-grok-<ts>.log` style).

### 5. Tamper-evident ops audit (metadata only)

- `ops_audit.py` → append-only `state/ops_audit.jsonl`.
- Hash chain: `hash = sha256(prev_hash + canonical_json(body))`.
- Never file contents or prompts.
- `okstratr audit tail|head|verify`; `/audit`; `GET /api/audit?n=`.
- `bb clear` does **not** wipe the audit log.

## Commands

```text
okstratr config set blackboard.duration 7     # longer boarding
okstratr bb duration 0                        # ephemeral (≤60m, agents ASAP)
okstratr bb duration 3d
okstratr bb prune
okstratr bb clear                             # hard wipe; no archive
okstratr audit verify && okstratr audit tail
```
