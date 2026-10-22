## North-star fit

**Reuses:** `ticket_policy.HOLD_LABELS` (`lib/ticket_policy.py:16`), the `write_revisit_state`/`check_hold_revisit` JSONL-state → health-check pattern (`lib/ticket_agents.py` / `lib/health_checks.py`), the "one ranked ladder, first match wins" pattern in `rework_status.status_for` and `prState.js`'s `sentBack` branch, and `project_catalog.run_env()` (`lib/project_catalog.py:407`) — the existing "GitHub gate" pattern `ticket_agents._gh` already uses (line 494-496) and `rework_status._gh` currently does not.

**This is not a fresh design — it's a repair pass on code that already exists.** I read the current worktree directly (`git diff --stat`: 16 files, 640 insertions, all uncommitted) and the full content of every touched production and test file. The implementation is substantively complete against all three acceptance criteria, and unlike the previous audit, this time **tests exist for almost everything** (170 new lines in `test_rework_status.py` alone). The gap the last review found is narrower than "no tests were written": it's 1 production bug (`--paginate` without `--slurp`) and 4 test bugs where the test's own fake doesn't exercise the branch it claims to, so a real regression would slip through silently. I verified the ticket_pipeline `pinned`-regression gap flagged by the *previous* design doc's own audit is already closed (`test_ticket_pipeline.py:1301-1307` now covers `hold`, `held`, `pinned`, and clean, confirmed by direct read).

**Simplest sufficient approach:** fix the 5 confirmed defects at the root (1 production bug, 4 vacuous test conditionals), add the handful of misuse-case tests the review's "notes" surfaced as real but non-blocking gaps (malformed health-check entry, a test that silently touches real `~/.claude` state, two places the detail text or label set can mislead or drift), and stop there. No redesign, no new abstractions — every fix is a one- or two-line change in a file that's already open for its own bug.

**Where this spends/saves tokens:** the pagination fix (`--slurp` + flatten) is a 2-line change, not a rewrite; adding `run_env()` to `rework_status._gh` is reusing an existing 15-line function rather than writing a new one. This round spends slightly more tokens than the prior attempt estimated, specifically on *proving* the two fixed tests actually fail before the fix and pass after (TDD red→green), because that's exactly the discipline whose absence caused the "must-fix" findings — skipping it again would reproduce the same review outcome a third time.

**Phone-OS direction:** neutral, as before — pipeline-integrity plumbing.

**More capable, not more passive:** yes — this removes a state (held + ready + sent-back all at once) that today a person discovers by having their feedback silently vanish for days (#358), and it makes a health check, not a person, the one that notices when that happens again.

## What the review actually found (grounded, not re-derived)

Must-fix (blocking), each verified against the real file/line:

1. **`lib/rework_status.py:53`** — `gh api .../events --paginate` with no `--slurp` concatenates one JSON array per page (`[...][...]`); `json.loads` on that is invalid JSON, so `json.loads` raises, the outer `except Exception: return None` swallows it, and any ticket whose event history spans more than one page (the long-lived, repeatedly-held tickets this feature exists for) silently loses its label/date/comment. Confirmed by reading the function; it is wrapped in a single broad `try/except Exception` at line 48-94.
2. **Test 8** (`test_hold_info_partial_degradation_when_comments_fetch_fails`) — its fake checks `"issue view" in args[0]`; `args[0]` for the comments call is just the string `"issue"` (the args list is `["issue", "view", ...]`), so the substring check is always `False`. The fake never returns the intended failure, the call falls through to `{}`, and the assertion that `_hold_info` degrades gracefully never touches the failure branch it claims to test.
3. **Test 9** (`test_hold_info_ignores_comment_outside_window`) — identical bug, same wrong conditional; the out-of-window comment is never actually returned by the fake, so the window-filter logic is never exercised — the assertion passes whether or not the filter works.
4. **Test 19** (`test_find_label_contradictions_truncates_at_50`) — slices `contradictions[:50]` itself and asserts on its own slice; it never calls `write_label_contradictions_state`, so the 50-cap the test claims to pin is untested.
5. **Test 21** (`test_run_with_label_contradictions_path_none_doesnt_write_file`) — checks whether the literal string `"label_contradictions"` (underscore) is a member of a list of full paths in `tmp_path`. The real filename (`LABEL_CONTRADICTIONS_PATH`, `lib/ticket_agents.py:288`) is `label-contradictions.json` (hyphen) — the assertion can never be true regardless of whether `run()`'s `if label_contradictions_path is not None:` guard works.

Notes worth fixing this round (cheap, directly reduce a real bug or duplication, not scope creep):

6. `lib/health_checks.py:522` — `c['repo']` / `c['number']` read with no `.get()` inside `check_label_contradictions`'s list comprehension; one malformed entry in the state file raises `KeyError` instead of degrading. This is squarely "malformed input," one of the misuse categories this ticket requires testing against, and today there's no test for it (confirmed: `test_health_checks.py`'s Test 26 only covers a malformed *envelope* — bad JSON or missing `generated_at` — never a malformed *entry* inside an otherwise valid `contradictions` list).
7. `rework_status.py:223` — `next(iter(names & ticket_policy.HOLD_LABELS), None)` picks whichever label set-iteration order happens to produce, when a ticket carries two hold labels at once (a person's mistake — explicitly one of the ticket's own misuse scenarios). Non-deterministic across Python runs/versions. Fix: `sorted(names & ticket_policy.HOLD_LABELS)[0]`.
8. `rework_status.py:144` — `detail += f" — Reason: \"{comment[:100]}...\""` always appends `"..."`, even when the comment is under 100 characters and nothing was truncated.
9. `rework_status.py`'s `_gh` (line 41-45) calls bare `["gh", *args]` with the inherited environment; `ticket_agents.py`'s `_gh` (line 494-496) instead passes `env=run_env()`, which puts the GitHub gate (`~/.agents/bin/gh`) first on `PATH` and supplies `GH_TOKEN` when the environment doesn't already have one — exactly the "wrong permissions/machine" misuse case the ticket's required test categories name, and exactly the pattern this same file's sibling function already establishes. `rework_status._gh` should match it.
10. `test_rework_status.py`'s Test 11 (`test_collect_end_to_end_with_hold_ticket`) hand-swaps `subprocess.run` globally instead of using `monkeypatch` (so a test failure before the `finally` can leave the real `subprocess.run` patched for later tests), and its catch-all can let `ticket_stages.read_stages` fall through to reading real `~/.claude/logs` state. This is the same class of risk the "`~/.claude/logs` wipe" incident came from (a test touching real HOME state). Fix: `monkeypatch.setattr` and a stubbed `ts.read_stages`.
11. `dashboard/electron/main/decisions_submit.js:61` redefines `new Set(['pinned', 'hold', 'held'])` locally; `dashboard/src/lib/ticket_input.js:9` already exports `HOLD_LABELS` as the shared source of truth, and `ticket_input.js`'s own header comment says explicitly "Shared by the dashboard... and by the main process... so the two can never disagree" — the current code violates that stated intent. Fix: import it.
12. `decisions_submit.js:71` — `Promise.resolve().then(() => { out.labelSkipped = '...' })` for a synchronous assignment; simplify to a direct assignment, same behavior.
13. `prState.js:43` — the detail text tells the reader to "clear the hold label" to let the rework proceed, but the only action offered (`clearSentBack`) clears the **sent-back** label (`needs-reengagement`), confirmed against `CONTEXT.md:1216`'s own description of what that button does. A person reading the card could click the button expecting it to lift the hold. Fix the wording so it's clear the hold label is removed on GitHub by a person, and the button here does something else (clears a stale sent-back label if the rework is already in by hand).
14. Housekeeping: `.commit-msg-1` (a stray scratch commit-message file for an unrelated test) is sitting at the repo root uncommitted — delete it. `docs/design/pipeline-g-eskayo-marvin-455.md` currently opens with agent narration ("Now I have everything I need...") — when this plan is written to that path, it must not carry that chatter.

Explicitly **not** fixing this round, with reasons: `_hold_info`'s two uncached `gh` calls per `collect()` pass are bounded to currently-held-*and*-sent-back tickets (a small, naturally-bounded set), and adding a cache would be new machinery for a cost nobody has observed yet — accepted as-is. `_read_diagnosis`'s `datetime.min(timezone.utc)` (calling a `datetime` instance as if it were a function, `lib/rework_status.py:105`) is a real latent bug but belongs to the diagnosis feature, not this ticket's hold/contradiction scope, and the review didn't flag it — noting it here rather than silently fixing something unrelated.

## Decisions

Carried forward unresolved — I read the ticket's 4 comments and none of them answer it; they are automated planner-failure notices (model session limits), not owner input:

<!-- marvin:decisions -->
### comment_window: `_hold_info`'s 5-minute hold→comment matching window is an unreviewed guess — keep it, or change it?
- [ ] A: Keep the 5-minute window as-is (`HOLD_COMMENT_WINDOW_S` in `rework_status.py`)
- [ ] B: Widen it (state the window you want in the PR's note box)
- [ ] C: Drop automatic comment-matching entirely — show only the label and date, never a possibly-wrong comment

## Tests to write first

The ticket itself has no "How we'll try to break it" section (confirmed by reading its body) — triage should have caught that per `ticket_policy.triage_verdict`'s own rule, but didn't act on it here. Using the standard misuse categories plus the specific breakages the code review actually found adversarially:

**`lib/tests/test_rework_status.py`**
1. **New** — multi-page `gh api --paginate --slurp` events response (two pages, the real `labeled` event on page 2) → `_hold_info` finds it. Must be written to fail against the *current* unpatched `events_proc` parsing (prove it reproduces finding #1) before the fix, pass after.
2. **Fix** Test 8's fake: `"issue view" in args[0]` → `args[:2] == ["issue", "view"]`. Verify red→green: temporarily confirm the old conditional lets the test pass even with the degrade-on-failure branch deleted, then fix and confirm it now actually fails without that branch.
3. **Fix** Test 9's fake with the same conditional fix; re-verify it now actually depends on the window-filter logic, not just a vacuously-empty comments list.
4. **New** — ticket with both `hold` and `held` labels, called twice → `_hold_info`/`collect` pick the same label deterministically both times (`sorted(...)[0]`), not whatever set-iteration order happens to produce (finding #7, a person's-mistake case).
5. **New** — `hold_info["comment"]` under 100 characters → detail has no trailing `"..."` (finding #8).
6. **New** — `_hold_info`'s `_gh` call is made with `env=project_catalog.run_env()` (finding #9): mock `subprocess.run`, assert the `env` kwarg is present and matches `run_env()`'s output (the "wrong permissions/machine" misuse case).
7. **Fix** Test 11 (`test_collect_end_to_end_with_hold_ticket`): replace the hand-swap of `subprocess.run` with `monkeypatch.setattr`, and stub `ticket_stages.read_stages` so the test cannot touch real `~/.claude/logs` state (finding #10).

**`lib/tests/test_ticket_agents.py`**
8. **Fix** Test 19: actually call `write_label_contradictions_state(contradictions, tmp_path / "state.json", NOW)`, read the file back, assert `len(json.loads(...)["contradictions"]) == 50`. Verify red→green: confirm it fails if the `[:50]` slice is temporarily removed from `write_label_contradictions_state`, then confirm it passes against the real code.
9. **Fix** Test 21: replace `"label_contradictions" not in [str(p) for p in tmp_path.glob("*")]` with `not list(tmp_path.glob("*contradiction*"))`. Verify it would actually catch a regression: temporarily pass a real path alongside `None` in a throwaway check and confirm the glob matches a written file, proving the assertion is capable of failing.

**`lib/tests/test_health_checks.py`**
10. **New** — a `contradictions` entry missing `"repo"` or `"number"` inside an otherwise well-formed state file (valid `generated_at`, valid JSON) → `check_label_contradictions` doesn't raise `KeyError`, degrades to a safe placeholder for that entry (finding #6).

**`dashboard/test/decisions_submit.test.js`**
11. No new test required for the `HOLD_LABELS` import dedup (finding #11) — it's a behavior-preserving refactor; existing Tests 32-34 must continue to pass unchanged, which is the regression check.

**`dashboard/test/pr_state.test.js`**
12. **Tighten** the existing "Test 35" (`describePrState` with `rework.state === 'held'`): today it only asserts `s.detail` matches `/hold|waiting|person/i`, which would still pass with the misleading wording. Add a precise assertion that the detail does not claim the on-screen action removes the hold label (e.g. it names GitHub / a person as the one who clears it), so a future regression back to the misleading wording fails this test.

## Task List

1. `lib/rework_status.py` + `lib/tests/test_rework_status.py`: tests 1, 4, 5, 6 (new), tests 2, 3, 7 (fixed fakes). Fix production code: `--paginate --slurp` + flatten (finding #1), deterministic label pick (#7), conditional ellipsis (#8), `_gh` using `run_env()` (#9). Run the file's test suite; commit together.
2. `lib/ticket_agents.py` + `lib/tests/test_ticket_agents.py`: fix Test 19 and Test 21 (tests 8, 9 above) against the existing, unchanged `write_label_contradictions_state`/`run()` code (no production change needed here — confirm with the red→green check that the existing `[:50]` slice and `is not None` guard already do the right thing). Commit together.
3. `lib/health_checks.py` + `lib/tests/test_health_checks.py`: test 10 (new). Fix `check_label_contradictions` to build each row with `.get()` defaults instead of raw `c['repo']`/`c['number']`. Commit together.
4. `dashboard/electron/main/decisions_submit.js`: import `HOLD_LABELS` from `../../src/lib/ticket_input.js` instead of the local `Set` literal (finding #11); replace the `Promise.resolve().then(...)` with a direct assignment (finding #12). Re-run `dashboard/test/decisions_submit.test.js` (Tests 32-34) unchanged to confirm no regression; no new test needed.
5. `dashboard/src/lib/prState.js` + `dashboard/test/pr_state.test.js`: fix the held-rework detail wording (finding #13) and tighten Test 35 (test 12 above) so it pins the corrected wording. Commit together.
6. Delete `.commit-msg-1`. When this design doc is committed to `docs/design/pipeline-g-eskayo-marvin-455.md`, write it clean (no agent narration) — this document already is.
7. Resolve the `comment_window` Decision once the owner answers; adjust `HOLD_COMMENT_WINDOW_S`/`_hold_info` only if the answer isn't "A: keep as-is."
8. Run the full suite end-to-end (`pytest lib/tests` + the dashboard's vitest suite) once more, confirm the metrics comparison shows the must-fix findings resolved with no regressions, then `graphify update .`.