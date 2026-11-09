## North-star fit

Reuses, before adding anything: `route.py`'s existing `INTENTS` table and `launch()`/`--launch` mechanism (`skills/route/scripts/route.py:259-272`) for decision 5 (routing already does what option A asks — nothing new to build there); `bench.py`'s existing `run_once()` workdir logic (`bench/bench.py:255-337`) as the single place that creates/destroys bench working folders, for decision 1 (bench-folders) — no new script, just change how that one function names/clears its directory; `docs/agents/decisions-format.md`'s Decisions block syntax for the two new questions this reply has to ask back. Simplest sufficient approach: two small, independently testable code edits (route.py's `recall` row, bench.py's workdir strategy) plus a doc addendum and a PR reply — not a redesign of routing or the bench harness. Spends tokens on: a short doc commit + a small code PR + one PR comment; saves tokens going forward by dropping a dead Haiku-routing claim and by not inventing a recurring-rerun or skill-pruning mechanism nobody asked for yet. Leaves the user (Gil) more capable: he gets a direct answer to each question he actually asked, two concrete decisions acted on, and two real ambiguities (rerun cadence, skill-listing mechanism) handed back as buttons instead of silently guessed or silently dropped — matching why ticket #1140 exists (marvin#607: a PR with answered decisions and no reply is MARVIN's move, not the owner's).

Correcting the ticket's own framing: #1140 doesn't ask me to build "a design", it asks me to act on an *already-designed* doc's decisions. Two of the six decisions (`routing`, `claude-md`) require **no code change at all** — one is already satisfied by existing code, the other was declined. Only two (`recall-model`, `bench-folders`) are concrete, buildable code changes. The remaining two (`rerun`, `skill-listing`) can't be honestly "carried out" without guessing, because the owner's chosen box and his own note pull in different directions (`rerun`) or because no box was chosen at all and the note describes a mechanism that doesn't exist yet (`skill-listing`). This is exactly the ticket's own "notes contradict a chosen option" trap — I verified it against the code rather than assuming it.

## What I read and what it shows

- `docs/design/1037-session-overhead.md` (on `origin/ticket/1037-overhead-design`, PR #1125's only commit, `1d2a5c81`) — the design doc itself.
- PR #1125's body (current, 1 commit, no new comments since the owner's decisions comment at `2026-11-04T20:47:02Z`) — confirms the Decisions section and ticked boxes I'm acting on are still current; nothing changed since.
- `skills/route/scripts/route.py` — `INTENTS["recall"]["model"]` is `claude-haiku-4-5-20251001`; `"why"` text claims "Haiku handles recall at ~60% Sonnet cost (bench Run 8)" — the exact thing decision `recall-model` reverses. `launch()` (line 259) already execs `claude` with the routed config/model — decision `routing`'s option A is already what this does.
- `skills/route/scripts/auto_route_hook.py` — `MESSAGES["recall"]` (line 24) advertises the Haiku switch for recall; becomes false once the model fix lands.
- `skills/route/scripts/tests/test_auto_route_hook.py` and `lib/tests/test_route.py` — existing coverage; `test_classify_returns_message_for_recall` (line 44) will need to flip to a silence test, matching `test_classify_is_silent_for_architecture`.
- `bench/bench.py` `run_once()` (lines 255-337) — `cwd == "tmp"` and `is_fs` tasks get `tempfile.mkdtemp(prefix=f"mb-{task_id}-{profile}-")` (a fresh random path every call) and `shutil.rmtree` on teardown. This is precisely the "fresh temp folder per run" artifact decision `bench-folders` picked a fix for. Confirmed single-threaded (`bench/bench.py:658-721`: sequential `for task / for profile / for repeat`), so a stable, serially-reused directory is safe — no concurrency to guard against.
- `bench/tests/test_cost_validation.py::test_qa_task_with_tmp_cwd_runs_in_a_fresh_folder_outside_home` (line 82) — currently asserts the folder is gone afterward; this is the test that has to change to prove the new behavior, not just get out of the way of it.
- `bench/cost_validation.sh` line 26 comment ("route.py sends recall and research to Haiku") — goes stale the moment `recall-model` lands; it's a comment, not logic, but a stale comment is exactly what causes the next person (or agent) to reintroduce the bug.
- Searched for "deprecated" anywhere in `skills/` and `CONTEXT.md`: nothing in this repo is actually marked deprecated today. The owner's "get rid of deprecated tools" note has no concrete target yet — it's a standing instruction for whenever one appears, not a backlog of five things to delete right now.
- Searched for a `marvin ask` entry point, a phone-Thread launcher, and a per-chat skill-pruning mechanism: none exist yet (MARVIN Mobile is still ADRs 0039-0046, in progress). So decision `routing`'s named examples are future call sites for a mechanism that already exists in `route.py`, not missing code.
- `bench/tasks/*/task.json`: 12 `fs` tasks, 6 `qa` tasks already exist — more than "3 per type" on its face, but decision `rerun` is about *timing a $25 API-cost sweep*, not something to trigger from inside an automated ticket run regardless of count (low-cost-experimentation discipline, and the account was at its 7-day usage warning on 2026-11-04 per the doc). Not something this ticket should execute.

## Decisions

Two genuine ambiguities, formatted for the PR #1125 reply (not guessed, not asked in prose):

```markdown
## Decisions
<!-- marvin:decisions -->
### rerun-cadence: The chosen rerun option says run `cost_validation.sh` once, after #1037's task set exists; your note also asks for it on a semi-regular basis. Which should this build?
- [ ] A: Just the one-time re-run once the task set exists (3+ tasks/type) — matches the ticked box exactly, no scheduling added
- [ ] B: The one-time re-run, plus a recurring schedule (e.g. monthly) added once that first run is clean
- [ ] C: Skip the one-time gate — set up the recurring schedule directly

### skill-listing-mechanism: No skill group was picked to leave the listing, and the note asks for something bigger instead — route skills to the chats that need them, without moving to slash-command-only, and drop deprecated tools when they appear. That's a new mechanism (nothing in the repo does per-session skill pruning today), not a doc change. Should it be its own ticket?
- [ ] A: File it as a new follow-up ticket now (design: per-launch skill-set selection + a standing "flag deprecated tools" check)
- [ ] B: Fold it into #1037 part b's remaining work instead of a separate ticket
- [ ] C: Not now — revisit after the next bench rerun shows the listing's cost clearly
```

## Tests first

One per "How we'll try to break it" item, plus the misuse cases it didn't name:

1. **Notes contradict a chosen option (named case)** — assert the reply for `rerun` states the contradiction explicitly and carries a new Decision, rather than silently picking A, B, or C. (Checked by hand when drafting the reply comment — no code path to unit-test; verified by re-reading the posted comment body before closing out.)
2. **PR changed since the decisions (named case)** — re-ran `gh pr view 1125` and `gh pr view 1125 --json comments` immediately before planning (done above): still 1 commit, still only the owner's original decisions comment. No drift to account for.
3. `test_route_recall_model_is_session_default` (new, `lib/tests/test_route.py`): `route.INTENTS["recall"]["model"] is None`.
4. `test_route_research_model_is_still_haiku` (new, same file): `route.INTENTS["research"]["model"] == "claude-haiku-4-5-20251001"` — proves the fix didn't also knock out the half of the decision that keeps research/explain on Haiku.
5. `test_launch_cmd_recall_has_no_model_flag` (new): `route._launch_cmd("recall")` contains no `--model`.
6. Replace `test_classify_returns_message_for_recall` with `test_classify_is_silent_for_recall` (`skills/route/scripts/tests/test_auto_route_hook.py`): `arh.classify(...)` returns `None` when `_resolve_intent` returns `"recall"`, same shape as the existing `test_classify_is_silent_for_architecture`.
7. `test_main_no_longer_fires_a_message_for_recall` (new, same file): full stdin/stdout path with a recall-shaped prompt, monkeypatched `_resolve_intent` to `"recall"`, asserts empty stdout and `_already_fired` still set — mirrors `test_main_marks_fired_even_when_classify_is_silent`.
8. Rewrite `test_qa_task_with_tmp_cwd_runs_in_a_fresh_folder_outside_home` (`bench/tests/test_cost_validation.py`): the folder now **persists** after the run (not `not seen["cwd"].exists()`), lives outside `$HOME`, and is empty *at run start* (not "fresh" — pre-existing stale content must be gone before `claude` sees it).
9. `test_stable_workdir_path_is_identical_across_repeat_calls` (new): two `run_once()` calls with the same `(task_id, profile, model, prompt_prefix)` land in the same directory path both times.
10. `test_stable_workdir_is_emptied_of_leftover_files_before_the_run` (new): pre-seed the stable directory with a stray file from a "previous run", call `run_once`, assert the stray file is gone and only the task's fixture files (for `is_fs`) or nothing (for `qa`) remain.
11. `test_stable_workdir_differs_by_profile_and_model` (new): same task, different `profile` or `model` → different directory paths — no collision between cells sharing a task id.
12. `test_stable_workdir_differs_by_prompt_prefix_tag` (new): same task/profile/model, different `prompt_prefix` (e.g. `""` vs `"Caveman mode. "`) → different paths — covers `cost_validation.sh`'s caveman-tagged cell not colliding with the plain cell for the same task+profile.
13. **Each dependency failing** — `claude` subprocess itself raising/timing out is already covered by the existing `TimeoutExpired` branch (line 302); confirm no new failure mode: `test_stable_workdir_survives_a_timeout_without_leaving_half_written_state` (new) — a `TimeoutExpired` run still leaves the stable directory usable (not deleted mid-write) for the next repeat.
14. **Repeats and wrong order** — `test_three_repeats_reuse_one_directory_and_each_starts_clean` (new): simulate 3 sequential `run_once` calls (mocking `subprocess.run` to write a marker file each time), assert each run only ever sees its own marker, never a prior repeat's.
15. **A person's mistakes / stale state** — `test_stable_workdir_handles_a_directory_that_already_has_wrong_permissions_or_is_a_file`: if the stable path exists as a plain file (not a directory) from some earlier manual poke, `run_once` recovers (removes it, creates the directory) instead of crashing.
16. **Bad/empty/malformed input** — `test_run_once_with_empty_prompt_prefix_and_no_model_still_builds_a_valid_path` (new): defaults (`model=None`, `prompt_prefix=""`) produce a sane, non-colliding directory name (no `None`/empty-string artifacts in the path).

## Task List

1. `skills/route/scripts/route.py`: set `INTENTS["recall"]["model"] = None`; rewrite `"why"` and `"savings"` to state recall stays on the session model (drop the Run-8 Haiku-cost claim); leave `research`'s Haiku row untouched. Add tests 3-5.
2. `skills/route/scripts/auto_route_hook.py`: drop the `"recall"` key from `MESSAGES`. Update tests 6-7 in `test_auto_route_hook.py`.
3. `bench/bench.py`: replace `run_once()`'s `tempfile.mkdtemp(prefix=f"mb-{task['id']}-{profile}-")` + unconditional `shutil.rmtree` with a deterministic path keyed on `(task_id, profile, model or "default", slug(prompt_prefix))` under the system temp root; empty (not delete) it at the start of each call if it already exists or isn't a directory; stop deleting it at teardown. Write tests 8-16 in `bench/tests/test_cost_validation.py` first, then make them pass.
4. `bench/cost_validation.sh` line 26 comment: "route.py sends recall and research to Haiku" → "route.py sends research to Haiku; recall now stays on the session model (PR #1125)."
5. Run the full `lib/tests/test_route.py`, `skills/route/scripts/tests/test_auto_route_hook.py`, and `bench/tests/test_cost_validation.py` suites; confirm nothing else references `INTENTS["recall"]["model"]` or the old mkdtemp behavior (grep both before committing).
6. Open the code PR from steps 1-5 against `main`, body links PR #1125 and states which two decisions (`recall-model`, `bench-folders`) it carries out.
7. Push one commit to `origin/ticket/1037-overhead-design` (PR #1125's own branch) adding a "## Decisions recorded, and what happens next" section to `docs/design/1037-session-overhead.md`: records all six outcomes, names the code PR from step 6 for the two buildable ones, states plainly that `routing` needed no new code (already satisfied) and `claude-md` needed none (declined), and flags `rerun` and `skill-listing` as unresolved pending new Decisions.
8. File a new GitHub issue (`gh issue create --repo G-Eskayo/marvin`) only if the reply's `skill-listing-mechanism` decision comes back as option A: scope = design a per-launch skill-set selection mechanism (extends `route.launch()`/the `index` skill's manifest pattern to prune the skill *listing*, not just file loads) plus a standing "flag tools marked deprecated" check; links #1037 and #1125. Do not file it speculatively before the owner picks.
9. Post the reply comment on PR #1125: states what changed (cites the code PR's commit once merged, and the doc-branch commit from step 7), confirms no screenshots apply (doc + backend-only changes, nothing visual), answers the `claude-md` and `recall-model` questions in plain language, and carries the Decisions block from above. Must include `<!-- marvin:decisions-addressed -->`.
10. Verify via `bin/gh` that the reply posts cleanly (no `DECISIONS_NOT_ASKABLE`/`DECISIONS_UNPARSED`) before considering #1140 done.