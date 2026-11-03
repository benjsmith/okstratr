# Changelog

## Unreleased

- **Effort now picks the orchestration shape for `/auto`.** It chooses
  between a single worker and several investigators from the effort slider
  and the task, within the hire cap. Trivial tasks no longer fan out just
  because several harnesses are installed.
- **`/work` hires specialists in sequence:** gather context → write (plan,
  update or deliverable, from the brief) → review. The old template is the
  fallback.
- **The verifier / review gets the strongest allowed model.** Authors get
  the strongest model too until okstratr has seen how a cheaper model does on
  that task class. It then picks the model with the best expected utility,
  counting P(fail | model, class), the rework a failure costs and the extra
  tokens a failing model spins. Outcomes are kept in
  `state/model_routing.json`.
- **Per-workspace model allow/deny list:** `okstratr model allow|deny|unlist
  KEY [--ws ID]`, `okstratr model policy|reset`, `/api/models/policy`.
- **Run folders** (`state/runs/<id>/`) follow the blackboard duration
  (default 3 days; duration 0 keeps them at most 60 minutes) and `bb clear`
  removes them.
- **Retired node ids are never reused** until the DAG is reset (stored as
  `archived_ids` in `dag.json`, written only when non-empty).
- **Findings are verified before the answer.** Seats file results with
  `okstratr findings add` (a per-node file plus a blackboard post), so plan
  growth after a verifier, the `OBJECTIVE_MET` stop and reducer evidence work
  on Herdr desks, Switchbay without Herdr and the plain CLI. okstratr never
  reads pane text.
- **Host done:** okstratr reads each harness's stop rule (`okstratr
  host-profile`; `done = "…"` in harnesses.toml or `OKSTRATR_HOST_DONE`). It
  respects a rule at least as strong as its own and otherwise adds seats or a
  verify round within budget. Each override is logged in
  `runs/<id>/decisions.jsonl` and on the blackboard.
- **`okstratr run` and `okstratr loop`** run an objective outside a desk,
  through the direct adapter or a file queue (`okstratr queue
  list|show|claim|done`). `loop --for 2h --budget-tokens N` checkpoints each
  round and records why it stopped.
- **A finished Herdr job no longer reports `desk.done`** unless the desk has
  no seats left. Otherwise it sends `desk.progress`. `schedule.failed` is only
  sent for scheduled desks.
- **Seat timeout raised from 15 to 30 minutes** (`WORKER_TIMEOUT_SEC` 900 → 1800)
  so a seat can be a full agent session.
- **Learned shapes per desk and task type** are stored in a new `recipes`
  section of `bandit.json`. Existing `bandit.json` and `dag.json` files load
  unchanged; older okstratr versions ignore the new section.
- **Seats no longer inherit provider API keys.** `XAI_API_KEY`,
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and similar keys are removed from
  direct and Herdr seat environments, so seats use subscription logins.
  **Behaviour change:** a seat (for example pi) that relied on
  `OPENAI_API_KEY` now fails unless `OKSTRATR_SEAT_API_KEYS=allow` is set.
- **A failed seat is re-seated once on a healthy harness** (`<id>-retry`),
  and its dependents wait for the retry. A retry is never retried.
- **The old template shape (`parallel_diverse_k`) is always a candidate**
  when two or more harnesses are installed, and the decision says why it lost
  or tied. Code tasks are never treated as simple and get a `tools_verify`
  candidate.
- **A second expansion wave is only hired if it is likely to help:** the
  expected gain is discounted by P(close gap), learned from earlier waves,
  and expansion stops after a wave that found nothing new.
- **The learner leaves the prior shape only on clear evidence:** an arm must
  beat the prior by more than its standard error.
- **Offline benchmark:** `python3 -m okstratr.orchestration_bench` compares
  the chosen shape with a single worker and the old fixed template on fake
  harnesses. `--seeds N` reports mean ± SE and paired win/tie/loss,
  `--calibrate` learns on training seeds and reports prior vs realized on
  held-out seeds, and `--routing` compares cheap and strong author models.
  The fake verifier is not an oracle: it misses some false claims.

## v0.2.1 — 2026-10-13

**Migration:** none. **Breaking:** the observer and panel no longer have desk
or workspace dropdowns.

- **Context is read-only.** Pick a desk by clicking its card in the left rail.
  The workspace shown is the one the host has open: Switchbay's or okbay's
  active workspace, or on the bare CLI the workspace chosen with
  `POST /api/workspace/select`, `--workspace` / `OKSTRATR_WORKSPACE`, or the
  registered workspace containing the current directory.
- **Desk and label always agree.** The workspace a desk binds to follows the
  same rule as the Context label, so an old saved selection no longer
  overrides the host's active workspace.
- **New `okstratr --workspace`** option and a `ws` line in `okstratr status`.
- **Default workspace is now `work` (all of `~/Work`)** instead of `local`
  (the directory `okstratr serve` was started in) when nothing else applies.

## v0.2.0 — 2026-09-29

First meaningful minor after the skill + observer product lock. **Migration:**
none. **Breaking:** none for bare CLI / skill installs. Hosted shells
(Switchbay) must set `OKSTRATR_PUBLIC_BASE` / hosted headers as below.

### Added / locked (product shape)

- **Skill + observer panel:** in-harness skill ships the kernel +
  HTML **observer** (`/observer/`, `/panel/`). Observer is the **primary
  visual console** — standing desks rail, AGENT SPACE canvas, blackboard,
  workspace switcher, Desk Prompt / CoS conversation, schedule dialog.
  **No chat / objective query bar** in the observer (text I/O stays in
  Herdr / CLI harnesses).
- **Hosted proxy contract:** `OKSTRATR_PUBLIC_BASE` (typical
  `/embed/okstratr`); strip prefix before routing; inject
  `window.OKSTRATR_PUBLIC_BASE` / `OKSTRATR_API`. Hosted mode via
  `X-Okstratr-Host: switchbay|okbay` or `?host=` hides HTML settings strip.
- **Registry SSOT:** `okstratr.harness.registry` + `harnesses.toml` +
  `GET/POST /api/harness*` — shells are config UIs over this allowlist, not
  a second copy (Switchbay Settings thin client).
- **host_notify:** path-native envelopes for schedule fire /
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
  prefer observer. Query bar removed from Panel.
- TUI removed earlier; observer-only console.
- Deep Switchbay parity: Switchbay 0.13.0 (core-skills auto-start) consumes
  this contract. Residual gaps (live Herdr focus sync, etc.) stay listed as
  non-goals / stubs.

### Version bumps

- `pyproject.toml` + `src/okstratr/__init__.py`: **0.1.0 → 0.2.0**

