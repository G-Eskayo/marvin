Good — only those two spots, both in `security_command`. That confirms the full scope of the code change. I have everything needed to write the plan.

## North-star fit

Reuses existing patterns, adds nothing new:
- **Decision-reply mechanism**: `lib/owner_decisions.py` (`ADDRESSED_MARKER = "<!-- marvin:decisions-addressed -->"`, `HEADING = "### Decisions from the owner"`) is the pattern a reply must satisfy — no new tooling needed, just a `gh pr comment` on #941 via the repo's `bin/gh` gate (per [[reference-github-gate]]).
- **Tag-only guarding**: `lib/task_dispatch.py`'s `accepts()`/`select_machine()` (ADR 0069, `FALLBACK_NEEDS`) already enforces "only the tag guards it" at the dispatch layer — mac-mini-2012's registry `accepts` list is the real gate, and `box_trial.py` is the only caller that ever sets `need="security"`. Dropping `box_trial.py`'s own closed tool list doesn't weaken that layer; it removes a second, redundant gate the owner explicitly chose to drop.
- **Mac-only test marking**: main grew a repo-wide `@pytest.mark.macos_only("why")` marker (`lib/tool_requirements.py`, #1117) *after* this branch forked, replacing ad hoc `skipif(sys.platform != "darwin")` checks, with a test (`test_mac_only_tests_use_the_one_marker_not_their_own_platform_skips`) that fails the suite if any ad hoc one survives. The rebase must adopt that marker for `test_plist_that_only_launchd_tolerates_still_counts` rather than keep the branch's own `skipif(not Path("/usr/bin/plutil").exists())` — reusing the newer convention, not re-inventing it.

Simplest sufficient approach: this is almost entirely "finish what's already built" — one decision (`retrieval-graph`) is already satisfied by the code as written (`retrieval_command()` already runs `graphify update .` first), so it needs zero code change, just confirmation in the reply. The other decision (`security-tools`) needs a 3-line deletion (the `SECURITY_TOOLS` frozenset and its membership check) plus matching test changes — no new abstraction, no new file.

Token cost: spends tokens on a manual conflict resolution (two real conflicts against current `main`, diagnosed below) that five automated attempts already burned 1200s timeouts and 3 "mixed verdict" iterations on without landing — worth doing by hand once rather than re-queuing a sixth automated attempt. Saves tokens everywhere else: no new design, no new file, no new pattern.

Leaves the user more capable: unblocks a stuck PR and closes the owner's open decisions loop without needing Gil to intervene himself; the box's security trial becomes capable of running any Kali tool (owner's explicit, informed choice — the trade-off was visible in the PR when he chose it).

**Correction to the ticket's own framing**: the ticket says "Carry out the chosen options... where you can." One of the two options (`retrieval-graph`) requires no action — it's already built exactly as chosen. Only `security-tools` requires a code change.

## Decisions

None needed. Both of PR #941's questions already have recorded owner answers; nothing here requires a new choice. No contradiction was found between the decisions and the PR's current notes (the decisions comment's note field is empty).

## Tests to write first

For the ticket's own "how we'll try to break it" (#983):
1. **Notes contradict a chosen option** — not a pytest test; a manual check already done: the decisions comment's `note` field is `""` for both answers, and the PR body's own table still describes the pre-decision behavior (closed tool list) — no contradiction, just unimplemented.
2. **The PR changed since the decisions** — not a pytest test; a manual check already done: PR #941 has no commits or body edits since the 2026-10-30 decisions comment, only automated-verification failure comments (none touched the decision content).

For the `lib/box_trial.py` code change (security tool list removal), in `lib/tests/test_box_trial.py`:
3. Replace `test_a_ticket_build_cannot_ride_in_as_a_security_tool` with a test asserting any tool now passes through unchanged and quoted — e.g. `bt.security_command(["claude", "-p", "build #12"]) == "claude -p 'build #12'"` — proving the decision is implemented (only the tag guards it now).
4. Keep an explicit "empty command is still refused" test (`bt.security_command([])` raises `ValueError`) — the one piece of input validation that survives.
5. Keep `test_security_arguments_are_quoted_not_interpreted` as-is — quoting is independent of the tool list and must still hold (injection resistance).
6. Fix `test_the_cli_says_where_it_ran_and_refuses_with_exit_2`, which currently relies on `"claude"` being off the now-deleted list: change it to assert `bt.main(["security"])` (no command at all) exits 2 with "refused" in stderr — still a real misuse case (a person forgetting `-- TOOL ARGS`), now exercising the surviving check instead of the removed one.
7. **Misuse the ticket's list missed**: a huge/malformed argv (e.g. an empty string as the tool name, `security_command([""])`) should still be quoted and passed through, not crash — add a test asserting it doesn't raise and quotes to `''`.
8. **Misuse the ticket's list missed**: `bt.plan("security", ...)["need"]` is still `"security"` after the change (the dispatch-layer gate is untouched) — extend the existing `test_each_trial_type_goes_with_its_tag_and_limit` case (it already covers this; just confirm it still passes unmodified, proving the real gate wasn't touched).

For the rebase itself (verification, not new tests): run the full suite after resolving both conflicts, since a hand-resolved conflict skips no gate ([[feedback-full-suites-before-hand-merge]]) — `lib/tests/test_box_trial.py`, `lib/tests/test_dispatch_fallback.py`, `brain-map/scripts/test_generate.py`, and `lib/tests/test_tool_requirements.py::test_mac_only_tests_use_the_one_marker_not_their_own_platform_skips` (the offender scan) must all pass, plus the project's own full Python + dashboard suites.

## Task List

1. In this worktree, create a rebase of `ticket/932-box-trial` onto current `main` (`cc830481`), resolving the two real conflicts:
   - `lib/tests/test_dispatch_fallback.py`: keep both sides' additions — the branch's `stdin=None` plumbing through `World.run_remote`/`World.run_local` and its three new stdin tests, *and* main's six new signal-handling tests (`test_a_signal_to_the_wrapper_alone_ends_it_and_its_job_at_once` etc., from #1139/#1144) — union, no logic conflict, just placement around the same anchor function.
   - `brain-map/scripts/test_generate.py`: take main's `@pytest.mark.macos_only("plutil reads the plist that Python's parser refuses")` on `test_plist_that_only_launchd_tolerates_still_counts`, dropping the branch's own `skipif(not Path("/usr/bin/plutil").exists())` — adopts the newer repo-wide convention (#1117) instead of keeping a duplicate mechanism.
2. In `lib/box_trial.py`: delete the `SECURITY_TOOLS` frozenset (line 43) and its membership check + error in `security_command` (lines 80-82), and the explanatory comment above it that describes the closed list. `security_command` keeps only its "needs a command" empty check and the `shlex.quote` join.
3. In `lib/tests/test_box_trial.py`: apply test changes 3, 4 (already present, keep), 6, 7 above.
4. Run `lib/tests/test_box_trial.py`, `lib/tests/test_dispatch_fallback.py`, `brain-map/scripts/test_generate.py`, `lib/tests/test_tool_requirements.py` locally; then the full Python suite and dashboard vitest suite (per [[feedback-full-suites-before-hand-merge]], since this is a hand-resolved rebase that bypasses the normal pipeline gate).
5. Commit the rebase-resolution and the `security_command` change as separate, clearly-labeled commits on `ticket/932-box-trial`; push.
6. Post a reply comment on PR #941 (via `~/.agents/bin/gh`, body via `--body-file` per [[gh-body-file-not-heredoc-substitution]]) carrying `<!-- marvin:decisions-addressed -->`, stating: both decisions acted on (security tool list dropped in commit `<sha>`; retrieval-graph confirmed already built as chosen, no change needed), and that no screenshots were retaken because this PR has no UI/visual component.
7. Confirm issue #983 closes itself once the reply posts and the PR is addressed (per `lib/owner_decisions.py`'s own closing logic) — no manual close needed.