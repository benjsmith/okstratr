# Cleanup — kept vs legacy surfaces

Product shape after three iterations (Omarchy plugin → CLI → skill + observer).
Authoritative product lock: [ADR-003](ADR-003-skill-observer-vs-kernel.md).
Harness seating history: [ADR-001](ADR-001-cli-tui-harness.md).
Package map: [ARCHITECTURE.md](ARCHITECTURE.md#kept-vs-legacy-surfaces).

## Kept (core)

- Kernel daemon + HTTP API (`okstratr serve` / `start` on `:8767`)
- In-harness skill (`skills/okstratr/SKILL.md`)
- **Observer panel** (`src/okstratr/observer/`) — primary visual console
- CLI lifecycle + desk/DAG/blackboard/harness commands
- Herdr bridge + direct CLI seating

## Kept (optional / guest)

- Omarchy QML: `Panel.qml`, `DeskRail.qml`, `BarWidget.qml`, `Service.qml`, `Model.js`
  — thin client / native twin; **do not delete** while Omarchy guest may load them
- `contrib/setup.sh`, `contrib/guest-apply-main.sh`, hypr/menu snippets

## Legacy / deprecated

  (prefer observer panel)
- **`okstratr seat`** and **`POST /api/seat`** — deprecated aliases for
  `desk start auto`

## Removed in this cleanup

- One-shot `contrib/guest-apply-phase*.sh` and other superseded
  `guest-apply-*` scripts (kept only `guest-apply-main.sh`)

## Explicit non-deletes

Do **not** remove Panel.qml / DeskRail / BarWidget in cleanup PRs — too risky
for the Omarchy guest. Document primacy of the observer instead.
