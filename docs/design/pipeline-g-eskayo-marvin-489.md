## North-star fit

- **Reuses**: `hook_errors.log_hook_error` (`lib/hook_errors.py:17`), the primitive already wired into `gh_merge_guard.py:60`, `deliverable_location_guard.py:69`, `session_start_report.py:71/85/117/284`, `background_architecture_review.py:319`. It also reuses the "wrap the logger call in its own `try/except: pass`" defensive pattern already present in `lib/temp_deliverable_hook.py:209-214`'s `main()` — the one existing place in the repo that already defends against `log_hook_error` itself raising, which is exactly AC #3's requirement. No new logging mechanism is introduced; the only new code is one small private helper (`_log_hook_error_safe(context, exc)`) inside `task_dispatch.py` so that 4-line guard isn't tripled verbatim across the three call sites — three call sites is enough to justify it, two would not be.
- **Simplest sufficient approach**: this only adds logging calls at the three named sites; it doesn't touch return values, control flow, or the two blocks the ticket explicitly says to leave alone (`_live_task_count`'s `continue`, `_log_fallback`'s `pass`).
- **Token/compute cost**: negligible — a few extra lines and, on failure, one append to `~/.claude/logs/hook-errors.log` (already rotated/managed) plus `error_log.record`. No new process, no new dependency.
- **North star 5 fit**: a remote machine `task_dispatch` can't reach (SSH down, malformed state, Tailscale CLI missing) currently reads as quietly "free"/"idle"/"unknown load" with no trace. After this, that silent misread leaves a line in `hook-errors.log` / the error log Health already shows, so a wrongly-busy-or-free read of a remote is diagnosable after the fact instead of invisible — the exact gap the ticket's Purpose names.
- **Token/capability**: pure observability infrastructure for MARVIN itself; it makes diagnosing a misrouted dispatch possible after the fact rather than leaving Gil guessing. Not user-facing, so it doesn't change how passive/active anyone is — it only removes a blind spot.

No owner decision is needed — the ticket's "What to build" and acceptance criteria fully specify the change; nothing here is a design choice to put to Gil.

## Tests first (added to `lib/tests/test_task_dispatch.py`)

For `tailscale_online_hosts_or_none()`:
1. `subprocess.run` raises `FileNotFoundError` (binary missing) → `log_hook_error` called exactly once with context `"tailscale_online_hosts_or_none"`, return value still `None`.
2. `subprocess.run` raises `subprocess.TimeoutExpired` → same: one log call, still returns `None`.
3. Non-zero exit (already-handled branch) → **no** log call (out of the ticket's stated scope — pins down we didn't over-extend logging there).
4. `log_hook_error` itself raises (monkeypatched to raise) → function still returns `None`, no exception propagates.

For `_read_remote_dispatch_state()`:
5. `subprocess.run` raises `FileNotFoundError` → one log call with context `"_read_remote_dispatch_state"`, returns `{"busy": False}` unchanged.
6. `subprocess.run` raises `TimeoutExpired` → same.
7. SSH returns malformed JSON (returncode 0, garbage stdout) → `json.loads` raises → one log call, returns `{"busy": False}`.
8. SSH returns non-zero exit code (e.g. 255) → one log call whose logged exception/message includes that return code, returns `{"busy": False}` (AC: "non-zero-exit branch should log the return code too").
9. Returncode 0 but empty stdout → **no** log call (existing silent branch stays silent; ticket doesn't ask for it).
10. `log_hook_error` raises → function still returns `{"busy": False}`, no exception propagates.
11. Called for 5 different hosts, each raising → 5 separate log calls (one per call, no dedup/suppression), each call still returns `{"busy": False}`, nothing crashes — covers "5 hosts all down: 5 log lines, no crash, decision unchanged."

For `machine_load()`'s remote branch (line ~203):
12. `subprocess.run` raises `FileNotFoundError` → one log call with context `"machine_load"`, returns `None`.
13. `subprocess.run` raises `TimeoutExpired` → same.
14. SSH output malformed (e.g. `float()`/`int()` parse failure) → one log call, returns `None`.
15. `log_hook_error` raises → `machine_load` still returns `None`, no exception propagates.

Cross-cutting / misuse the ticket's list didn't spell out:
16. Repeats: call the same failing function twice in a row → two independent log calls (no hidden memoization/suppression state leaking between calls).
17. Log path not writable (`LOG_PATH.parent.mkdir`/open fails — simulate via monkeypatching `hook_errors.LOG_PATH` to a path under a non-writable or non-existent unwritable parent, or monkeypatch `Path.open` to raise): dispatch-level fallback (`_read_remote_dispatch_state`, `tailscale_online_hosts_or_none`, `machine_load`) still returns its normal fallback — exercises the real `hook_errors.log_hook_error`, not a mock, for this one case so its own internal `except: pass` is verified for real (per "test against the real collaborator wherever a mock could hide its rules").
18. Existing tests `test_online_hosts_says_none_when_tailscale_cannot_run_and_dispatch_still_gets_a_set` and `test_online_hosts_says_none_when_tailscale_exits_non_zero` must keep passing unmodified (return-value regression guard).

## Task List

1. Add `from hook_errors import log_hook_error  # noqa: E402` to `lib/task_dispatch.py`'s import block (next to the existing `machine_profile`/`host_os` imports, ~line 30-31).
2. Add a small private helper `_log_hook_error_safe(context: str, exc: BaseException) -> None` in `lib/task_dispatch.py` that calls `log_hook_error("task_dispatch", context, exc)` inside its own `try/except Exception: pass`, mirroring `lib/temp_deliverable_hook.py:209-214`.
3. In `tailscale_online_hosts_or_none()` (~line 73-90): change `except Exception:` to `except Exception as exc:`, call `_log_hook_error_safe("tailscale_online_hosts_or_none", exc)` before `return None`. Leave the `returncode != 0` branch untouched.
4. In `_read_remote_dispatch_state()` (~line 103-113): split the combined `if proc.returncode != 0 or not proc.stdout.strip():` into two branches — a non-zero-exit branch that calls `_log_hook_error_safe("_read_remote_dispatch_state", RuntimeError(f"ssh to {host} exited {proc.returncode}: {proc.stderr[:300]}"))` then returns `{"busy": False}`, and an unchanged empty-stdout branch that returns `{"busy": False}` without logging. Change `except Exception:` to `except Exception as exc:`, call `_log_hook_error_safe("_read_remote_dispatch_state", exc)` before returning `{"busy": False}`.
5. In `machine_load()` (~line 196-204): change `except Exception:` to `except Exception as exc:`, call `_log_hook_error_safe("machine_load", exc)` before `return None`.
6. Write the 18 tests above in `lib/tests/test_task_dispatch.py`, run them first to confirm they fail against the current code.
7. Implement steps 1-5, rerun the full `lib/tests/test_task_dispatch.py` (and the rest of `lib/tests/`) until green.
8. Add the recurrence probe the ticket asks for: a one-line count of `[task_dispatch]` lines in `hook-errors.log`, surfaced wherever the existing session-start/health checks already summarize that log (reuse, don't build a new reader) — confirm on 2026-11-26 per the ticket.
9. `marvin-show` the diff/PR for review; open the PR naming `Closes #489`.