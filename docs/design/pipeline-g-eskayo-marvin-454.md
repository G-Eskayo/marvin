Good — this confirms the standing decision ("Titles always travel with numbers") the ticket is enforcing; nothing in CONTEXT.md contradicts the plan. I have what I need to write the plan.

## North-star fit

**Reuses:** `lib/mr_raiser.py:_ticket_title`/`_subject` (lines 61-76) already compute `<ticket title> (#<n>)` with a safe fallback — this is the exact pattern the pipeline-PR-title requirement needs, and it turns out to already be wired into `_commit_and_push` and `_default_open_pr`'s create path (confirmed by existing passing tests `test_the_pr_title_matches_the_commit_subject`, `test_an_unreadable_ticket_title_still_commits_under_the_old_subject`). The only gap is that `_default_open_pr`'s *rework* branch (`lib/mr_raiser.py:211-219`, the "already exists" `gh pr edit`) never passes `--title`, so a rework keeps whatever title the first pass gave it. For the dashboard half, `dashboard/src/components/MrReview.jsx:445-446` (`PrCard`) already renders a repo badge for non-marvin repos — that acceptance-criterion line is already satisfied and needs no new code, just confirmation. `dashboard/electron/main/relations_service.js:67-101` (`parity()`) already resolves each open PR to its ticket's real title via board data — the bare-title fallback can reuse that existing plumbing (`parity.prs[].ticket.title`) instead of adding a new ticket-fetch path.

**Simplest sufficient approach:** three small, independently testable edits (one line in `mr_raiser.py`, two pure helpers in `project_onboard.py`, one pure helper + one call-site edit in the dashboard) plus a one-time live retitle of 4 GitHub PRs — no new files beyond one 6-line pure-function module (`dashboard/src/lib/pr_title.js`), matching the project's existing convention of tiny pure lib files (`pr_order.js`, `decisions.js`, `pr_images.js`).

**Where it spends/saves:** spends nothing ongoing — all three fixes are pure string formatting or a conditional in an already-running code path; the dashboard fix reuses data (`parity()`) the UI already fetches every refresh, so it adds zero GitHub calls.

**Leaves the user more capable:** yes — a correct PR/ticket title is exactly the information Gil needs to triage MR Review without opening each PR; this removes a repeated manual "what is this PR actually about" step he flagged directly ("not helpful in the slightest").

One correction to the ticket's own framing: the "What to build" bullet gives the onboarding PR title as the literal template `Onboarding <repo-name>: agent docs and CI`, but the very next sentence — "Only claim CI if the PR actually adds a workflow file. The 2026-10-09 PRs claimed CI and contained none." — describes a bug *in that title itself* (the 2026-10-09 PRs' title said "and CI" with no CI file). Treating only the description as conditional would leave the documented bug unfixed, so the title must be conditional too (`Onboarding <repo-name>: agent docs` when no CI file is added, `... agent docs and CI` when one is). This isn't an open question for the owner — it's required by the Problem statement itself, so I'm resolving it, not punting it.

## Tests (written first)

The ticket has no "How we'll try to break it" section (likely why an earlier automated attempt stalled on "no task list"). Deriving the adversarial cases directly from each "What to build" bullet and the north-stars' misuse checklist:

**`lib/tests/test_mr_raiser.py`**
1. `test_rework_open_pr_also_updates_the_title` — existing-PR branch (`_default_open_pr`'s `CalledProcessError "already exists"` path) must call `gh pr edit <url> --title <subject>`, not just `--body`.
2. `test_rework_retitles_even_when_the_ticket_title_changed_since_first_raise` — the rework's title reflects the *current* ticket title (person edited the ticket after the first PR was raised), not a cached/stale one.
3. `test_subject_never_bare_when_title_resolves` — parametrized over several `(ticket_ref, title)` pairs (including a title containing only whitespace collapse, and one with embedded newlines/flag-like text reusing the existing adversarial fixture) asserting `_subject(...)` never equals the bare `Implement <ref>` form when `_ticket_title` returns non-empty text.
4. `test_ticket_title_none_on_timeout` — `gh issue view` raising `subprocess.TimeoutExpired` (not just non-zero exit) still yields `_ticket_title(...) is None`, so `_subject` falls back cleanly (dependency failure case, distinct from the existing non-zero-exit test).
5. `test_failed_retitle_on_rework_is_not_swallowed` — a `gh pr edit --title` failure (wrong permissions / revoked token) on the rework path still raises (`check=True`), it isn't caught and hidden.

**`lib/tests/test_project_onboard.py`**
6. `test_pr_title_has_repo_name_and_claims_ci_when_workflow_added` — title is `Onboarding <repo-name>: agent docs and CI` when `.github/workflows/ci.yml` is among the written files.
7. `test_pr_title_omits_ci_claim_when_no_workflow_file_added` — title is `Onboarding <repo-name>: agent docs` (no "CI") when only docs files are written — the direct regression test for "claimed CI and contained none."
8. `test_pr_body_lists_exactly_the_files_written` — body enumerates precisely the files in `files_to_write` (+ `CLAUDE.md` once, not duplicated, when appended) — not more, not fewer, for a partial-missing-docs case (only one doc file missing).
9. `test_pr_body_says_ci_only_when_ci_included` — same scenario twice (with/without the workflow file) asserting the literal word "CI" appears in the body iff the workflow file was written.
10. `test_pr_title_uses_the_correct_repo_even_with_a_hyphenated_name` — malformed-ish repo name edge case (`owner/some-repo.name`) still slices to the right short name.
11. Confirm (no new test needed, already covered) — `test_apply_pr_unchanged_when_nothing_missing` still passes untouched: zero files means title/body helpers are never invoked.

**`dashboard/test/` (new `pr_title.test.js`)**
12. `test_replaces_bare_implement_repo_number_form` — `Implement G-Eskayo/marvin#218` + a ticket title → shows the ticket title.
13. `test_replaces_bare_implement_short_number_form` — `Implement #218` (the short legacy form in fixtures/history) + ticket title → shows the ticket title.
14. `test_never_overrides_a_real_title_that_merely_starts_with_implement` — `Implement retry logic for #12` is left untouched (anchors the regex so a genuine title containing "Implement" is never mistaken for the bare marker).
15. `test_falls_back_to_bare_title_when_no_ticket_title_available` — ticket missing/not resolved yet → shows the raw (bare) title rather than `undefined`/blank.
16. `test_empty_or_whitespace_ticket_title_is_treated_as_unavailable` — malformed-input case: an empty-string or whitespace-only ticket title must not replace a real bare title with blank text.
17. `MrReview.test.jsx` (existing file, extended) — `test_card_shows_repo_badge_and_substituted_title_together_for_another_repos_bare_pr` — the compound case the ticket actually describes: a bare-titled PR from a non-marvin repo shows both the repo badge and the resolved ticket title on the same card.

## Decisions

None — the one apparent ambiguity (whether "only claim CI" governs the title or only the description) is resolved by the Problem statement itself, not left open; see north-star fit above.

## Task List

1. `lib/mr_raiser.py`: in `_default_open_pr`'s "already exists" branch, add `"--title", _subject(ticket_ref)` to the `gh pr edit` call so a rework retitles the PR.
2. `lib/tests/test_mr_raiser.py`: add tests 1–5 above (rework retitle, stale-title rework, never-bare property test, timeout dependency failure, failed-retitle-not-swallowed).
3. `lib/project_onboard.py`: add `_pr_title(repo, includes_ci)` → `f"Onboarding {repo.split('/')[1]}: agent docs" + (" and CI" if includes_ci else "")`.
4. `lib/project_onboard.py`: add `_pr_body(files, ticket, includes_ci)` → summary line ("Adds agent docs." / "Adds agent docs and a CI workflow.") + exact bullet list of `files` + `_closes(ticket)`.
5. `lib/project_onboard.py`: in `_apply_pr`, compute `includes_ci = ".github/workflows/ci.yml" in files` right after `files` is built, and replace the hardcoded `ONBOARDING_TITLE` / `"Automated agent docs and CI workflow setup..."` in the `gh pr create` call with `_pr_title(repo, includes_ci)` / `_pr_body(files, ticket, includes_ci)`.
6. `lib/project_onboard.py`: reword `ONBOARDING_TICKET_BODY`'s "the pull request titled "{ONBOARDING_TITLE}"" line to stop quoting a now-variable PR title (point at "this ticket's linked pull request" instead); leave `ONBOARDING_TITLE` (the ticket's own title) unchanged — ADR 0058 fixes that string.
7. `lib/tests/test_project_onboard.py`: add tests 6–10 above.
8. `dashboard/src/lib/pr_title.js` (new, ~6 lines): `export function displayTitle(title, ticketTitle)` with the anchored bare-`Implement` regex.
9. `dashboard/test/pr_title.test.js` (new): tests 12–16 above.
10. `dashboard/src/components/MrReview.jsx`: in `PrCard`, import `displayTitle` and render `displayTitle(pr.title, parity?.ticket?.title)` in place of the raw `pr.title` at line 445 (repo-badge logic at line 446 stays as-is — already correct).
11. `dashboard/test/mr_history_render.test.jsx` or `MrReview`-specific render test: add test 17 (compound repo-badge + title-substitution case).
12. Run the full suite (`~/.agents/venv/bin/python -m pytest lib/tests/test_mr_raiser.py lib/tests/test_project_onboard.py` and the dashboard's `vitest`) and confirm everything passes, then verify by changing only the implementation (not the tests) that each new test actually fails first (red-green per `tdd`).
13. One-time live retitle (not unit-tested, operational): `gh pr edit` on #400 → `"Stop retry storms: hold a ticket after N failed pipeline runs (#218)"`, #368 → `"Pipeline stage strip on PR and ticket cards (GitLab-style), showing where it failed (#217)"`, #359 → `"Usage: show how much of the allowance autonomous work uses (no cap yet) (#81)"`, #358 → `"Proposals section in MR Review: big north-star ideas, plain-language cards, actions (#102)"` (closed PR — `gh pr edit` still works on closed PRs); verify each via `gh pr view <n> --json title`.
14. Capture real dashboard screenshots (Electron CDP attach, per the hard screenshot rule) showing a card with the repo badge and the ticket-title substitution for a bare-titled other-repo PR, for this ticket's own PR evidence.