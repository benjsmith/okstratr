# ADR-003: Skill + observer panel vs desk kernel

- **Status:** Accepted
- **Date:** 2026-09-18
- **Deciders:** Ben / okstratr

## Context

okstratr is a desk-brain kernel (serve on `:8767`) plus seating into Herdr /
direct CLI harnesses. Users need a low-friction way to bring the kernel up
from inside a harness without inventing a second chat surface, and Omarchy
needs a visual desks/DAG control surface.

## Decision

1. **Ship okstratr as an in-harness skill** that points at the server module
   and the **observer panel** static assets (`okstratr/observer/`).
2. **Text I/O stays in Herdr / other CLI harnesses.** The observer panel is a
   CE-style interactive HTML control surface (desks / DAG / buttons /
   settings chips) — **not** a second chat.
3. **Consent-first lifecycle** via `okstratr.lifecycle`:
   `start | restart | shutdown | status | ensure_running(prompt=True) | doctor`.
   Skill path must prompt before daemonizing; CLI `--yes` skips for automation.
4. **Slash:** `/okstratr start|restart|shutdown|status` in harness/TUI.
5. **URLs:** observer panel at `/observer/` on the kernel server (alias
   `/panel/` optional). Dedicated `:8768` host is optional fallback.

## Consequences

- Kernel remains the SSOT for desks/DAG/blackboard/API.
- Skill + CLI share one lifecycle module and pidfile under the state dir.
- Omarchy displays the observer panel; Herdr keeps the conversation.

## Observer panel layout (2026-09-18)

The `/observer/` static UI mirrors Omarchy **Panel.qml + DeskRail.qml**:

1. **Top bar** — brand, chips (bb duration, web, harness, Running/Idle), Refresh.
2. **Left rail (~280px)** — standing desks (work/curate/code/deck/auto) with
   Start/Continue, Stop, Dismiss/Delete posting to `/api/desk/*`.
3. **Main** — objective query + Start (`drive_herdr`), cwd chip, **topo DAG**
   columns (depth / tier from `depends_on` or graph tiers) via `/api/dag?desk_id=`,
   blackboard head + Clear (`/api/blackboard/clear`).
4. **Right strip** — config summary + optional web Off/Once/Session.

Dark blue/black Omarchy theme; poll ~3s; **not** a chat surface. Name remains
**observer panel** (not Butter). Routes: `/observer/` and `/panel/`.
