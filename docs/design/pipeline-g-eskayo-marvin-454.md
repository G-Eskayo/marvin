I have all the context needed. Here's the design doc.

## North-star fit

This is a **fix pass on the existing uncommitted diff** in this worktree (confirmed via `git diff`), not a rebuild: `mr_raiser.py`'s rework retitle, `project_onboard.py`'s `written`-tracking / `_onboarding_pr_title`/`_onboarding_pr_body`, `mr_review.js`'s `normalizeTitle`/`BARE_TITLE`, and `index.js`'s wiring are all already correct in production code — the latest review found exactly **one** production bug (a dropped `body` field in `dashboard_gh_api.js`) and the rest of its must-fix list is entirely about tests that don't test what they claim. Reuses everything already built; touches only the flagged lines plus the tests that need to actually exercise the behavior they assert. Simplest sufficient approach: no new abstractions — a one-line revert, a few test bodies replaced with ones that fail against the bug they claim to catch, two new tests for scenarios the prior attempt's own list promised but never wrote (malformed ref, real repeat-dispatch). Token cost: this review pass itself is spent on reading, not speculative rewriting — I verified every "must-fix" against current file contents before touching anything, and verified the "notes" (lower-priority, not in `fix_these`) against current code too, since several no longer apply. User capability: real PR titles and an honest onboarding PR body remain the actual deliverable — unchanged from the prior plan — so Gil can trust MR Review cards without opening each PR.

**Checked against code, corrected:** the review's "notes" about `dashboard/test/mr_review.test.js` (C14/C16 using a "locally-redeclared regex", C21 "proving non-call by throwing") **do not match the file as it stands** — `grep` confirms `BARE_TITLE` is declared only once (in `mr_review.js`), and C14/C16/C21 already call the real `listPipelinePrs` with `vi.fn()` spies. These three are not touched. The two real, narrower gaps the same note pointed at — no false-positive guard for a title like `"Implement retry logic for #218"`, no dotted-repo-name case in C16 — are still absent and worth adding as new tests, not rewrites. `index.js`'s `ghIssueView(number, repo)` signature was also re-checked directly (`index.js:138`) against how `normalizeTitle` calls it (`(number, repo)` in `mr_review.js:274`) — they match; no bug there either.

## Fixes (mapped to must-fix findings only — the 10-item `fix_these` list)

**1. `dashboard/mobile-backend/dashboard_gh_api.js:284`** — revert this hunk only: restore `'--json', 'number,title,body'` on the `/mr/ticket-context` route's `ghIssueView` (the one feeding `fetchTicketContext`, not the new one at :210 feeding `listPipelinePrs`, which correctly only needs `title`). Verified the break directly: `fetchTicketContext` (`mr_review.js:181`) reads `ticket.body` to find a `## Parent` ref; with `body` dropped, that's always `undefined`, silently breaking parent-ticket lookup for every `/mr/ticket-context` call.

**2. `lib/tests/test_project_onboard.py:2615`** (`test_identical_content_skip_does_not_count_as_written`) — rewrite to actually seed `remote_files` with a file whose remote content is byte-identical to what `_apply_pr` would write (sourced from the real `_render_agent_docs` output, not retyped), and assert that file is excluded from `result["files"]` while an unaffected sibling file is still included (positive control, so the test can't pass by accident if nothing gets written at all).

**3. `lib/tests/test_project_onboard.py:2738-2765`** (B11/B12/B13) — replace all three:
   - B11: fail only the `issue-tracker.md` PUT by matching its unique `message=Add docs/agents/issue-tracker.md` arg; assert that file is excluded while `triage-labels.md` (unaffected) is still written.
   - B12: fail only the CLAUDE.md create PUT (`message=Create CLAUDE.md...`); assert `CLAUDE.md` excluded while a sibling doc file still lands — proving CLAUDE.md's outcome doesn't contaminate others and vice versa.
   - B13: assert the literal PR title (`gh.prs[0]["title"] == "Onboarding repo: agent docs and CI"`), computed independently of the result's own `files` — not derived from it.

**4. `lib/tests/test_project_onboard.py:2637`** (`test_claude_md_write_failure_leaves_it_out_of_files`) — target the fault precisely at the PUT (`fail=("message=Create CLAUDE.md",)`, which doesn't appear in the GET call), tighten the assertion to `"CLAUDE.md" not in result["files"]`, and add a positive control in the same test: a second `_apply_pr` call with a clean `FakeGitHub()` asserting `"CLAUDE.md"` **is** in `files` — proving the fault, not file-tree state, is what excluded it.

**5. `lib/tests/test_mr_raiser.py:827-844`**:
   - `test_malformed_ref_returns_none_without_crashing` → replace with a test that actually calls `mrr._ticket_title("malformed-ref")` and `mrr._subject("malformed-ref")` against a `subprocess.run` that raises (simulating `gh` failing on the malformed ref), asserting `_ticket_title` returns `None` and `_subject` returns `"Implement malformed-ref"` — exercising the real functions the docstring claims, not `raise_mr`'s overall non-crash.
   - `test_repeat_dispatch_same_ticket_succeeds` → replace with a test that calls `_default_open_pr` **twice** for the same ticket (both hit the "already exists" → edit path, since `fake_run` always raises "already exists" on create), and asserts the two `--title` values from both edit calls are identical.

**6. `lib/tests/test_mr_raiser.py:676-693`** (A6) — stop stubbing `_ticket_title` directly (duplicate of A2); instead leave it unstubbed and make `fake_run` raise specifically when the command is `gh issue view` (the dependency boundary `_ticket_title` wraps), proving its own `try/except` — not a test double standing in for it — survives the failure and falls back to `"Implement o/r#23"`.

**Also from `fix_these`: A3/A4/A5 (`:625-673`)** — add `monkeypatch.setattr(mrr, "_ticket_title", lambda ref: "Fix the bug")` to each (currently unstubbed, so they pass by reading `fake_run`'s canned PR-URL string as if it were the title).

## New tests for misuse the ticket's checklist (absent — no "How we'll try to break it" section on #454) would otherwise miss

- **dotted repo name** through `listPipelinePrs`/`normalizeTitle` (e.g. `Implement org/repo.name#5`) — extends C16, doesn't replace it.
- **false-positive guard**: a title containing `#218` without the full bare-`Implement owner/repo#n` shape (e.g. `"Implement retry logic for #218"`) must leave `ghIssueView` uncalled and the title untouched — new test alongside (not replacing) C14/C21, which already cover the true-positive and true-negative cases correctly.
- Already covered by the current B-series and A-series above: empty/malformed PR bodies (existing), each dependency (`gh`) failing (existing + #2-#6 above), repeats (new #5), a person's mistake / malformed ref (new #5).

## Decisions

None. The ticket's "What to build" and acceptance criteria are concrete and already matched by the existing (uncommitted) implementation; this round's work is entirely defect-fixing in code and tests, not new design surface.

## Task List

1. `dashboard/mobile-backend/dashboard_gh_api.js`: revert the `/mr/ticket-context` route's `ghIssueView` back to `--json 'number,title,body'` (leave the `listPipelinePrs` route's `ghIssueView` at `number,title`, unchanged).
2. `dashboard/mobile-backend/dashboard_gh_api.js` test coverage: add/extend a test asserting `fetchTicketContext` via the `/mr/ticket-context` route still resolves a `## Parent` ref (i.e. `ticket.body` is populated) — this is the test that would have caught finding #1.
3. `lib/tests/test_project_onboard.py`: rewrite `test_identical_content_skip_does_not_count_as_written` to seed `remote_files` from real `_render_agent_docs` output and assert on `files`, per Fix #2.
4. `lib/tests/test_project_onboard.py`: replace B11/B12/B13 with the three non-circular, fault-targeted tests in Fix #3.
5. `lib/tests/test_project_onboard.py`: rewrite `test_claude_md_write_failure_leaves_it_out_of_files` to target the PUT specifically and add the positive-control assertion, per Fix #4.
6. `lib/tests/test_mr_raiser.py`: stub `_ticket_title` in A3/A4/A5.
7. `lib/tests/test_mr_raiser.py`: rewrite A6 to fail at the `gh issue view` boundary instead of stubbing `_ticket_title`.
8. `lib/tests/test_mr_raiser.py`: replace the malformed-ref and repeat-dispatch tests per Fix #5.
9. `dashboard/test/mr_review.test.js`: add the dotted-repo-name and false-positive-guard tests (additions only — C14/C16/C21 stay as-is, verified correct).
10. Run `lib/tests` and `dashboard/test` in full. Before finalizing, revert each production fix one at a time and confirm its corresponding new/rewritten test fails — the sanity check the last attempt's task list promised but that still needs doing for this round's changes specifically.
11. Delete `docs/design/pipeline-g-eskayo-marvin-454-tasks.md` (leftover verbatim duplicate of a design doc's own task list, flagged by the last review as a drift risk — confirmed present and still a duplicate).
12. Retitle the 3 open pipeline PRs: `gh pr edit 400 --repo G-Eskayo/marvin --title "Stop retry storms: hold a ticket after N failed pipeline runs (#218)"`, `gh pr edit 368 --repo G-Eskayo/marvin --title "Pipeline stage strip on PR and ticket cards (GitLab-style), showing where it failed (#217)"`, `gh pr edit 359 --repo G-Eskayo/marvin --title "Usage: show how much of the allowance autonomous work uses (no cap yet) (#81)"`. Skip #358 (confirmed CLOSED). Verify each with `gh pr view <n> --json title`.
13. Screenshot evidence for the PR: MR Review tab showing (a) the existing non-marvin repo badge (pre-existing, confirmed at `MrReview.jsx:416`), (b) a card whose title now reads the real ticket title instead of a bare `Implement …#n`.