## North-star fit

**Reuses:** the whole shape of this fix already exists in the codebase, just split across two languages. `bin/gh`'s `ui_evidence_refusal()` already imports `lib/pr_images.py` and calls `pi.verdict()` in-process (north star 4: pr_images.py is already "the tool for making this kind of check"). `dashboard/webhook-server/merge.js` already calls out to other Python CLIs the same way this ticket wants pr_images called — `defaultGateContext()` (`merge.js:634`) and `generatedResolver()` (`merge.js:669`) both do `execFileAsync(VENV_PYTHON, [SCRIPT, ...]).then(JSON.parse)`, catching a non-JSON/crashed result as a failure. The new `pr_images.py check <pr-url>` CLI is the same pattern as `project_profile.py gate-info`/`verify` (plain `sys.argv` dispatch, no argparse — `lib/project_profile.py:745`) and `generated_paths.py resolve-rebase` (JSON out, non-zero exit = refuse). Nothing new is invented; this ticket moves logic, it doesn't add a new kind of thing.

**Simplest sufficient approach:** one shared Python function does the GitHub facts-lookup + verdict, called in-process by `bin/gh` and out-of-process (via a thin CLI) by `merge.js`. That is strictly less code than today: `ui_evidence.js`'s ~180 lines of link/staleness/cross-repo logic disappear; `bin/gh`'s bespoke single-repo `changed_since` closure disappears too.

**Where it spends tokens, and why:** I'm asking the owner to decide on API-call cost for the MR-review card (see Decisions below) rather than silently picking an answer, because the two options have materially different ongoing GitHub-API-budget costs, and this repo has an entire rate-limit-cooldown system (`bin/gh`) built because that budget was exhausted before.

**More capable, not more passive:** this is pure plumbing — it makes an existing owner-facing guarantee ("I never approve something I haven't actually seen") actually hold everywhere, instead of holding on one road and not another. No behavior the owner performs changes.

**Important finding that changes the shape of the fix:** `pr_images.py`'s `verdict()` is *not* just an older copy with the same rules as `ui_evidence.js` — the two have **drifted in both directions**:
- `ui_evidence.js` is missing the "blob/raw link 404s on a private repo" check that `pr_images.py` already has (`link_problem()` → `"blob"`). This is the literal bug in the issue title ("A broken image link... passes Approve" — true today, confirmed by reading `unpinnedImages()`/`imagePins()` in `ui_evidence.js`: a `github.com/.../blob/<40-hex>/...` link passes as "pinned" there).
- `pr_images.py` is missing two fixes that only ever landed in `ui_evidence.js`: cross-repo image pins (marvin#773, MARVIN's own screenshots live in `marvin-instance`, compared by commit time not by `compare`) and "only the PR's own files count toward staleness, not everything a rebase/merge of main also changed" (marvin#971). Confirmed by reading `lib/tests/test_pr_images.py` — no cross-repo test, no own-files-filter test exist there, while `dashboard/test/ui_evidence.test.js` has both (lines 200-262, 160-171).
- `bin/gh` and `dashboard/webhook-server/ui_evidence.js` also disagree **on purpose** about what "I can't tell" means: `pr_images.verdict()` treats an unresolvable `changed_since` as "pass" (bin/gh's documented policy: "Fails OPEN when GitHub can't be asked... the dashboard's Approve still fails closed" — `bin/gh:254`), while `ui_evidence.js`'s `assertUiEvidence` explicitly throws `UI_EVIDENCE_UNCHECKED` (refuse) for the same case, and the ticket's own break-test says the merge path "refuses, never passes" on an unreadable CLI result. Unifying the code must **preserve both policies**, not collapse them to one.

## Decisions

A PR carrying this fix needs the owner to pick one of these before it can be merged, since both are real, different-cost architectures, not something the ticket text settles:

<!-- marvin:decisions -->
### card-verdict-source: How should the "Needs images" card (`mr_review.js`'s `needsImages`, used for every open PR on every list refresh) get its verdict?
- [ ] A — Call `pr_images.py check <pr-url>` (a full `gh pr view` + staleness compare) for every PR, every refresh. Fully "one implementation," but adds N extra GitHub API calls per refresh purely to re-fetch data the list already has, and staleness becomes checkable on the card for the first time (a behavior change).
- [ ] B — Add a second, no-fetch CLI mode (`pr_images.py check-local`, taking files+body already in hand, no GitHub call) for the card; the full `check <pr-url>` mode (with staleness) stays merge-gate-only, matching today's explicit design note in `mr_review.js` ("Staleness needs GitHub calls, so only the gate checks it"). Recommended: zero new GitHub calls, same current behavior, still "one implementation" for the part that matters (no-image / bad-link detection), at the cost of staleness remaining gate-only on the card.
<!-- /marvin:decisions -->

I'll build against **B** unless told otherwise, since it's the lower-risk, lower-cost option and preserves a design constraint the codebase already states deliberately; if the owner picks A I'll drop the `check-local` mode and have the card call `check <pr-url>` directly.

The ticket's other named decision ("whether `merge.js` should also route through `bin/gh`") is not an owner Decision — it's an analysis the PR must state and justify in prose, per the ticket text. My answer, to put in the PR: **no, not in this PR.** `bin/gh`'s PATH/rate-limit/priority machinery is a separate, larger change (ADR 0080 lists it as its own invariant concern, not I1), and this ticket's job is narrower: one verdict, not one gh binary. Routing `merge.js` through `bin/gh` is also where `pull_only_refusal` and the hourly-budget/background-priority logic live, none of which apply to the dashboard's merge server — folding it in now would risk exactly the kind of "regressed" verdict this ticket already got twice.

## Tests (written first)

**`lib/tests/test_pr_images.py`** (extends existing file; existing `changed_since` tests get rewritten since the callback signature changes from `(sha)` to `(repo, sha)`):
1. Cross-repo pin: an image pinned in another repo, taken after the PR's last same-time commit → current, no `STALE` (ports `ui_evidence.test.js`'s marvin#773 cases).
2. Cross-repo pin older than the PR's own last-prior commit, and that prior commit lacks the look change → current.
3. Cross-repo pin, a look-changing file appears between the matched prior commit and head → `STALE_UI_EVIDENCE`, naming the file.
4. Cross-repo pin whose own repo can't find the commit → `STALENESS_UNCHECKED` (not silently "pass").
5. Same-repo compare lists files that only changed via a merge of main, not the PR's own files → not stale (ports marvin#971).
6. Same-repo compare lists a file the PR itself also changed, among main's → still `STALE_UI_EVIDENCE`, naming only the PR's own file.
7. `changed_since` returns `None` for a same-repo pin → `STALENESS_UNCHECKED`, not swallowed to "pass" (this is the behavior-preserving test: bin/gh's caller must now explicitly choose to ignore this code; nothing ignores it implicitly).
8. A `github.com/.../blob/<sha>/...` link (any repo, any SHA) is always `BAD_IMAGE_LINK` — the fix for the issue's headline bug, tested at the shared-function level so both callers inherit it.
9. `pr_images.py check <url>` CLI, invoked as a subprocess against a stub `gh`: prints valid JSON `{"problems": [...]}` for a clean PR, a no-image PR, a bad-link PR, and a stale PR.
10. CLI with no UI-touching files: exits 0, prints `{"problems": []}`, and makes **no** `gh api compare`/`commits` calls (only the one `pr view`) — ports the existing "a non-UI PR is never asked about its images" optimization.
11. CLI whose underlying `gh pr view` call fails, times out, or the stub prints garbage: non-zero exit / no parseable JSON (this is what `merge.js` must treat as fail-closed).
12. CLI malformed input: PR URL with no number, a private/nonexistent repo, huge body (10k images) — doesn't crash, degrades to a reasonable refusal or `STALENESS_UNCHECKED`, never a stack trace on stdout.

**`lib/tests/test_gh_gate.py`** (existing `ui_evidence_refusal` tests, adjusted to the new shared function; add):
13. A PR whose images are pinned in another repo, opened via `pr create` through `bin/gh` → now correctly judged (today it silently can't do this at all — a real capability gain, test that it doesn't regress to "fails open on everything").
14. `STALENESS_UNCHECKED` from the shared function → `bin/gh` still lets the call through (fails open), unchanged from today.
15. Everything currently in this file keeps passing unmodified in spirit (same refusal codes/messages for the cases it already covered), since `ui_evidence_refusal` is now a thinner wrapper around the same shared function, not a rewrite of policy.

**`dashboard/test/ui_evidence.test.js` / `merge.test.js`** (near-total rewrite of the `assertUiEvidence` describe-blocks, since `exec` now mocks a CLI subprocess call instead of raw `gh` calls):
16. `assertUiEvidence` spawns `pr_images.py check <url>` exactly once (plus the extra `uiPaths` args), not per-link/per-pin `gh` calls directly — the gate's own GH calls move entirely into the stubbed CLI boundary.
17. CLI returns a `NO_UI_EVIDENCE` problem → `MergeFailure` with that code and **pr_images' own message text** (the "same message on both roads" acceptance criterion — the previous bespoke JS wording goes away).
18. CLI returns `BAD_IMAGE_LINK` for a `blob/...?raw=true` or a repo-relative path → refused, same message pr_images would give `bin/gh`.
19. CLI returns `STALE_UI_EVIDENCE` → refused.
20. CLI returns `STALENESS_UNCHECKED` → refused (fails closed — this is the one place `merge.js`'s policy must differ from `bin/gh`'s).
21. CLI process rejects (non-zero exit), times out, or its stdout isn't JSON → `UI_EVIDENCE_UNCHECKED`, refused, never passes.
22. CLI returns `{"problems": []}` → resolves, no refusal.
23. `uiPathsFor`'s extra patterns are passed through to the CLI call and honoured identically to today (a project's own `evidence.ui_paths`).
24. `mergePr` still refuses before any gate work starts, same as the existing `mergePr refuses before any gate work or merge` test.
25. (if Decision = B) `needsImages()` in `mr_review.js` calls `pr_images.py check-local` with the PR's already-known `files`/`body` — zero extra `gh` calls for the list — and its result (`{files}` / `{files, unpinned}` / `null`) matches today's shape exactly, so `prState.js`/`MrDetail.jsx`/`WorkshopItem.jsx` need no changes.
26. (if Decision = A) `needsImages()` is now async, calls `check <pr-url>`, and a failing/slow lookup for one PR never blocks or breaks the rest of the list render.
27. A project profile adding its own `evidence.ui_paths` is honoured identically on both the card and the merge path for the same PR (the issue's explicit break-test).
28. A PR with no UI files passes on both roads with no image required (the issue's explicit break-test), verified via one shared fixture PR body/files used against both the CLI-mock and the real `pr_images.py check-local`/`check` path in a light integration test.

**`lib/tests/test_work_loop_e2e.py`** (new "I1 current evidence" section, following the existing I2 section's shape):
29. A fake `gh` is extended to answer `pr view`/`api compare`/`api commits` with scripted JSON (not just `{}`), keyed by call shape — a new fixture, `github_i1`, built on the existing `github` fixture's recording behaviour.
30. A chat-opened PR (`bin/gh pr create` with a `blob/...?raw=true` image) against the fake GitHub → refused, `BAD_IMAGE_LINK` (or equivalent bin/gh-side code), same message `pr_images.py` would give.
31. The **same** fake-GitHub fixture driven through `pr_images.py check <url>` directly (standing in for the dashboard merge road, since this file has no Node harness) → refused with the identical code and message as test 30 — this is the literal "two roads, one code" proof the ticket asks for.
32. A stale-image case (same fixture data) refused identically on both roads.
33. A clean PR (no UI files) passes on both roads, no GitHub calls beyond the minimum.

**Misuse cases not named in the ticket, added per the "tests try to break it" rule:**
34. PR body with thousands of image tags (a malformed/huge PR description) — the CLI finishes in bounded time, doesn't hang on regex backtracking.
35. Two concurrent `check` CLI invocations (two Approves at once, or a chat PR + a dashboard Approve racing) — each is independent (no shared mutable state in `pr_images.py`; it opens no lock files), so no cross-talk.
36. `gh` on PATH inside the CLI subprocess is itself `bin/gh` (recursion risk) — `pr view`/`api` calls aren't in `ui_evidence_refusal`'s trigger list (`pr create/ready/merge` only), so this is a non-issue; add a regression test proving a `check` call never recurses into the UI-evidence gate.
37. The PR's repo is private and the CLI's `gh` call lacks a valid token → the underlying `gh` call fails → CLI exits non-zero → fails closed, same as test 11.
38. A PR URL that doesn't parse (not `github.com/.../pull/N`) → CLI refuses to run, clear error, non-zero exit, no GitHub call at all.

## Task List

1. **`lib/pr_images.py`**: generalize `_RAW` to capture `(owner/repo, ref)`; add a repo-aware pin extractor; rewrite the staleness branch of `verdict()` to take `changed_since(repo, sha)` and intersect results with the PR's own `files` (port marvin#971); introduce `STALENESS_UNCHECKED` as an explicit problem code instead of silently returning `[]` on an unresolvable pin.
2. **`lib/pr_images.py`**: add one shared function (e.g. `pr_facts_and_verdict(pr_url, ask, extra_patterns=())`) that does the open-PR facts lookup (files/body/head), the per-pin same-repo `compare` or cross-repo commit-time lookup (port marvin#773 from `ui_evidence.js`), and calls `verdict()` — parameterized by an injectable `ask(args) -> dict` so both `bin/gh` and the new CLI share it.
3. **`lib/pr_images.py`**: add the `check <pr-url> [extra-pattern ...]` CLI entry point (and, per Decision B, `check-local` reading files+body without a GitHub call), printing `{"problems": [{"code", "message"}, ...]}`, non-zero exit / non-JSON on an unrecoverable top-level fetch failure.
4. **`bin/gh`**: rewrite `ui_evidence_refusal()` to call the new shared function instead of its own single-repo `changed_since` closure; keep its own documented fail-open policy by explicitly treating `STALENESS_UNCHECKED` as "no refusal."
5. **`dashboard/webhook-server/ui_evidence.js`**: delete `link_problem`-equivalent/staleness/cross-repo logic; `assertUiEvidence` becomes a thin `execFileAsync(VENV_PYTHON, [PR_IMAGES_SCRIPT, 'check', prUrl, ...uiPaths])` call, mapping the CLI's problems (including a crashed/non-JSON/non-zero result) to the existing `MergeFailure`/`refusal()` codes, using pr_images' own message text. Keep `uiFiles`/`hasImage`/`unpinnedImages` exported only if Decision = B requires them for the card's local path; otherwise remove.
6. **`dashboard/electron/main/mr_review.js`**: `needsImages()` gets its verdict from the CLI per the Decision (local, no-fetch mode for B; per-PR `check <url>` for A), keeping its existing `{files}` / `{files, unpinned}` / `null` output shape so `prState.js`, `MrDetail.jsx`, `WorkshopItem.jsx` need no changes.
7. **`lib/tests/test_pr_images.py`**: rewrite affected `changed_since`-based tests for the new 2-arg signature; add tests 1–12.
8. **`lib/tests/test_gh_gate.py`**: add tests 13–15.
9. **`dashboard/test/ui_evidence.test.js` / `merge.test.js`**: rewrite the `assertUiEvidence`/`mergePr` describe-blocks around the CLI boundary; add tests 16–28.
10. **`lib/tests/test_work_loop_e2e.py`**: add the "I1 current evidence" section, the `github_i1` fixture, and tests 29–33.
11. Add tests 34–38 (misuse/adversarial cases) across the Python and JS suites as appropriate.
12. Run the full `lib/tests` suite and the dashboard's full test suite; confirm green.
13. Write the PR body: state the `bin/gh`-routing analysis (answer: no, not in this PR, and why), name which Decision option was taken, and link ADR 0080 / this ticket.