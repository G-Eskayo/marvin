## North-star fit

**Reuses:** the exact pattern already in `lib/incident_ladder.py:389` — `changed = any(r.get("changed") for r in aid_results)` — which `step()` already uses to decide whether a clearing was "first-aid-fixed" vs "self-cleared". The fix for this regression is to apply that same, already-proven `any(r.get("changed") ...)` test one branch earlier, to the "worse" verdict at line 378, instead of inventing a new mechanism. No new file, no new abstraction — one guard clause reusing a boolean the function already knows how to compute.

**Simplest sufficient approach:** the regression's evidence (issue #707's 2026-11-18 comment) shows both registered first-aid steps (`code-sync-drop-contained-stash`, `code-sync-rerun`) reporting `changed: false` ("no leftover stash HEAD already contains", "no repo is stuck on this Mac") — i.e. the real failure was the Mac Mini's SSH remote being unreachable for ~947 minutes (`ssh: connect to host gils-mac-mini port 22: Operation timed out`), a dependency outage no registered first-aid step can touch. Despite that, `step()` still wrote `aid=worse` purely because `after > live_before`, with no check on whether first aid did anything. That one unguarded comparison is the whole defect — fixing it needs no change to `code_sync.py`, `purpose_metrics.py`, or the probe/first-aid registry, all of which behaved correctly and reported their own impotence honestly.

**Where it saves/spends tokens:** spends a small, one-time diagnosis (no background-analyst calls, no new runtime cost); saves materially going forward: today, any day this ticket is mid-regression, a wrongly-recorded `aid=worse` permanently disables first aid for the rest of that regression (`if steps and st["aid"] != "worse":` at line 363), even if the real cause later becomes something first aid *could* fix (a leftover stash, say). The fix restores first aid's ability to try every day until it either helps or the ticket clears.

**Phone-OS direction:** neutral — this is reliability plumbing for the self-healing pipeline, not a user-facing capability, but it directly serves north star 2 ("nothing may break silently" / "nothing breaks silently") by making the ladder's own self-diagnosis trustworthy.

**Leaves the user more capable or more passive?** More capable: Gil doesn't have to notice "both first-aid steps said they did nothing, yet it's flagged as worse" and manually intervene — the ladder's own evidence (`changed: false` on every line) is now read correctly by the code that's supposed to read it.

**Correcting the ticket's stated fit, if any:** the ticket doesn't state its own north-star fit; nothing to correct.

## Files already read (per "What to build" / acceptance criteria)

- `lib/incident_ladder.py` (full `step()` and surrounding helpers, lines 1–460)
- `lib/purpose_metrics.py` (full file — `PROBES`, `FIRST_AID`, `_sync_stuck_episodes`, `_code_sync_rerun`, `_code_sync_drop_contained_stash`)
- `lib/code_sync.py` (full file, both pages — push/pull/mirror, the run lock, `_track_episode`, `STUCK_ALERT_AFTER_S`)
- `lib/tests/test_incident_ladder.py` (existing coverage, especially `test_first_aid_that_makes_it_worse_is_flagged_and_not_run_again`, lines 1–230)
- Issue #707 and all 10 comments (including PR titles for #702, #706, #693, #701)
- `CONTEXT.md`'s "Solved stays solved" decision (lines ~1807–1821) — confirms no recorded decision contradicts this fix

## What actually regressed (not one of the 4 listed root causes)

The four recorded root causes (live-edit lease deferring a push, stash/pop collisions, Health-only silent alerting, leftover stashes) are all **local git-state** problems. This recurrence's cause — the Mac Mini unreachable over SSH/Tailscale for ~16 hours — is a **network/remote-availability** problem none of the four fixes (#702, #706, #693, #701) were built for, and neither registered first-aid step (`code-sync-drop-contained-stash`, `code-sync-rerun`) can do anything about it. Both correctly reported `changed: false`. The actual defect is in `incident_ladder.step()`: it judged `aid = "worse" if live_before is not None and after > live_before else "ran"` (line 378) with no regard to whether first aid changed anything, so a measured rise it never caused got blamed on it — violating the ticket's own acceptance bullet ("each dependency failing ... leaves things no worse than before") and permanently skipping first aid for the rest of this regression (line 363: `if steps and st["aid"] != "worse":`).

## Decisions

None needed — this is a bug fix in already-decided, already-implemented logic (`CONTEXT.md`'s "Solved stays solved" entry), not a new design choice.

## Tests to write FIRST (all in `lib/tests/test_incident_ladder.py`, same `env`/`FakeGitHub`/`Probe` fixtures already in the file)

1. **The regression test (required, names it in the PR body under `## Regression test`).**
   `test_first_aid_that_changes_nothing_is_not_blamed_for_a_worse_reading` — a custom `aid` callable (not the fixture's default) that returns `changed: False` for every step (mirroring #707's actual comment: "no leftover stash HEAD already contains" / "no repo is stuck on this Mac"), driven by `Probe(1, 1, 3)` (live-before 1, after 3 — same shape as the existing worse-test). Asserts: the posted body contains neither `"made it worse"` nor `"aid=worse"`; and on the next day's run (`Probe(1)`, same `did_nothing` aid), the call count to the custom `aid` function is **higher** than before — i.e. first aid still gets to run, it isn't permanently disabled. **Fails on current code** (today it writes `aid=worse` and skips first aid thereafter); **passes after the fix**.

2. **Guard against overcorrection — genuine regressions must still be flagged.**
   `test_worse_is_still_flagged_when_any_first_aid_step_changed_something` — two first-aid steps, one reporting `changed: True`, one `changed: False`, with `after > live_before`. Asserts `aid=worse` and `"made it worse"` still appear, and the next day's run does **not** re-invoke first aid. Confirms the fix uses `any(...)`, not `all(...)` — this is exactly the realistic case for ticket #707 itself, whose "First aid" section lists two steps.

3. **Malformed first-aid result (misuse: malformed input).**
   A step result dict missing the `"changed"` key entirely (a first-aid implementation that forgot to set it) must not crash `step()` and must be treated as not-changed (`.get("changed")` default), not as a guaranteed "worse".

4. **Empty aid_results (misuse: empty input / a step registered but never actually run on any Mac).**
   `steps` non-empty but the injected `first_aid` callable returns `[]` for every name (e.g. `only` matched no Mac). `any([])` must be `False`, so this can never be flagged `aid=worse`, and the ladder still proceeds to "still tripping"/reopen normally.

5. **Existing suite stays green, unweakened (ticket's "the fix PRs' tests are not weakened or deleted").**
   Run the full `lib/tests/test_incident_ladder.py` and `lib/tests/test_purpose_metrics.py` as-is, with zero edits to any existing assertion. In particular `test_first_aid_that_makes_it_worse_is_flagged_and_not_run_again` (the pre-existing `changed=True` + worse case), `test_first_aid_that_throws_is_a_failed_step_and_the_ladder_goes_on` (first-aid step raising — dependency failing), and `test_a_probe_that_throws_posts_nothing_and_is_tried_tomorrow` (GitHub/measure raising — dependency failing) must all still pass unchanged, proving the fix doesn't touch those paths.

6. **Repo-wide check (per CLAUDE.md's full-suite-before-hand-merge rule and this skill's own test-coverage habit):** run the complete Python test suite once before opening the PR, not just the touched files, since `incident_ladder.py` is imported by `purpose_metrics.run()` and the daily cleanup sweep.

## Task List

1. In `lib/incident_ladder.py`'s `step()`, inside the `if steps and st["aid"] != "worse":` block (around line 362–379), compute `changed_anything = any(r.get("changed") for r in aid_results)` right after the `for name in steps:` loop, and change the verdict line to `aid = "worse" if changed_anything and live_before is not None and after > live_before else "ran"`.
2. In the same block's `log("first-aid", ...)` call, add `changed=changed_anything` to the logged event, so a future diagnosis doesn't have to re-derive it from `aid_results`.
3. Write test 1 (the regression test) in `lib/tests/test_incident_ladder.py`; confirm it fails on the pre-fix code.
4. Apply the fix from steps 1–2; confirm test 1 now passes.
5. Write tests 2–4 (guard-against-overcorrection, malformed input, empty results); confirm all pass against the fixed code.
6. Run the existing `test_incident_ladder.py` and `test_purpose_metrics.py` suites unmodified; confirm every prior assertion still holds (test item 5).
7. Run the full Python test suite (test item 6) before opening the PR.
8. Open the PR with a `## Regression test` heading naming `lib/tests/test_incident_ladder.py::test_first_aid_that_changes_nothing_is_not_blamed_for_a_worse_reading`, and reference issue #707 ("Part of #707" — the watch stays open under the `watch` label; this fix addresses the self-disabling bug the 2026-11-18 recurrence exposed, not the Mac Mini's underlying network reachability, which is infrastructure outside this ticket's code scope).