## North-star fit

**Reuses before adding anything new:**
- `lib/auto_merge_regression.py`'s `_BRANCH = re.compile(r"^pipeline/(?:[\w.-]+/[\w.-]+#)?(\d{1,7})$")` (and the identical `_pipeline_branch` in `lib/incident_ladder.py`) — the codebase's one existing, trusted definition of "a branch really named for ticket N". `ticket_evidence._named()` currently uses its own much looser `[/-]{n}(?!\d)`, which is the actual root cause (see below). I adapt the canonical pattern (prefix-tolerant, since `_named` is called on `origin/pipeline/...` and `refs/rescue/pipeline/.../<ts>` strings too, not just bare `headRefName`) instead of inventing a new one.
- `lib/ticket_pipeline.py`'s existing `_flagged_before`/`_mark_flagged` (already used to flag-once a hand-made-PR-conflict comment) for the new "one comment on looks-done" requirement, instead of a new state file.
- No new files, no new config, no feature flag.

**Root cause, confirmed against the real incident (PR G-Eskayo/clarity-captions#267):** its body never contains the literal string `#10` (only `(10)`/`1.1.0 (10)`), and `_claims`/`_commit_claims` already require a literal `#N`. The match came from `headRefName: "release/1.1.0-10"` through `_named`'s loose regex: `[/-]10(?!\d)` matches the `-10` tail of a version-build string, because the regex isn't anchored to the real `pipeline/...` branch convention at all. This is a one-function bug, not a title problem — `gather()` never even fetches PR `title` into facts, so titles are structurally already excluded from every check.

**Second gap required by the ticket's own break-list** ("marvin PR 'Part of clarity-captions#10' doesn't mark marvin#10 done"): `_mentions()` (used for open-PR "in-flight" evidence) does a bare `#{n}` search with no left boundary, so `clarity-captions#10` inside a same-repo PR body would wrongly count toward ticket `#10`. `_claims()` is already incidentally safe here (its regex only allows whitespace/colon between the work-verb and `#N`), but I add the same boundary guard there too for defense-in-depth at the one place both checks build their regex.

**Simplest sufficient approach:** two regex tightenings in `ticket_evidence.py`, no behavior change to the already-correct commit/`_claims` logic, plus ~10 lines in `ticket_pipeline.py` reusing existing flag-dedup machinery for the comment requirement.

**Cost:** negligible — the extra `gh issue comment` call fires at most once per (ticket, evidence-ref) pair, not per scan.

**Capability:** this was found by Gil manually reading `ticket-pipeline-error.log` — after the fix, a wrong match posts a visible comment on the ticket itself, so he doesn't have to grep logs to catch it again. Reliability precondition of north star 2 ("nothing may break silently").

**No decisions needed** — the ticket's "What to build" and break-list are concrete and leave no open design choice for the owner.

## Tests first

In `lib/tests/test_ticket_evidence.py`:
1. Update the stale `FACTS` fixture's branch/rescue entries (`"origin/pipeline/clarity-captions-21"`, `"refs/rescue/pipeline/clarity-captions-23/..."`) to the real convention (`"origin/pipeline/21"`, `"refs/rescue/pipeline/23/..."`) — the old dash-style strings are test-only fiction that doesn't match any branch the pipeline actually creates (`sandbox_orchestration.py:392`, `project_profile.py:665` both emit `pipeline/<N>` or `pipeline/<owner>/<repo>#<N>`), and they're what let the loose regex pass undetected.
2. **Reproduce the incident exactly**: merged PR with `headRefName: "release/1.1.0-10"` and the real PR #267 body text (no `#10` anywhere) → `evidence_for(10, facts) == []`.
3. Parametrized: branch names `"build-12"`, `"v2-3"`, `"release/1.1.0-10"` never mark tickets 12, 3, 10 — the ticket's three literal examples, applied to the real mechanism (branch naming), since titles are already never fetched.
4. Positive control: canonical branches `"pipeline/21"` and `"pipeline/g-eskayo/marvin#21"` still produce evidence (open-pr/merged-pr/branch/rescue) — proves the tightening didn't overcorrect.
5. A real `"Closes #10"` body still counts (already covered by existing tests — rerun, don't weaken).
6. Cross-repo: open-PR body `"Part of clarity-captions#10"` produces no evidence for ticket 10 (`_mentions` boundary fix).
7. Cross-repo: merged-PR body `"Closes clarity-captions#10"` produces no evidence for ticket 10 (`_claims` boundary fix / regression guard).

In `lib/tests/test_ticket_pipeline.py`:
8. New autouse fixture that no-ops `tp._flagged_before`/`tp._mark_flagged` by default (mirrors the two existing conflict-flag tests that already monkeypatch these explicitly) so no test in this file writes to the real `FLAGGED_PATH` now that `_unclaimed_ready_tickets` also calls them.
9. A ticket skipped as `looks-done` gets exactly one `gh issue comment <n> --repo <repo> --body ...` call naming the matching PR/commit.
10. A second scan with the same evidence does not comment again (dedup via `_flagged_before`).
11. A ticket skipped as `in-flight` never triggers a comment (scoped to `looks-done` only, per the ticket).
12. A failing `gh issue comment` (non-zero exit) does not call `_mark_flagged` (so it retries next scan) and does not raise/crash the scan.

## Decisions
None — nothing ambiguous to put to the owner.

## Task List
1. `lib/ticket_evidence.py`: replace `_named()`'s loose `[/-]{n}(?!\d)` with the canonical, prefix-tolerant pipeline-branch pattern (`(?:^|/)pipeline/(?:[\w.-]+/[\w.-]+#)?{n}$`), reused from `auto_merge_regression._BRANCH`/`incident_ladder._pipeline_branch`.
2. `lib/ticket_evidence.py`: add a `(?<![\w/-])` left-boundary guard before `#{n}` in both `_mentions()` and `_claims()` so a ticket number glued to a repo slug (`clarity-captions#10`) never counts as same-repo evidence.
3. `lib/tests/test_ticket_evidence.py`: fix the stale branch fixtures and add tests 2–7 above.
4. `lib/ticket_pipeline.py`: add `_flag_looks_done(repo, n, evidence)` next to `_flagged_before`/`_mark_flagged`, posting one `gh issue comment` naming the PR/commit, gated by `_flagged_before`/`_mark_flagged` keyed on `f"looks-done:{repo}#{n}"` → the evidence ref; mark flagged only on a successful `gh` call.
5. `lib/ticket_pipeline.py`: in `_unclaimed_ready_tickets()`'s existing skip branch, call `_flag_looks_done` when (and only when) `ticket_evidence.verdict(ev) == "looks-done"`.
6. `lib/tests/test_ticket_pipeline.py`: add the autouse no-op fixture (test 8) and new tests 9–12.
7. `CONTEXT.md`: amend the "Pre-dispatch 'work already exists' guard (2026-10-05)" entry to state that branch/PR matching requires the ticket's real `pipeline/<N>` (or `pipeline/<owner>/<repo>#<N>`) naming or a work-verb link — never a bare version/build number — and that a `looks-done` skip now leaves one comment on the ticket naming the match (closes #1270).
8. Run `lib/tests/test_ticket_evidence.py` and `lib/tests/test_ticket_pipeline.py` in full, plus the module's existing full suite, before calling this done.