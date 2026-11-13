Good, no conflicting decisions found — plan is consistent with existing design docs. I have enough context to write the plan now.

## North-star fit

**Reuses:** the shared-constant pattern `daily_digest.py:322`'s existing `already_failed = content.startswith("(claude call failed:")` check — this ticket just hoists that literal into a module constant (`CLAUDE_FAILED_PREFIX`) so `cross_machine_merge.py` can import and check it too, instead of duplicating the string. It also reuses `cross_machine_merge.py`'s own established "log line + `continue`" skip idiom already used for `merged_file.exists()` and `not local_file.exists()` at `cross_machine_merge.py:364-369`, and its quarantine placeholder text that already exists verbatim in `daily_digest.py:328-330` (`"_Quarantined by safety-monitor..."`) — no new sentinel invented for it, just a substring check on existing text.

**Why simplest sufficient:** a one-line constant plus two `continue`-guarded checks in the one function (`run_merge_authority`) that writes and pushes the file. No new state, no new file, no retry-scheduling machinery — the fix is purely "stop writing/pushing/spending-a-call on junk," and the next day's natural re-trigger (`check_and_trigger_merge.py` / the 09:30 launchd run) already retries for free once `merged_file.exists()` is no longer true, per the ticket's own purpose section.

**Tokens:** spends a few lines of code to *save* a wasted ~240s Claude call (`build_merged`) whenever either input is already a failure/placeholder — net token and time savings, not a cost.

**North star 5 (every machine works):** directly serves it — one failed call on either machine no longer leaves both Macs stuck on a junk merged digest for the rest of the day.

**More capable or more passive:** neutral-to-positive; this is a reliability fix in a background job Gil never watches directly — it just stops a silent failure mode from persisting.

## Tests first (one per "How we'll try to break it" item, plus misuse not explicitly listed)

In `skills/improve/scripts/tests/test_cross_machine_merge.py`, add tests for `run_merge_authority()` (currently untested in that file):

1. **`call_claude()` returns empty string → treated as failed, no write.** Monkeypatch `cmm.build_merged` (or the underlying `call_claude`) to return `""`; assert `{TODAY}-merged.md` is not created and `scp_push` is not called. (Covers the "empty string" break-attempt explicitly, which is stricter than just checking the failure-prefix string — confirms the empty-content case is *also* caught, not just prefix-matched.)
2. **Merge result starting with `CLAUDE_FAILED_PREFIX` → no write, no push, logs and continues to the next `kind`.** Monkeypatch `build_merged` to return `f"{cmm.CLAUDE_FAILED_PREFIX} boom)"`; assert no `-merged.md` file for either `daily-digest` or `research-digest`, `scp_push` not called, and the loop still processes the second `kind` (doesn't abort the whole function).
3. **Failure prefix appearing mid-text in an otherwise-good local or remote input → still merged (only a *leading* prefix on inputs disqualifies).** Local file content is `"Good stuff.\n\nQuoted elsewhere: (claude call failed: old)"` with the prefix not at position 0; assert `call_claude`/`build_merged` IS invoked (the merge proceeds) — proves the check is `startswith`, not `in`.
4. **A leading failure prefix on the local input → `call_claude` never invoked, no write/push.** `local_file` content starts with `CLAUDE_FAILED_PREFIX`; assert `build_merged`/`call_claude` is never called, no `-merged.md` written, `scp_push` not called, and log line present.
5. **A leading failure prefix on the remote input → same as #4** but via `ssh_run`'s returned content.
6. **Remote content containing `"Quarantined by safety-monitor"` (leading or embedded per the quarantine placeholder's actual shape, which is a full sentence, not a prefix — ticket says "contains" for this marker specifically) → `call_claude` never invoked**, no write/push.
7. **Local content containing the quarantine marker → same as #6.**
8. **Remote unreachable mid-run (`ssh_run` returns `None`) → unchanged behavior:** no write, no push, no exception (this path already exists in current code at `cross_machine_merge.py:372-374`; add a regression test pinning it so the new checks don't disturb it).
9. **After a failed attempt, the same day's next call to `run_merge_authority()` retries the merge.** First call: `build_merged` returns a failure string → no `merged_file` written. Second call (same `TODAY`, same tmp dirs): `build_merged` returns real content → assert `merged_file` now exists and `scp_push` was called this time. Proves the `merged_file.exists()` guard doesn't falsely trip after a failed attempt.
10. **The constant is actually shared, not duplicated.** `assert cmm.CLAUDE_FAILED_PREFIX is dd.CLAUDE_FAILED_PREFIX` (imported identity) — catches the ticket's named failure mode ("the prefix string changes in `call_claude()`: the shared constant keeps both sides in step").

In `skills/improve/scripts/tests/test_daily_digest.py`, add:

11. **`already_failed` check uses `dd.CLAUDE_FAILED_PREFIX`, not a hand-typed literal.** `content = dd.CLAUDE_FAILED_PREFIX + " boom)"`; call whatever helper/inline logic wraps `already_failed` (extract if currently inline in `main()` — see task 2 below) and assert it's `True`; a sibling test with the constant changed via `monkeypatch.setattr(dd, "CLAUDE_FAILED_PREFIX", "(different prefix:")` and the same content prepended with the *new* value must still evaluate `True`, proving the check reads the constant rather than the old hardcoded string.
12. **`call_claude()`'s two failure-return paths both start with the constant.** One test forces the `except Exception` path (mock `marvin_launcher.launch` to raise); one forces the `result.exit_code != 0 or not result.text.strip()` path; both assert `.startswith(dd.CLAUDE_FAILED_PREFIX)`.
13. Existing `test_daily_digest.py` suite must still pass unmodified (ticket's explicit acceptance criterion) — no test change needed here beyond running the full file; note it as a verification step, not a new test.

## Decisions

No open design choices — the ticket's "How" section is fully prescriptive (exact constant name, exact call sites, exact skip conditions) and matches the existing code shape (`already_failed`, the `continue`-skip idiom, the quarantine marker string). Nothing here needs the owner to pick between options.

## Task List

1. In `skills/improve/scripts/daily_digest.py`: add module-level `CLAUDE_FAILED_PREFIX = "(claude call failed:"` near the other module constants (top of file, after `OUT_FILE`), use it in both `call_claude()` return strings (lines 276, 278) via f-string/`+`, and in `main()`'s `already_failed = content.startswith("(claude call failed:")` (line 322) → `content.startswith(CLAUDE_FAILED_PREFIX)`.
2. In `skills/improve/scripts/cross_machine_merge.py`: extend the existing `from daily_digest import call_claude` (line 57) to also import `CLAUDE_FAILED_PREFIX`.
3. In `run_merge_authority()`, before `print(f"{LOG_PREFIX} merging {kind}...")` and the `build_merged(...)` call (around line 376): add a guard that checks `local_file.read_text()` and `remote_content` each with `.startswith(CLAUDE_FAILED_PREFIX)` OR `"Quarantined by safety-monitor" in text`; on a hit, print a log line (e.g. `f"{LOG_PREFIX} {kind} input from {('local' if ... else remote_id)} is a failure/quarantine placeholder — skipping merge, will retry next trigger"`) and `continue` to the next `kind`, without reading the file twice (reuse the already-read content for `build_merged`'s call below rather than re-reading).
4. After `merged = build_merged(...)` (line 377-380): add `if merged.startswith(CLAUDE_FAILED_PREFIX):` → log line (`f"{LOG_PREFIX} {kind} merge call failed — not writing, will retry on next trigger"`) and `continue`, placed before the `header = (...)` / `merged_file.write_text(...)` block so neither the write nor the subsequent `scp_push` runs.
5. Add tests 1–10 to `skills/improve/scripts/tests/test_cross_machine_merge.py`, reusing the file's existing `monkeypatch.setattr(cmm, "ssh_run", ...)` / `monkeypatch.setattr(cmm, ...)` style; mock `cmm.scp_push` to a recording stub so push-not-called is assertable without a real SSH/scp call; mock `cmm.build_merged` directly where only the merge result matters, and `cmm.ssh_run`/local file content where only the input-skip matters.
6. Add tests 11–12 to `skills/improve/scripts/tests/test_daily_digest.py`, reusing the file's existing `_pinned_machine_role` fixture pattern and `monkeypatch.setattr` style for `marvin_launcher.launch`.
7. Run the full `skills/improve/scripts/tests/` suite (`test_daily_digest.py`, `test_cross_machine_merge.py`, and the unrelated `test_auto_fix.py`/`test_improvement_sweep.py` to catch any accidental import breakage from the new `CLAUDE_FAILED_PREFIX` import) and confirm all pass.
8. Add the recurrence-check probe the ticket mentions ("none yet: add one counting `*-merged.md` files... that contain 'claude call failed'") — out of scope for *this* code fix per the ticket's own phrasing ("add one... as part of the fix" is listed under "Recurrence check", a separate tracked follow-up date 2026-11-26, not an acceptance criterion); flag in the PR description that this probe is not included and ask whether it should be a follow-up ticket rather than silently adding scope.