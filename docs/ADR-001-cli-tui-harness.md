# ADR-001: CLI harness-agnostic seating (observer supersedes any desk TUI)

- **Status:** Accepted (Phase 1–4) · Vision complete for ADR-001 scope
- **Date:** 2026-09-17
- **Deciders:** Ben / okstratr

## Context

okstratr began as an Omarchy desk panel paired with a **grok-only** Herdr
`--kind` (`DEFAULT_KIND = "grok"`). The product vision is broader:

1. **okstratr = CLI-first desk brain** (Herdr-shaped observability).
2. The Omarchy plugin becomes a **thin client** of the same local daemon.
3. Seating must be **harness- and model-agnostic** — orchestrate seats across
   any CLI harness the user has (claude, grok, pi, codex, omp, opencode,
   cursor, …), aligned with Herdr `--kind` values where possible.
4. Config (Switchbay-inspired, **no LiteLLM**) controls which harnesses +
   models + settings may be fanned out.
5. On Mac (no Omarchy): `okstratr start` + **observer panel** is the primary
   unchanged. (Superseded UI primacy: ADR-003.)
6. Herdr remains the multiplexer when present; a **direct CLI adapter**
   (subprocess without Herdr) is required for environments without Herdr.

Switchbay patterns consulted read-only (not vendored): fanout plan/workers,
llmgateway provider registry, routing_status provider+model effort.

## Decision

### Boundaries

| Piece | Owns |
|-------|------|
| **okstratr** | Desk brain: kernel, desks, DAG, CoS, blackboard, schedule, **harness registry + config**, seating policy, CLI, HTTP daemon |
| **Herdr** | Multiplexer / runtime when present: panes, agent lifecycle, `--kind` seating |
| **okbay** | Knowledge / Atlas / work-coverage ingest (unchanged) |
| **Omarchy Panel** | **Client** of okstratr daemon (Phase 1: keep Panel; document path to thin client) |

### Harness registry

**SSOT for shells:** Switchbay/okbay settings configure this registry via `/api/harness*` (including `switchbay-rail`); no parallel allowlist. See [ADR-004](ADR-004-hosted-proxy-registry.md).

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

### CLI + observer

- `okstratr harness list|detect|enable|disable`
- `okstratr config show|set …`
  plain fallback; talks to `http://127.0.0.1:8767` (same API as observer/Panel).
  Primary visual is the HTML **observer panel** (ADR-003), not a separate desk TUI (removed).
- `okstratr agents` — desk/thread filtered agent list stub

### Observability

Every seat still carries **desk_id + thread_id** labels for Herdr grouping.
Mac workflow (primary — see ADR-003):

```text
okstratr start --yes              # daemon + observer :8767
open http://127.0.0.1:8767/observer/   # primary visual console
# herdr          # multiplexer (optional)
```

**No Herdr on Mac?** Point seating at the direct CLI adapter (uses `grok` etc.):

```bash
okstratr config set backend direct
# optional: grok-4.6 + low reasoning
okstratr config set harness.grok.default_model grok-4.6
okstratr config set harness.grok.settings.reasoning low
# restart serve, then Start / drive_herdr drives *seats* via harness.direct
```

Desks appear grouped by labels; `okstratr agents --desk …` lists them.
`GET /api/dag` (and observer DAG) load the focused desk's `desks/<id>/dag.json`.

### Omarchy

Do **not** rip Panel in Phase 1. Panel remains a client of the same HTTP
API. Config UI may read/write `harnesses.toml` later; docs note the path.

## Consequences

- Seating is no longer hardcoded grok-only.
- Users must enable + install harnesses they want fan-out across.
- Clear error when no enabled harness is installed.
  without it.
- Tests use `OKSTRATR_STATE_DIR` + `OKSTRATR_CONFIG_DIR` + dry-run.

## Later phases

- **P2:** real direct-CLI adapters; model rungs / effort;
  agents groupings; Panel Config path stub
- **P3 (this PR):** thin Omarchy plugin (Panel pure client); DeskSession module;
  fuller QML harness editor via `/api/harness*`
- **P4 residual:** DeskSession full SSOT — drop FileView dual-read/write where
  safe; migrate any remaining desk brief channels onto `desk_session` only

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
  argv templates + detect (`grok` uses positional prompt, not `--prompt`); stdout/stderr → `state/harness_logs/`; PID registry;
  kill on desk stop/dismiss/quiet.
- `harnesses.toml`: per-harness `default_model`, `effort` rung map
  (trivial|normal|hard); `okstratr config set harness.claude.default_model …`;
  `okstratr model list`; `/model claude:sonnet` + `/rung` wired into select.
- ~~removed TUI~~ was: desk tabs with Running/Idle badges, DAG topo+status, blackboard head,
  slash help, optional `/api/status` poll; `--snapshot` unchanged for CI.
- `okstratr agents` groups by `desk_id`/`thread_id` (Herdr list + desks);
  same label keys on Herdr + direct paths; label convention documented.
- Panel Config: harnesses.toml path + CLI reload hints (no full QML editor).
- Out of scope at P2: Panel rewrite / DeskSession SSOT (delivered in P3/P4).

### Phase 3

- **DeskSession** module (`okstratr.desk_session`): single logical view of
  standing desks + DAG summary + objective + Herdr/direct seat refs.
  Embedded in `GET /api/status` as `desk_session` (+ top-level `desks` /
  `standing` aliases). Also `GET /api/desk_session`.
- **Harness HTTP API**: `GET /api/harness`, `POST /api/harness/enable|disable|
  reload|set` — persists `harnesses.toml` via existing harness.config helpers.
  Status snapshot includes `harness` allowlist rows (default_model + effort).
- **Panel**: Config harness editor lists enable toggles, default_model, effort
  rungs; Reload button; Start/focus/dismiss UX unchanged (still `/api/desk/*`).
  Prefers `GET /api/status` while open; FileView `status.json` marked compat.
- ~~removed TUI~~ was: `desk_rows()` prefers `desk_session` when present.
- **Status channel hygiene**: `status_channel` documents primary HTTP vs
  FileView dual-source; P4 drops remaining dual-write.
- Tests: unit DeskSession + harness API; e2e harness toggle via HTTP.
  Pytest green (142).

### Phase 4 (complete)

- **DeskSession full SSOT**: Panel, CLI, observer, BarWidget, and Service prefer
  `desk_session` from `GET /api/status` / `GET /api/desk_session`.
- **status.json**: daemon write-through **compat mirror** only
  (`status_channel.dual_source=false`, `mirror=true`). Clients must not treat
  FileView as authoritative when HTTP is up. Panel sets `httpLive` and ignores
  FileView overwrites while open+live; BarWidget/Service HTTP-poll first,
  FileView last-resort offline.
- **ConfigHarnessEditor.qml**: extracted harness allowlist editor; richer
  per-harness model field + quick picks → `POST /api/harness/set`
  (`harness.<id>.default_model`).
- **Tests**: status channel primary=http; FileView mirror matches desk_session;
  Panel/Model helper contracts; harness set e2e. Pytest green.
- **ADR-001 vision**: complete for stated scope (CLI-first desk brain +
  harness-agnostic seating + thin Omarchy client).

### Residual hygiene (honest, out of ADR-001 scope)

- Live QML verification on Omarchy guest (`contrib/guest-apply-main.sh`).
- Further Panel.qml size reductions (DeskRail.qml extracted; query bar still inlined).
- **status.json write-through mirror kept** for offline bar chips. Opt out with
  `OKSTRATR_STATUS_MIRROR=0` (skips disk write; HTTP SSOT unchanged). Eventual
  removal still TBD once all bar hosts are HTTP-only.
- Workspace sandbox (`okstratr cd`  / `/cd`): seats chdir into operating dir;
  path escapes rejected — see `okstratr.workspace` policy string.
- Web egress remains deny-by-default (`web_egress`); `/web` via slash + observer/web API.
- No LiteLLM / no Cloud Agents (unchanged boundary).

### Smoke: desk-file DAG + direct backend

- `GET /api/dag` loads focused/active desk `desks/<id>/dag.json` (CoS graph);
  response `nodes` is a **list** (clients receive list nodes when count>0).
- `drive_herdr` / `drive_seats` means drive seats; with `backend=direct` never
  starts Herdr panes (even if a broken `herdr` shim is on PATH).
- Mac without Herdr: `okstratr config set backend direct`.

### Product-shape cleanup (2026-09-18)

- Omarchy Panel remains optional thin client (not deleted).
- See `docs/CLEANUP.md` and ADR-003.


## Status note (2026-09-18)

The Textual `okstratr tui` surface was **removed**. Observer panel + lifecycle CLI are the only console path. This ADR remains for harness registry / seating history.
