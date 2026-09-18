# ADR-004: Hosted observer, reverse-proxy embed, registry SSOT

- **Status:** Accepted (Phase 1a)
- **Date:** 2026-09-18
- **Deciders:** Ben / skill-shell rationalization charter
- **Charter refs:** locked decisions #1 (no iframes), #5 (registry SSOT), #6 (hosted settings off)

## Context

Switchbay and okbay install okstratr as a desk kernel and need to show the
observer (desks / DAG / blackboard) inside their shells **without** nesting
iframes. Shells own settings chrome; okstratr HTML must not compete when hosted.
Harness/model allowlists must live in one place so rail UIs do not invent a
second allowlist.

## Decision

1. **No iframes.** Switchbay/okbay daemons **same-origin reverse-proxy**
   okstratr (`127.0.0.1:8767`) under a configurable public base path
   (env `OKSTRATR_PUBLIC_BASE`, typical value `/embed/okstratr`). CE uses the
   sibling prefix `/embed/ce/`. In-app panels load first-party proxied routes.

2. **Public base path.** The kernel accepts requests both at `/…` and at
   `{OKSTRATR_PUBLIC_BASE}/…` by stripping the prefix before routing. The
   observer injects `window.OKSTRATR_API` / `OKSTRATR_PUBLIC_BASE` so `fetch`
   and asset-relative calls work under the embed prefix.

3. **Hosted mode.** When `X-Okstratr-Host: switchbay|okbay` **or**
   `?host=switchbay|okbay`, the HTML observer **hides/disables** the settings
   strip (config / web egress controls). Desks, AGENT SPACE (DAG), and
   blackboard remain. Shells write harness/model config through the API.

4. **Registry SSOT.** `okstratr.harness.registry` + `harnesses.toml` +
   `GET/POST /api/harness*` are the single allowlist for harnesses and models
   (including `switchbay-rail`, Pi, provider CLIs). Switchbay rail UI and okbay
   settings **configure** this registry; they do not maintain a parallel one.

## Consequences

- Proxy must forward `X-Okstratr-Host` (or append `?host=`) when embedding.
- Bare / Mac installs omit the header and query → full settings chrome.
- Phase 4 Switchbay / Phase 5 okbay wire the reverse proxy; this ADR is the
  okstratr contract they implement against.
- Textual TUI stays removed (charter #8); observer-only console.

## Verify

```bash
# Hosted settings off (query)
curl -s 'http://127.0.0.1:8767/observer/?host=switchbay' | grep -E 'OKSTRATR_HOSTED|hosted'
# or header
curl -s -H 'X-Okstratr-Host: okbay' 'http://127.0.0.1:8767/observer/' | grep OKSTRATR_HOSTED

# Proxy prefix
OKSTRATR_PUBLIC_BASE=/embed/okstratr okstratr serve
curl -s 'http://127.0.0.1:8767/embed/okstratr/health'
curl -s 'http://127.0.0.1:8767/embed/okstratr/observer/' | grep OKSTRATR_PUBLIC_BASE

# Registry API (shells configure okstratr)
curl -s http://127.0.0.1:8767/api/harness | jq '.harnesses[].id'
```

## Follow-on (Phase 1b)

Desk-dashboard **stats and groupings** (tokens, working/idle, files/lines, by-kind /
by-state, Quiet all, schedule badge) live on the observer and remain visible in
hosted mode. Inventory + remaining gaps:
[`MIGRATION-AGENT-DASHBOARD.md`](./MIGRATION-AGENT-DASHBOARD.md). No chat bar.

