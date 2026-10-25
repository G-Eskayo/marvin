## North-star fit

**Reuses before adding anything new:** the fix for the must-fix shlex-quoting bug (`lib/brief_fallback.py:52`) is not new machinery — it's applying the exact pattern `scanner_role.py` already uses correctly: `REMOTE_HEARTBEAT_COMMAND = 'cat "$HOME/.claude/ticket-scan-heartbeat.json"'` (`lib/scanner_role.py:22`) puts `$HOME` inside **double** quotes (so the remote shell expands it) and nothing else needs quoting there because that path is a fixed literal. `brief_fallback.py` has a variable (date-stamped) suffix after `$HOME`, so the same idea splits in two: `"$HOME"` stays double-quoted/literal, and the variable remainder gets `shlex.quote()`ed and concatenated as a separate shell word — standard `"$HOME"/'quoted/rest'` shell concatenation. No new quoting scheme, no new dependency.

The rest of the design (`scanner_role.should_scan()`'s primary/standby shape, `machine_profile.registry_id()`/`remote_devices()`, `task_dispatch.SSH_OPTS`, the digest scripts' existing TOCTOU-recheck-before-write pattern, `health_checks.JOB_PLACEMENT`/`check_brief_builder()`) is already built in this worktree and already passed review with **no must-fix findings** on those parts. This is confirmed by direct inspection, not assumed: `lib/health_checks.py:525-541` (`check_brief_builder`) and `:1011-1026` (`JOB_PLACEMENT`), the three launchd fallback plists, and the `CONTEXT.md` "Brief owner" bullet are all present, correct against ADR 0067 ("an hour after its usual time" ↔ 09:15→10:15, 08:30→09:30, 09:00→10:00 in the plists), and already registered in `default_checks()`. Redoing any of that would be waste, not rigor.

**Simplest sufficient approach:** this is a four-defect repair pass on an already-accepted design (ADR 0067, no open "how should this work" question) — not a redesign. All four must-fix bugs trace to one root module, `lib/brief_fallback.py`, and one unguarded call site (`skills/improve/scripts/daily_digest.py:282`). Fixing `_is_valid_content()`/`produced()`/`should_run()` centrally repairs `research_digest.py`'s and `daily_digest.py`'s gates for free, since both already delegate to `brief_fallback`. No new files, no new abstractions.

**Tokens:** spends a few lines of new/rewritten tests and ~30 lines of corrected logic in one file; saves the recurring cost of this ticket failing automated review and re-running from scratch (this is at least the 7th attempt against `main`, per the issue's comment history).

**User capability:** directly serves north star 1 (halves model calls once it actually works) and leaves Health accurately reporting which machine built today's output — Gil stops having to notice a silently-stuck fallback himself.

**Correcting the ticket's stated fit:** unchanged from the prior analysis — the ticket's "reuses the existing jobs and launchd setup" doesn't name the real reusable primitive (`scanner_role.py`'s primary/standby shape, now also its `$HOME`-quoting pattern specifically).

## Root cause of each must-fix bug (read from current `lib/brief_fallback.py`)

1. **`_infer_remote_path()` (line 40-57) returns `shlex.quote(f"$HOME/{rel}")`** — single-quotes the whole string including `$HOME`, so the remote `cat` never expands it. `read_remote()` (line 60-86) is therefore always `None`, so `should_run()` can never see that the primary already produced today's file.
2. **`test_infer_remote_path_*` (lines 21-55) only assert `"$HOME" in result`** — true even for the single-quoted, non-expanding string, so the broken version passes.
3. **`should_run()` (lines 142-161)** returns `Decision(True, ...)` for "no primary found" / "no host" / "unreachable" *before* the `past_deadline()` check (line 168). A standby that finds the Mini briefly unreachable before the deadline (e.g. still booting) builds immediately instead of waiting out the hour ADR 0067 specifies.
4. **`produced()` (lines 89-103)** treats any non-empty file as produced, so a file containing `daily_digest.py`'s `"(claude call failed: ...)"` placeholder counts as a successful run. `should_run()` (line 164) compounds this by testing raw `read_remote()` truthiness instead of the same validity check. Separately, `daily_digest.py:282` has its own `if OUT_FILE.exists():` early-return that bypasses `produced()` entirely — even once `produced()` is fixed, the digest's own primary-path guard would still treat a failure placeholder as "already done" and never retry it.

## Tests to write first

All against real collaborators where a mock would hide the rule being tested (per "tests try to break it"): the `$HOME`-expansion and injection tests run a **real** `sh -c`, not a mocked `shlex.quote`.

**Rewritten in `lib/tests/test_brief_fallback.py`** (replacing the tests that let bug #1/#2 through):
1. `test_infer_remote_path_splits_home_from_relative` — for a path under `Path.home()`, asserts the function's new return shape makes `$HOME` and the relative remainder separately available (see Task List #1 for the exact contract), not just "a string containing `$HOME`".
2. `test_infer_remote_path_bare_filename_outside_home` — unchanged behavior, still covered: a path not under `Path.home()` → bare filename only.
3. `test_read_remote_expands_home_via_real_shell` — build the actual command `read_remote()` would run, execute it through a real `sh -c` (not `subprocess.run(["ssh", ...])`) with `HOME` monkeypatched to a `tmp_path` containing the target file at the inferred relative path; assert the real file's content comes back. *Directly catches bug #1 — the single-quote version fails this test; a double-quoted-`$HOME` version passes.*
4. `test_read_remote_rejects_shell_injection_in_relative_path` — same real-`sh -c` harness, with a local path whose filename contains shell metacharacters (e.g. `` `touch sentinel`; rm -rf /tmp/x ``); assert no sentinel file is created and the call returns `None`/no match. *Attacks-class test (outward-facing: this command string is built from a filesystem path).*

**New/rewritten `should_run()` tests** (replacing `test_should_run_standby_runs_if_primary_unreachable`, which asserted `True` using the real wall clock with no `now` override — already a latent flakiness bug, confirmed by inspection):
5. `test_standby_waits_before_deadline_without_probing` — before deadline; monkeypatch `produced` and `read_remote` to raise `AssertionError` if called; assert `Decision(False, "...")` and that nothing probed. *Catches bug #3's "waits without ever calling produced()/SSH" requirement.*
6. `test_standby_waits_before_deadline_even_when_primary_unreachable` — primary offline (`_tailscale_online_hosts` returns `set()`), explicit `now` before deadline → `Decision(False, "waiting...")`, not `True`. *Directly catches bug #3 — the old code returned `True` here.*
7. `test_standby_waits_before_deadline_when_no_primary_registered` — `_primary_device()` returns `(None, None)`, `now` before deadline → `Decision(False, ...)`. *Same bug, the "no primary found" branch.*
8. `test_standby_builds_after_deadline_when_primary_unreachable` — same unreachable setup, `now` past deadline → `Decision(True, "...fallback...")`. *Confirms the fallback still fires once the window has actually elapsed.*
9. `test_standby_skips_when_local_file_already_produced` — past deadline, local file has real content → `Decision(False, ...)` without needing SSH at all (cheap local check first).
10. `test_standby_skips_when_remote_has_valid_content` — past deadline, local absent, `read_remote` (mocked at this level) returns real content → `Decision(False, "...")`.

**Placeholder-detection tests** (bug #4):
11. `test_produced_false_for_failure_placeholder` — local file content `"(claude call failed: timeout)"` → `produced()` is `False`.
12. `test_produced_true_for_quarantine_placeholder` — local file content containing `"_Quarantined by safety-monitor"` → `produced()` is `True` (quarantine is a real outcome, not an outage).
13. `test_should_run_builds_when_remote_content_is_failure_placeholder` — past deadline, local absent, `read_remote` returns `"(claude call failed: boom)"` → `Decision(True, "...fallback...")`, not `False`. *Directly catches the "`should_run` used raw truthiness" half of bug #4.*
14. `test_should_run_never_raises_when_registry_id_fails` — `machine_profile.registry_id` raises → `should_run()` returns a `Decision`, never propagates. *Closes the related "never raises" gap PR #600's review flagged (`is_primary(None)` would otherwise crash).*

**New test in `skills/improve/scripts/tests/test_daily_digest.py`** (the gap bug #4 leaves in the actual call site, not just the library):
15. `test_main_rebuilds_when_existing_digest_is_failure_placeholder` — write `OUT_FILE` ahead of time with content containing `"(claude call failed:"`; monkeypatch `brief_fallback.should_run` → `Decision(True, "fallback: ...")`; monkeypatch `call_claude` to return real content; run `main()`; assert `OUT_FILE` is overwritten with the new content. *Directly catches the `daily_digest.py:282` `.exists()` bug — this test fails against the current code even after `produced()` itself is fixed, because line 282 never calls `produced()`.*

No changes needed to `lib/tests/test_health_checks.py`, `lib/tests/test_morning_brief.py`, the launchd plists, or `CONTEXT.md` — inspected directly and all already match ADR 0067 with no must-fix findings against them.

## Decisions

<!-- marvin:decisions -->
### retire-cross-machine-merge: Once the Mini is the sole real builder, should `cross_machine_merge.py`'s LLM-merge step be retired now or left wired?
- [ ] A: Retire now in a follow-up ticket — under this design it runs zero LLM calls on a normal day (only one machine ever has real content to merge), so leaving it wired is dead weight.
- [ ] B: Leave it wired for now — it's a harmless no-op most days and still covers the rare day both machines end up with real output (e.g. the Mini recovers mid-morning after the MacBook already built as fallback). `JOB_PLACEMENT["cross-machine-merge"]` is still `"both"` in the current worktree, unchanged by this ticket.

## Task List

1. **`lib/brief_fallback.py`** — fix the four must-fix defects in place (no new files):
   - `_infer_remote_path(local_path) -> tuple[str, bool]`: return `(str(rel), True)` when under `Path.home()`, else `(path.name, False)` — unquoted; quoting moves to the caller.
   - `read_remote()`: build the command as `f'cat "$HOME"/{shlex.quote(rel)}'` when `under_home`, else `f'cat {shlex.quote(rel)}'` — `$HOME` literal and double-quoted (expands), the variable part separately `shlex.quote()`-d (immune to injection).
   - Add `_is_valid_content(content: str | None) -> bool`: `False` for `None`/empty/whitespace-only, `False` when `"(claude call failed:"` appears anywhere in it, `True` otherwise (covers the quarantine-placeholder case, which doesn't contain that string).
   - `produced(local_path)`: delegate to `_is_valid_content()` on the file's text (still never raises).
   - `should_run()`: for the standby branch, check `past_deadline()` **first**, before any `_primary_device()`/`read_remote()` call; only after the deadline has passed, check `produced(local_path)` then `_is_valid_content(read_remote(...))`, in that order (local check is free, SSH only if needed).
   - Guard `me = device_id or machine_profile.registry_id()` against `registry_id()` raising (catch and treat as unknown/non-primary) so `should_run()` keeps its "never raises" guarantee.
2. **`lib/tests/test_brief_fallback.py`** — replace the 5 `_infer_remote_path` tests and the 4 `should_run` tests per items 1-10 above (red against current code, green after step 1); add placeholder tests 11-14.
3. **`skills/improve/scripts/daily_digest.py:282`** — change `if OUT_FILE.exists():` to `if brief_fallback.produced(OUT_FILE):`, so a failure-placeholder digest gets rebuilt rather than silently kept.
4. **`skills/improve/scripts/tests/test_daily_digest.py`** — add test 15.
5. **Full-suite run**: `~/.agents/venv/bin/python -m pytest lib/tests/ skills/improve/scripts/tests/ skills/research-colony/scripts/tests/ -q`; confirm every new/rewritten test fails against the pre-step-1 tree and passes after; re-confirm `lib/tests/test_no_hardcoded_home.py`'s one pre-existing failure (`docs/screenshots/vitals-v4/data.js`) is still unrelated and unchanged by this diff.
6. **PR description**: note this supersedes PR #600 on the same branch; carry forward the `retire-cross-machine-merge` Decision; call out the four specific must-fix defects fixed and which test catches each, so the next review can check directly rather than re-deriving them.