## North-star fit

**Reuses before adding anything.** I re-read every file this ticket touches against the actual worktree state (not the prior design doc's claims about it) and the review comment that failed this attempt. The architecture from ADR 0065 is sound and already built: `claims.py`'s `CLAIMS` list, `collect()`, the nightly `job_events.job_run()` wrapper, the `portfolio.js`→`PortfolioHub.jsx` wiring, the launchd plist, `health_checks.py`'s `JOB_PLACEMENT` entry. Most of the previous iteration's fixes (sys.path, `check_claim_ticket_done`'s `parse_stage_key` use, `check_no_failed_stages`' latest-stage-only logic, the plist's `EnvironmentVariables` block, "local time" wording) **are already correctly in place** — I verified each one against the code rather than assuming either the prior doc or the review's line numbers were still current. What's left is exactly the 6 must-fix defects the review found, which are narrow and mechanical: a test with a wrong argument order, a test that masks its own target bug, a hardcoded date, a missing `NaN`/clock-skew guard, a regex anchor that fails next to punctuation, and a UI field that's read but never rendered. No new architecture, no new files beyond one small test file for two new pure JSX exports.

**Simplest sufficient approach.** Every fix is a 1-10 line change plus a test that fails before the fix and passes after. I also checked three things the review flagged as "notes" rather than must-fix, and two of them turn out not to be real: `runs[-1]` ordering is already correct (`job_events.py` always appends, `status_of()` relies on the same assumption), and `check_marvin_link`'s findings-based check is **not** a vacuous placeholder — `portfolio_content.py:124-128` already computes `marvin-link-missing` from real HTML link-checking, so claims.py correctly reuses it; only the inline comment is stale and misleading, so I'm fixing the comment, not the logic. The third note — `run.fail()` marking the whole nightly job "failed" whenever any claim fails — **does** contradict ADR 0065's own stated philosophy ("Claims failures are not failures of MARVIN itself") and would alert cron-health every night a claim is red; it's a one-line removal with a direct textual citation to back it, not a judgment call, so I'm fixing it rather than filing a fourth attempt over it. `flag_for_redraft` is an unreferenced stub; deleting it is dead-code cleanup, not a decision.

**Tokens.** Zero LLM calls in this layer, unchanged. The fixes are all local pattern/logic corrections against code and tests I've already read line-by-line — cheaper than another blind pass, and cheaper than re-deriving the whole design a third time.

**More capable, not more passive.** Once the scanner's boundary bug is fixed, Gil actually sees ticket references that currently slip past detection (anything after punctuation, at line starts, in parens) — closing the exact gap the ticket exists to close. The nightly-job fix stops a false "MARVIN is broken" signal from firing every night a portfolio claim goes stale, which is the kind of silent-but-wrong state the north stars explicitly forbid.

## Decisions

None needed. I checked every review finding against the actual code and the already-accepted ADR/CONTEXT.md text: each one is either a straightforward bug fix against already-decided behavior (the must-fix list, the `run.fail()` contradiction, the stale `check_marvin_link` comment) or already resolved in this worktree and not actually broken (`runs[-1]` ordering). None require Gil to pick between live options — there's one correct fix in each case, derivable from code already in the tree.

## Tests to write first

Each test below is named for the exact defect it must fail against before its fix lands.

**Review defect — `claims.py` scanner regex boundary (currently `\b(ADR|PR)?\s*#(\d+)\b`, fails whenever a non-word character sits directly before an unprefixed `#`, since `#` itself is non-word and `\b` needs a word/non-word transition):**
1. `"(#97)"` → `97` is found, not silently dropped.
2. `"#97 is the ticket."` (bare number at the very start of the text) → found.
3. `"tickets: #97"` → found.
4. `"/#97"` → found.
5. `"Fixed in PR #123. See PR #97 for context."` → both excluded (regression, prefix path still works after the anchor changes).
6. `"Per ADR 0065, fixed in ADR #97."` → `97` excluded via the `ADR` prefix path (regression).
7. 50,000-char HTML blob scans within a fixed time bound (no catastrophic backtracking from the new lookbehind).
8. Malformed/unclosed HTML (`"<p>broken<div>#44"`) doesn't raise, and `44` is still found once tags are stripped.

**Review defect — `test_claims.py` test 3's argument-order bug (passes the `job_events`/`ticket_stages` fixture into the `portfolio` slot, so every such check hits its own `except Exception`, returns `"check failed: ..."`, and the test's only assertion — `"pass" in result` — is satisfied by the error path itself):**
9. For every `CLAIMS` entry, call `check` with the fixture in the slot matching its `gather_key`, and assert `detail` does **not** start with `"check failed:"` — this is what the old test should have asserted and didn't, so it's the one that would have caught the regression.

**Review defect — `test_subprocess_claims_script_resolves_sys_path` sets `PYTHONPATH` itself (masking the exact bug it exists to catch) and only requires "no Traceback in stderr" (tolerating a nonzero exit it never actually inspects), while also letting `_gather_portfolio()` reach the real portfolio repo on disk:**
10. Same subprocess invocation, but with no `PYTHONPATH` in `env`, `MARVIN_PORTFOLIO_PATH` pointed at an empty scratch directory (isolating the real collaborator), `cwd` outside the repo, and `-I` on the interpreter — assert `returncode == 0` and `json.loads(stdout)` succeeds with a `"claims"` key. Reverting the `sys.path.insert` fix makes this fail with `ImportError` and a nonzero exit, which the new assertion actually checks.

**Review defect — hardcoded absolute timestamp in `portfolio.test.js` (`'2026-10-10T02:30:00+00:00'`), which starts failing on its own once that moment is >25h in the past, plus a duplicate "ledger missing" test across two `describe` blocks:**
11. Merge the two `claims ledger` describe blocks into one; the "reads the ledger" test uses `new Date(Date.now() - 2*3600*1000).toISOString()` (always 2h old, never flakes with wall-clock time) instead of a fixed date.
12. Drop the duplicate "missing file → null" test (kept once).

**Review defect — `claimsReport()` doesn't reject an invalid timestamp string (`new Date("garbage")` is a truthy `Invalid Date`, so `ageHours` is `NaN`, `NaN > 25` is `false`, and the stale report is returned — rendering literal "Invalid Date" in the UI) or a future timestamp (negative age from clock skew):**
13. `claimsReport()` returns `null` when `timestamp` is an unparsable string (e.g. `"garbage"`).
14. `claimsReport()` returns `null` when `timestamp` is in the future (e.g. `Date.now() + 3600000`).
15. (Keep, unchanged) returns the report when recent; returns `null` when stale (>25h), missing timestamp, or corrupt JSON.

**Review defect — `PortfolioHub.jsx` never renders `report.unregistered` despite CONTEXT.md/ADR 0065 both promising it, and only ever shows `✓`/`✗`, never the word "Untrue":**
16. New exported `claimStatusLabel(pass)` returns `"Untrue"` for `false`, a passing label for `true`.
17. New exported `formatClaimTimestamp(ts)` returns a safe fallback (not `"Invalid Date"`) for a missing/malformed timestamp, the real formatted string for a valid one.
18. New exported `UnregisteredClaims({ items })` renders each item from a non-empty list, renders nothing (`''`) for an empty/missing list.
19. Wired into `Content()`: with `claims.unregistered = ['marvin-97']` in the loaded report, the rendered claims section's markup contains `marvin-97` (closes the loop the old doc's tests 20-25 described but never actually wired through to a reachable assertion).

**Self-found — `run.fail()` in `--nightly` marks the whole job "failed" whenever any individual claim fails, contradicting ADR 0065's own "claims failures are not MARVIN failures":**
20. `main(["--nightly"])` with gather functions monkeypatched so every claim fails still records `status: "passed"` in `job_events` (with the fail/pass counts still visible in `summary`).
21. `main(["--nightly"])` with `collect()` monkeypatched to raise still records `status: "failed"` with the real error — a genuine crash still surfaces, only a false/unbacked claim does not.

**Adversarial categories the review didn't name but the ticket's own "tests try to break it" standard requires:**
22. `collect()` called twice in a row produces two independent reports (no leaked module-level state) — repeats.
23. `collect()` with one gather function returning `None` (e.g. `portfolio_content.evaluate()` raising) still returns a report with the other two sources' claims intact — one dependency failing doesn't blank the rest.

**Verify fails when code changes without a test changing:** each numbered test above is pinned to one line/behavior (the regex, the argument order, the subprocess isolation, the hardcoded date, the `NaN`/clock-skew guard, the unregistered rendering, the `run.fail()` call) — reverting any one of them breaks exactly the test(s) listed under it.

## Task List

1. Fix the scanner regex in `claims.py` (`scan_for_unchecked_claims`): replace the leading `\b` with `(?<!\w)` immediately before the optional prefix group, keeping the trailing `\b` after the digits. Write tests 1-8 first.
2. Fix `test_claims.py` test 3 (`test_3_check_functions_return_dict_result`): keep the correct per-`gather_key` argument slotting it already uses, but add the `"check failed:"` assertion (test 9) that actually exercises the regression this test exists to catch.
3. Fix `test_subprocess_claims_script_resolves_sys_path`: drop `PYTHONPATH` from `env`, add `MARVIN_PORTFOLIO_PATH` pointed at an empty scratch dir, run with `-I` and `cwd` outside the repo, and tighten the assertion to `returncode == 0` + valid JSON with a `claims` key (test 10).
4. Merge the two `describe('claims ledger', ...)` blocks in `portfolio.test.js` into one, replace the hardcoded timestamp with a `Date.now()`-relative one, drop the duplicate "missing file" test, and add the invalid-timestamp and future-timestamp tests (11-14) before touching `claimsReport()`.
5. Fix `claimsReport()` in `portfolio.js`: compute `ageHours` from `new Date(report.timestamp).getTime()` and reject when `!Number.isFinite(ageHours) || ageHours > 25 || ageHours < 0` (covers missing, unparsable, stale, and future timestamps in one guard).
6. Add `claimStatusLabel`, `formatClaimTimestamp`, and `UnregisteredClaims` as named exports in `PortfolioHub.jsx`, following the existing `OpenDevSiteButton` pattern; write `dashboard/test/claims_ledger_view.test.jsx` (tests 16-18) first via `renderToStaticMarkup`.
7. Wire those three pieces into `Content()`'s Claims ledger section: the status badge shows the word, timestamps go through the safe formatter, and `<UnregisteredClaims items={claims.unregistered} />` renders after the claims list. Add test 19 (markup contains the unregistered id) against the wired-up section.
8. In `claims.py`'s `main()`, remove the `if failed > 0: run.fail(...)` call in the `--nightly` branch (keep `run.summary(...)`); write tests 20-21 first.
9. Delete the unreferenced `flag_for_redraft` stub in `claims.py`; fix the stale comment above `check_marvin_link` to describe the real mechanism (reusing `portfolio_content.py`'s own `marvin-link-missing` finding) instead of calling it a placeholder.
10. Add tests 22-23 (repeats, one-source-failing) to `test_claims.py`.
11. Tighten ADR 0065's and CONTEXT.md's staleness line to say "missing, unparsable, in the future, or stale (>25h)" instead of just "missing timestamp" — one line in each, matching the actual guard from step 5.
12. Run `~/.agents/venv/bin/python -m pytest brain-map/scripts/test_claims.py -v`, the dashboard vitest suite (`dashboard/test/portfolio.test.js`, new `claims_ledger_view.test.jsx`), then the full `lib/tests/` + `dashboard/test/` suites for regressions, and one manual `claims.py --json` run against this machine's real `~/.claude/logs` to sanity-check output before calling this done.