# ADR-001: CLI/TUI-first desk brain + harness-agnostic seating

- **Status:** Accepted (Phase 1) · Phase 2 in progress
- **Date:** 2026-09-17
- **Deciders:** Ben / okstratr

## Context

okstratr began as an Omarchy desk panel paired with a **grok-only** Herdr
`--kind` (`DEFAULT_KIND = "grok"`). The product vision is broader:

1. **okstratr = CLI/TUI-first desk brain** (Herdr-shaped observability).
2. The Omarchy plugin becomes a **thin client** of the same local daemon.
3. Seating must be **harness- and model-agnostic** — orchestrate seats across
   any CLI harness the user has (claude, grok, pi, codex, omp, opencode,
   cursor, …), aligned with Herdr `--kind` values where possible.
4. Config (Switchbay-inspired, **no LiteLLM**) controls which harnesses +
   models + settings may be fanned out.
5. On Mac (no Omarchy): `herdr` + `okstratr serve` + `okstratr tui` should
   give the same desk/thread grouping labels as today.
6. Herdr remains the multiplexer when present; a **direct CLI adapter**
   (subprocess without Herdr) is required for environments without Herdr.

Switchbay patterns consulted read-only (not vendored): fanout plan/workers,
llmgateway provider registry, routing_status provider+model effort.

## Decision

### Boundaries

| Piece | Owns |
|-------|------|
| **okstratr** | Desk brain: kernel, desks, DAG, CoS, blackboard, schedule, **harness registry + config**, seating policy, CLI/TUI, HTTP daemon |
| **Herdr** | Multiplexer / runtime when present: panes, agent lifecycle, `--kind` seating |
| **okbay** | Knowledge / Atlas / work-coverage ingest (unchanged) |
| **Omarchy Panel** | **Client** of okstratr daemon (Phase 1: keep Panel; document path to thin client) |

### Harness registry

Package: `okstratr.harness`

- Built-in defs: id, `herdr_kind`, bin names, `detect_installed()`
- Config file: `~/.config/okstratr/harnesses.toml` (override via
  `OKSTRATR_CONFIG_DIR` / `OKSTRATR_HARNESSES_TOML`)
- Allowlist (`enabled`), preference order, per-harness model pools,
  optional per-role harness map
- Selection (P1): preference order / round-robin among enabled∩installed,
  falling back to enabled-only for **Herdr** seating (Herdr can run `--kind`
  without a standalone CLI on PATH); strict install required for **direct**
  adapter. `OKSTRATR_HERDR_KIND` remains a hard override
- Slash directives: `/harness grok,claude` `/model …` (parse helpers +
  start-path env wiring)

Migration from grok-only `DEFAULT_KIND`: `DEFAULT_KIND` remains the
historical fallback string; live/dry seating resolves kind via the
registry. Default allowlist still starts with `grok` so existing users
are unchanged until they `harness enable` others.

### Adapters

| Adapter | Phase 1 |
|---------|---------|
| **Herdr multi-kind** | Implemented — seating uses registry `herdr_kind` |
| **Direct CLI** | Real subprocess adapter (`harness.direct`) + dry-run; PID track/kill on quiet |

### CLI / TUI

- `okstratr harness list|detect|enable|disable`
- `okstratr config show|set …`
- `okstratr tui` — minimal Textual UI (optional extra `[tui]`); `--snapshot`
  plain fallback; talks to `http://127.0.0.1:8767` (same as Panel)
- `okstratr agents` — desk/thread filtered agent list stub

### Observability

Every seat still carries **desk_id + thread_id** labels for Herdr grouping.
Mac workflow:

```text
herdr          # multiplexer
okstratr serve # daemon :8767
okstratr tui   # desk brain UI
```

Desks appear grouped by labels; `okstratr agents --desk …` lists them.

### Omarchy

Do **not** rip Panel in Phase 1. Panel remains a client of the same HTTP
API. Config UI may read/write `harnesses.toml` later; docs note the path.

## Consequences

- Seating is no longer hardcoded grok-only.
- Users must enable + install harnesses they want fan-out across.
- Clear error when no enabled harness is installed.
- TUI depends on optional `textual` for interactive mode; snapshot works
  without it.
- Tests use `OKSTRATR_STATE_DIR` + `OKSTRATR_CONFIG_DIR` + dry-run.

## Later phases

- **P2 (this PR):** richer TUI; real direct-CLI adapters; model rungs / effort;
  agents groupings; Panel Config path stub
- **P3:** thin Omarchy plugin (Panel pure client); DeskSession path; fuller
  QML harness editor
- **P4:** DeskSession single source of truth

## References

- `src/okstratr/harness/`
- `docs/DESK-KERNEL.md`, `docs/ARCHITECTURE.md`
- Switchbay (inspiration only): `agents/fanout.py`, `llmgateway/`, `routing_status.py`

## Omarchy Panel note (Phase 1)

Panel.qml is **not** removed. It remains a client of `http://127.0.0.1:8767`.

Harness allowlist file (read/write from a future Config section):

- `~/.config/okstratr/harnesses.toml`
- Overrides: `OKSTRATR_CONFIG_DIR`, `OKSTRATR_HARNESSES_TOML`

CLI today: `okstratr harness list|enable|disable`, `okstratr config show|set`.

## Changelog

### Phase 2

- Direct CLI adapter spawns real harness processes (`claude`/`codex`/`grok`/…);
  argv templates + detect; stdout/stderr → `state/harness_logs/`; PID registry;
  kill on desk stop/dismiss/quiet.
- `harnesses.toml`: per-harness `default_model`, `effort` rung map
  (trivial|normal|hard); `okstratr config set harness.claude.default_model …`;
  `okstratr model list`; `/model claude:sonnet` + `/rung` wired into select.
- TUI: desk tabs with Running/Idle badges, DAG topo+status, blackboard head,
  slash help, optional `/api/status` poll; `--snapshot` unchanged for CI.
- `okstratr agents` groups by `desk_id`/`thread_id` (Herdr list + desks);
  same label keys on Herdr + direct paths; label convention documented.
- Panel Config: harnesses.toml path + CLI reload hints (no full QML editor).
- Out of scope remains P3+ Panel rewrite / DeskSession SSOT.
