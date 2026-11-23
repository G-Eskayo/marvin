## North-star fit

- **Reuses before adding:** the pipeline-branch regex shape from `lib/incident_ladder.py:179-180` (`_pipeline_branch`), the hidden-marker/"bot comment" idiom already in `lib/ticket_policy.py` (`SENT_BACK_MARKER`, `REPAIRED_MARKER`, `automated_comment()`), and the single-issue comment-fetch pattern already used in `lib/ticket_pipeline.py`'s `_pr_retry_wait` (~line 713-725). No new file, no new abstraction — this extends `lib/ticket_evidence.py` and `lib/ticket_pipeline.py`, the two files the bug already lives in.
- **Simplest sufficient approach:** the root cause is one over-loose regex (`_named`) plus two missing real-link signals (`part of`, GitHub's own linked-issue field) plus a cross-repo mention gap. All four are small, local, deterministic regex/field fixes — no new service, no ML, no schema change. Verified directly against the real failing PR (`gh pr view 267 --repo G-Eskayo/clarity-captions`), not guessed.
- **Token/compute cost:** stays flat. The extra `closingIssuesReferences` field rides the same two `gh pr list` calls `gather()` already makes (no new call). The new "flag it" comment only does one extra `gh issue view --json comments` + one `gh issue comment`, and only when verdict is actually `looks-done` (rare) — not per scan.
- **Phone-OS / capability:** this is pipeline plumbing, neutral on that axis, but it directly serves north star 3: a silently dropped ticket (#10, "keep captioning alive through lock/background/calls") makes Gil *less* able until this is visible — the new comment turns a silent, permanent-looking drop into something a person sees and can act on.

## What's actually broken (verified against the real PR)

`gh pr view 267 --repo G-Eskayo/clarity-captions` shows: `headRefName: "release/1.1.0-10"`, body says `"Part of #167"` (the real release ticket) and contains `"1.1.0 (10)"` several times but no `"#10"` anywhere. So:

1. **The false positive's real cause**: `_named()` in `lib/ticket_evidence.py` is `re.search(r"[/-]{n}(?!\d)", ref)` — it matches *any* branch ending in `-N` or `/N`, regardless of whether it's a pipeline branch. `"release/1.1.0-10"` trips it for ticket `10` even though it has nothing to do with the pipeline's own naming.
2. **A second, latent gap this exposes**: the pipeline's real branch convention (`lib/sandbox_orchestration.py:391-392`, `_branch_for`) produces `pipeline/<owner>/<repo>#<N>` — confirmed live (`gh pr list --repo G-Eskayo/marvin --state merged`: `pipeline/g-eskayo/marvin#1317`, etc.). `_named`'s char class `[/-]` never matches the `#` that actually precedes the ticket number in real branches, so today it *also* fails to recognize genuine pipeline branches as "named for" their own ticket. Fixing `_named` properly should close both gaps at once (tightening against the false positive, widening to the real `#`-based convention) rather than just patching the symptom.
3. **"Part of #N" isn't a recognized claim verb** — `_WORK` in `ticket_evidence.py` lists `close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|references|implements|addresses` but not `part of`. So the real PR's own genuine link (`"Part of #167"`) wouldn't count as evidence for #167 either — the opposite kind of bug, but same root gap.
4. **Cross-repo bare mentions aren't guarded.** `_mentions`/`_claims` match a bare `#{n}` with no check on what's immediately before the `#`. `"Part of clarity-captions#10"` contains the substring `#10`, so if that text ever appears in an **open** PR's body in another repo, `_mentions` (used for in-flight, no verb required) would wrongly fire for the current repo's ticket #10.
5. **GitHub's own linked-issue field isn't read at all.** `gather()`'s `gh pr list --json` call only fetches `number,body,headRefName`; the ticket's "What to build" explicitly lists GitHub's linked-issue field as a third valid real-link source. Confirmed live that `gh pr list --json ...,closingIssuesReferences` works and returns `{number, repository:{name, owner:{login}}}` per linked issue — naturally repo-scoped, so it's cross-repo-safe for free.
6. **No visibility when a skip happens.** `_unclaimed_ready_tickets()` in `lib/ticket_pipeline.py` only does `print(..., file=sys.stderr)` on a `looks-done` skip — nothing is posted to the ticket. That's the acceptance criterion's second half, entirely unbuilt.

Title text is **not** currently read anywhere (`gather()` never fetches `title`), so the "(10)" and "(#12 notes)"-style title patterns in the ticket's break-it list can't reach the matcher today — the risk is that a future change starts passing title through the same loose matchers. The fix below (tightening `_named`, adding the cross-repo lookbehind) protects against that by construction; I'm also adding one explicit regression test pinning "title text is never consulted" so a later change can't reintroduce it silently.

## Decisions

None needed. Every open question below was resolvable from existing code/data, not a design fork for the owner:
- Dedup strategy for the new comment: GitHub-comment-marker based (reads the thread itself), not a local JSON file, because this pipeline runs on more than one Mac and a local dedup file wouldn't be shared between them — same reasoning as the existing cross-machine `RETRY_MARKER`/`SENT_BACK_MARKER` pattern already in `ticket_policy.py`.
- What the comment names when verdict is `looks-done` via a bare commit (no PR involved): names whichever evidence item actually matched (PR *or* commit ref), generalizing "naming the PR" to "naming the match" — same intent (make a wrong match visible), same mechanism, no extra branch of behavior.

## Tests first

All in `lib/tests/test_ticket_evidence.py` unless noted. Each maps to a break-it case or a misuse the section didn't spell out.

1. **(ticket break-it #1)** `test_version_build_number_in_branch_name_is_not_a_ticket_match` — merged PR with `headRefName="release/1.1.0-10"`, body containing `"1.1.0 (10)"` and `"## What's in 1.1.0 (10)"` but no `#10`: `evidence_for(10, facts) == []`. This is the literal PR #267 shape — the regression test for the reported bug.
2. **(ticket break-it #1, variants)** `test_bare_paren_or_hash_in_a_version_like_title_text_never_marks_done` — same check against `"Build 12 (#12 notes)"` and `"v2 (#3)"` appearing in a PR body (title is never fetched, so this is the closest reachable proxy): no verb precedes the `#`, so no match for 12 or 3.
3. **(ticket break-it #2)** `test_real_closes_in_body_still_counts` — unaffected by the branch-name fix: `"Closes #10"` in body still yields `looks-done`/`in-flight` as appropriate (guards against overcorrecting).
4. **(ticket break-it #3, cross-repo)** `test_cross_repo_mention_in_body_does_not_mark_the_local_ticket_done` — open PR body `"Part of clarity-captions#10"`, checked against local ticket `10`: `evidence_for(10, facts) == []` (currently fails — the uncovered `_mentions` gap).
5. **(ticket break-it #3, cross-repo, the other direction)** `test_closing_issue_reference_is_repo_scoped` — `closingIssuesReferences` entry pointing at a *different* repo/number must not count for the local repo's same-numbered ticket.
6. `test_part_of_is_a_recognized_claim_verb` — merged PR body `"Part of #167"`: `verdict(evidence_for(167, facts)) == "looks-done"`.
7. `test_real_pipeline_branch_naming_convention_is_recognized` — headRefName `"pipeline/g-eskayo/clarity-captions#10"` (the real, live-confirmed convention) is recognized as `in-flight`/`branch`/`merged-pr` as appropriate — pins the widened half of the `_named` fix, not just the narrowed half.
8. `test_old_hyphenated_pipeline_branch_fixture_still_matches` — the existing `FACTS` fixtures (`"pipeline/clarity-captions-21"` etc.) keep passing unmodified — no regression on already-covered conventions.
9. `test_closing_issues_reference_on_open_pr_means_in_flight` / `test_closing_issues_reference_on_merged_pr_means_looks_done` — the new GitHub-linked-issue signal, both states.
10. **(malformed/empty input)** `test_evidence_for_tolerates_missing_or_malformed_closing_issues_references` — `closingIssuesReferences` missing, `None`, `[]`, or entries missing `repository`/`number` keys: no crash, no false match.
11. **(person's mistake / case)** `test_repo_matching_is_case_insensitive` — `facts["repo"]="G-Eskayo/Marvin"` vs a closingIssuesReferences repo `{"name":"marvin","owner":{"login":"g-eskayo"}}` still matches.
12. `test_report_and_verdict_are_unaffected_by_the_new_repo_key` — `report()`/`verdict()` behavior for existing FACTS (no `"repo"` key) is unchanged (`facts.get("repo", "")` default doesn't blow up or over-match).

In `lib/tests/test_ticket_pipeline.py` (the new "post one comment" deliverable):

13. `test_looks_done_skip_posts_one_comment_naming_the_match` — verdict `looks-done` via a merged-pr match: exactly one `gh issue comment` call is made, its body names the PR.
14. **(repeats)** `test_looks_done_skip_does_not_repost_when_already_flagged` — issue's existing comments already contain the marker + that same PR ref: a second scan posts nothing (idempotency across repeated scans, since this runs on a loop).
15. `test_looks_done_skip_reflags_when_the_matched_pr_changes` — a prior flag names PR #267; evidence now matches a *different* PR #300: a new comment is posted (a different wrong match deserves its own visibility).
16. **(in-flight is explicitly out of scope for the comment)** `test_in_flight_skip_posts_no_comment` — verdict `in-flight` never triggers this comment path.
17. **(dependency failure)** `test_looks_done_skip_tolerates_gh_failure_without_crashing_the_scan` — the comment-fetch or comment-post subprocess call fails (non-zero / raises): `_unclaimed_ready_tickets()` still returns the correct filtered list; nothing propagates.
18. **(malformed dependency response)** `test_looks_done_skip_tolerates_non_dict_comments_json` — covers the real interaction with existing stub-style tests (`_stub_issues`) that return a bare JSON list for every `subprocess.run` call regardless of args; must not crash when parsing that as "comments".
19. In `lib/tests/test_ticket_policy.py`: `test_automated_comment_classifies_the_looks_done_flag_as_bot` — the new marker/comment shape returns `"bot"` from `automated_comment()`, so it can never be mistaken for a person's reply and wrongly stop `run_ticket._trailing_streaks`' failure-streak walk (verified real consumer: `lib/run_ticket.py:137`).

## Task List

1. `lib/ticket_evidence.py`: widen the `#`-aware, prefix-anchored `_named()` (requires a `pipeline/` segment; accepts `#`, `-`, or `/` as the separator before the ticket number) — fixes the reported false positive and the latent real-convention gap in one change.
2. `lib/ticket_evidence.py`: add a shared "not glued to a repo slug" lookbehind to `_mentions()` and `_claims()`'s `#{n}` matching, so a cross-repo mention like `clarity-captions#10` can't satisfy a bare `#10` check.
3. `lib/ticket_evidence.py`: add `part of` to the `_WORK` verb alternation.
4. `lib/ticket_evidence.py`: in `gather()`, add `closingIssuesReferences` to both `gh pr list --json` field lists (open and merged), and stash `facts["repo"] = repo`.
5. `lib/ticket_evidence.py`: add a `_links_repo(ref_list, repo, n)` helper and use it (alongside the existing checks) in `evidence_for()`'s open-pr and merged-pr branches.
6. `lib/ticket_policy.py`: add `LOOKS_DONE_MARKER` and extend `automated_comment()` to classify comments carrying it as `"bot"`.
7. `lib/ticket_pipeline.py`: add a `_flag_looks_done(repo, number, ev)` helper (mirrors `_pr_retry_wait`'s single-issue comment fetch) that checks the ticket's existing comments for the marker + the current match's ref, and posts one `gh issue comment` naming it when not already present; wrapped so any `gh` failure or unexpected response shape is swallowed, never raised.
8. `lib/ticket_pipeline.py`: in `_unclaimed_ready_tickets()`, call `_flag_looks_done` exactly when `ticket_evidence.verdict(ev) == "looks-done"` (not `in-flight`), right where the existing skip is logged.
9. Write all 19 tests above first (red), then make the above changes green; run the full `lib/tests/test_ticket_evidence.py`, `test_ticket_pipeline.py`, and `test_ticket_policy.py` files to confirm no pre-existing test regresses.
10. Update `CONTEXT.md`'s "Pre-dispatch 'work already exists' guard" entry (line ~1497-1499) to mention the branch-naming/cross-repo/linked-issue tightening and the new flag-comment, per the repo's domain-doc convention.