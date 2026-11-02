# Live evaluation with real seats

This is a design and runbook. It has not been run yet.

The offline benchmark (`python3 -m okstratr.orchestration_bench`) uses fake
harnesses. This evaluation runs real agents as seats, so it shows whether
the shape okstratr picks beats a single worker on real tasks. It compares:

- **utility**: `okstratr run` with no `--recipe` (okstratr picks the shape);
- **single**: `okstratr run --recipe single` (one worker, the baseline);
- optional **template**: `okstratr run --recipe parallel_diverse_k` (the old
  fixed shape).

Metrics, each reported as utility minus single (and minus template if run):

- quality, scored blind against gold written before any run;
- tokens, from `okstratr queue done --tokens` (or okstratr's estimate);
- wall time, from the start of `okstratr run` to its exit.

## Tasks

| Task | Folder | What it tests | How it is scored |
|---|---|---|---|
| code | `code/` | A change across three modules of a small Python package (parsing, CSV, CLI flag). | Hidden tests (`gold/hidden_tests`, 21 tests), plus the task's own tests. Score = hidden tests passed / 21. |
| synth | `synth/` | A current-state brief from six project documents with six planted conflicts, one unresolved conflict and three false alarms. | Blind judge against `gold/answer-key.md`, 0–20. |
| research | `research/` | Four questions over a 13-file local corpus. Each needs a join across files and has a trap. | Blind judge against `gold/answer-key.md`, 0–20. |

Each folder has `input/` (what the seats see, with `TASK.md`) and `gold/`
(what only the scorer sees). The code task's gold includes a reference
`solution.patch`; with it applied all 21 hidden tests pass, and on the
unchanged input 9 fail.

### Where the gold lives

The tasks and gold are in the bot's store, not in this repo:

```
/cursor/stores/store-5ea5ea64-8b4f-46a7-a4ee-4da57ee5326f/okstratr-live-eval/
```

The repo holds only the SHA-256 manifest of every file there,
[`live-eval-gold.sha256`](live-eval-gold.sha256). Check it before a run and
again before scoring:

```bash
cd /cursor/stores/store-5ea5ea64-8b4f-46a7-a4ee-4da57ee5326f/okstratr-live-eval
sha256sum -c /path/to/okstratr/docs/live-eval-gold.sha256
```

If a check fails, the gold changed after it was frozen; do not score.

## How seats run

Seats run through the file-queue adapter. okstratr writes each ready seat to
`state/queue/<run>/<node>.prompt.md` and waits. A parent agent dispatches
one fresh subagent per seat. The seat files its result with
`okstratr findings add`; the parent then signals done. okstratr never reads
a seat's transcript.

```
okstratr run --adapter queue          parent agent                    seat subagent
-------------------------------       -----------------------------   --------------------------
queues inv-0, inv-1 …         ──►     queue list --state queued
                                      queue claim R inv-0
                                      dispatch subagent(prompt)  ──►  works in the run's copy
                                                                      okstratr findings add …
                                      queue done R inv-0 --tokens N ◄─ returns
queues verify, then synth …   ──►     (repeat)
exits with the answer
```

## Setup (once per run)

Use the PR branch and a separate state folder so nothing touches a live
okstratr:

```bash
cd /workspace/okstratr-orch
export PYTHONPATH=src
export OKSTRATR_STATE_DIR=/workspace/live-eval/state
OK="python3 -m okstratr"
G=/cursor/stores/store-5ea5ea64-8b4f-46a7-a4ee-4da57ee5326f/okstratr-live-eval
```

- Do not start the okstratr server; `okstratr run` does not need it. Leave
  ports 8765–8767 and 8775–8777 alone.
- No API keys. Seats run as subagents; okstratr makes no model calls.
- Give every run its own copy of the input:
  `cp -r $G/<task>/input /workspace/live-eval/work/<run-id>`.
  Seats never see `$G`.
- Harness labels: all seats are the same agent, so run with one harness
  label (`--harness grok`). Diversity between seats is then only in the
  prompts, not the model. With one harness okstratr picks `tools_verify` for
  code and `single_verify` for synth and research. See "Limits" below.

## Runbook (per task, per repetition)

Run IDs: `<task>-<approach>-<rep>`, for example `synth-utility-1`.
Alternate which approach goes first between repetitions.

1. Check the manifest (above).
2. Copy the input to `/workspace/live-eval/work/<run-id>`.
3. Start the run in the background and note the start time:

   ```bash
   OBJ="Work in /workspace/live-eval/work/<run-id>. Follow TASK.md there."
   $OK run "$OBJ" --adapter queue --harness grok --run-id <run-id> --no-learn \
       [--recipe single] --seat-timeout 1800 > /workspace/live-eval/<run-id>.out &
   ```

   `--no-learn` keeps one run from steering the next. Leave `--recipe` off
   for utility.
4. Loop until the run exits:
   - `$OK queue list --run <run-id> --state queued`
   - for each queued seat: `$OK queue claim <run-id> <node>`, then dispatch
     one fresh subagent with the seat instructions below and the text of
     `$OK queue show <run-id> <node>`. Seats in the same wave can be
     dispatched in parallel.
   - when the subagent returns: `$OK queue done <run-id> <node> --tokens N`
     (N from the dispatch tool if it reports usage; otherwise leave out
     `--tokens` and okstratr estimates from text sizes, the same way for
     every approach). Use `--failed --error "…"` if the subagent errored or
     filed nothing.
5. Record the end time. Save the final answer
   (`$OK findings show --run <run-id> --node synth`; for `--recipe single`
   the only node is `main`) and, for the code task, the work folder.
6. Do not look at the gold until every run of that task is finished.

### Seat instructions (prepend to every seat prompt)

```
You are one seat in an okstratr run. Do only what the prompt below asks.
- Work only in /workspace/live-eval/work/<run-id>. Do not read any other
  folder under /workspace/live-eval or any /cursor/stores path.
- Do not use the web. Use only the files in the work folder.
- When you are done, file your result with the exact `okstratr findings add`
  command in the prompt (use --file for long JSON). Run it with
  PYTHONPATH=/workspace/okstratr-orch/src OKSTRATR_STATE_DIR=/workspace/live-eval/state
  python3 -m okstratr findings add …
- Then reply with one line: "filed" or "failed: <reason>".
```

For code seats, add: "Run `python3 -m pytest -q` in the work folder and
report the result as a check."

## Scoring

- **code**: copy `$G/code/gold/hidden_tests` into the run's work folder and
  run `python3 -m pytest -q tests hidden_tests`. Score = hidden passed / 21.
  No judge needed.
- **synth, research**: blind judging.
  1. Collect the final answers for one task and repetition, remove run IDs,
     node names and anything that reveals the approach, and label them A, B
     (C) in random order. Keep the key in a file the judge does not see.
  2. Dispatch one fresh judge subagent per task and repetition with the
     answer key, the scoring rubric in it, and the anonymised answers. The
     judge returns a score per answer and one line per point lost.
  3. Unblind after all scores are in.

Quality for U is score / max (0–1). Report U = Q − λc·C − λl·L with the same
λ values okstratr used for the run (balanced preference), C = tokens relative
to the single run of the same task and repetition, L = wall time relative to
the same.

## Pilot size

3 tasks × 2 approaches (utility, single) × 3 repetitions = 18 runs.
Adding the template approach makes 27. Three repetitions are enough to see
large differences (the offline benchmark's per-task Δ vs single is
0.16–0.53 U for these task types), not small ones; report each run, the
paired Δ per task and W/T/L, and do not claim significance from a pilot.

## Dispatch estimate

Seats per run, with one harness label:

| Task | Utility shape | Seats (no expansion) | With expansion | Single |
|---|---|---|---|---|
| code | tools_verify | 5 (2 investigate, execute, verify, synthesize) | up to ~9 | 1 |
| synth | single_verify | 3 (investigate, verify, synthesize) | up to ~7 | 1 |
| research | single_verify | 3 | up to ~7 | 1 |

For 3 repetitions: utility about 33 seats (range 33–69), single 9, judges 6
(synth and research only). **About 50 subagent dispatches for the pilot**
(up to about 85 if every run expands to its limit). The optional template
arm adds 9 runs × 4 seats (2 investigate, verify, synthesize) ≈ 36.

Wall time is dominated by subagent turns. Waves run in parallel, so a
utility run takes 3–5 sequential seat turns; a single run takes one.

## Limits

- **Subagents probably cannot dispatch subagents.** The top-level agent has
  to run the queue loop and dispatch every seat (and every judge) itself. A
  seat cannot start its own helpers, and a dispatched coordinator cannot run
  the loop for it.
- **One model behind every seat.** All seats are the same agent, so recipes
  that rely on different models (`ivs_diverse_*`, `parallel_diverse_*`) get
  no model diversity here. That is why the runbook uses one harness label;
  the gains it can show come from verification, execution and expansion,
  not from diverse models. The multi-model recipes stay in okstratr and are
  covered by the offline benchmark.
- **Tokens may be estimates.** If the dispatch tool does not report usage,
  okstratr estimates from prompt and result sizes, the same way for every
  approach. Report which was used.
- **Seats share the box.** They could read the store or other runs' work
  folders. The seat instructions forbid it; the parent should spot-check
  seat replies for references to other runs.
- **Small tasks.** The synth documents total about 2,300 words and the
  corpus is 13 short files, chosen so a pilot is affordable. Larger inputs
  favour multi-seat shapes more; scale up only after the pilot.
