# Changelog

## v0.2.0 — 2026-09-29

First meaningful minor after the skill + observer product lock. **Migration:**
none. **Breaking:** none for bare CLI / skill installs. Hosted shells
(Switchbay) must set `OKSTRATR_PUBLIC_BASE` / hosted headers as below.

Do **not** tag from the docs PR alone — Ben cuts the tag after merge.

### Added / locked (product shape)

- **Skill + observer panel (ADR-003):** in-harness skill ships the kernel +
  HTML **observer** (`/observer/`, `/panel/`). Observer is the **primary
  visual console** — standing desks rail, AGENT SPACE canvas, blackboard,
  workspace switcher, Desk Prompt / CoS conversation, schedule dialog.
  **No chat / objective query bar** in the observer (text I/O stays in
  Herdr / CLI harnesses).
- **Hosted proxy contract (ADR-004):** `OKSTRATR_PUBLIC_BASE` (typical
  `/embed/okstratr`); strip prefix before routing; inject
  `window.OKSTRATR_PUBLIC_BASE` / `OKSTRATR_API`. Hosted mode via
  `X-Okstratr-Host: switchbay|okbay` or `?host=` hides HTML settings strip.
- **Registry SSOT:** `okstratr.harness.registry` + `harnesses.toml` +
  `GET/POST /api/harness*` — shells are config UIs over this allowlist, not
  a second copy (Switchbay Settings thin client — SB ADR-005).
- **host_notify (ADR-005):** path-native envelopes for schedule fire /
  health; hosted POST to shell callback (Switchbay
  `/api/okstratr/host-notify`); bare → harness-visible stderr (or JSON lines).
- **Health block** on `okstratr status` / `GET /api/status`: `ce`, `okstratr`,
  `wiki_build`.
- **Bare CLI first-class:** `okstratr start|restart|status|shutdown` + desk /
  dag / bb / herdr / serve / observer. `contrib/setup.sh` installs CLI onto
  `~/.local/bin` (required for Switchbay Agents supervisor PATH); skill install
  into agent skill dirs.
- **Observer desk UX:** sticky desk focus across poll / soft remount; quiet
  desks at rest; Switchbay CoS empty-state copy strips Herdr flicker; Open in
  Herdr seats on workspace dirs; Pi harness slash model fixes.

### Clarified

- Omarchy **Panel.qml** remains an optional native twin / thin client (guest);
  prefer observer. Query bar removed from Panel per ADR-003.
- TUI removed earlier; observer-only console.
- Deep Switchbay parity check is **no longer “release pending”** — Switchbay
  Phase 4a/Embed v2 + core-skills auto-start consume this contract (see SB
  v0.13.0). Residual gaps (live Herdr focus sync, etc.) stay listed as
  non-goals / stubs, not as a blocked release.

### Version bumps

- `pyproject.toml` + `src/okstratr/__init__.py`: **0.1.0 → 0.2.0**

