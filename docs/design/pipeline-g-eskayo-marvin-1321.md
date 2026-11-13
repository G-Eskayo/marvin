## North-star fit

**Reuses:** the existing poll-with-deadline pattern already in `lib/tests/test_job_hooks.py::test_the_session_environment_is_read_from_proc` (added in commit `8f1b0838`, "Part of #1144") — a `time.monotonic()` deadline loop with `time.sleep(0.01)`. This plan keeps that shape and only changes *what* it polls on. No new file, no new helper, no new dependency.

**Why simplest sufficient:** the current failure is the second time this exact test has gone red with the exact same symptom (`KeyError: 'DISPLAY'`), despite a deliberate fix last time (#1144/#1135). That fix polled a *proxy* signal (`/proc/{pid}/exe` ends with `"sleep"`) as a stand-in for the real one (`/proc/{pid}/environ` contains the exec'd process's env). Proxy and target can legitimately diverge in timing on a loaded CI runner — polling the proxy doesn't guarantee the target is ready. The minimal, sufficient fix is to stop polling the proxy and poll the actual postcondition the assertion needs (`jh.process_env(p.pid)` already contains `"DISPLAY"`), using `jh.process_env` itself — the one function under test — instead of `os.readlink`. This removes the whole class of proxy/target divergence rather than widening a timeout or adding another indirect signal, which would just be the same bug with a longer fuse.

**Tokens:** small, surgical diff to one test function; no new files or scaffolding.

**Phone-OS direction:** none directly — this is CI hygiene, a precondition (north star 2 depends on reliability: "nothing may break silently").

**User capability:** restores main to green so the merge gate stops blocking all other PRs; doesn't change any shipped behavior, so it's purely enabling, not making anyone more passive.

**Decision to revert vs fix forward:** fixing forward (small, test-only change, no revert needed) — consistent with the ticket's "revert only if a fix is not small."

## Root cause

`lib/tests/test_job_hooks.py:172-185` (`test_the_session_environment_is_read_from_proc`) launches `sleep 30` with a specific env dict, then waits for `/proc/{pid}/exe` to end in `"sleep"` before calling `jh.process_env(p.pid)` and asserting on its contents. CI failed with `KeyError: 'DISPLAY'` — the environment `jh.process_env` returned didn't contain `DISPLAY` at all, meaning the read happened before the child's `/proc/{pid}/environ` reflected the exec'd process's environment, even though the `exe` symlink had already updated. The `exe`-symlink check is a *proxy* for "the child's environ is now the exec'd one" — under CI load the two can observably diverge, so polling the proxy doesn't prove the target condition. This is exactly the failure #1144 tried to fix, just recurring via a different proxy gap.

`lib/job_hooks.py:89-96` (`process_env`) is untouched; it's correct (reads `/proc/{pid}/environ`, filters to `SESSION_VARS`, returns `{}` only on `OSError`) — no production code changes needed, confirmed not the merge that broke this (last merge, #1319, only touched `bench/` MLX test skip logic, unrelated).

## Fix

In `lib/tests/test_job_hooks.py`, replace the `/proc/{pid}/exe` readlink poll with a poll on `jh.process_env(p.pid)` itself — the real target, not a proxy:

```python
deadline = time.monotonic() + 10
env = jh.process_env(p.pid)
while "DISPLAY" not in env and time.monotonic() < deadline:
    time.sleep(0.01)
    env = jh.process_env(p.pid)
assert env["DISPLAY"] == ":7" and env["XAUTHORITY"] == "/x" and "SECRET" not in env
```

`os.readlink`/`/proc/{pid}/exe` is dropped from this test; `os` stays imported (used elsewhere in the file, e.g. `os.kill` at line 63). The 10s deadline and polling cadence (0.01s) are unchanged — this isn't a widened tolerance, it's polling the actual assertion target instead of a stand-in, so the test is strictly more correct, not looser. If the environment genuinely never appears (real regression), the loop still exits at the deadline and the `assert` still fails exactly as before.

## Tests (first)

This is itself the test fix — there's no separate "production" change to cover, so the acceptance-criteria tests are:

1. **The named failing test passes on a clean checkout of main with the fix applied**, run repeatedly (e.g. 20×) on Linux to confirm the race is actually closed, not just missed once: `pytest lib/tests/test_job_hooks.py::test_the_session_environment_is_read_from_proc -q --count=20` (or a shell loop if `pytest-repeat` isn't installed — check first) on a Linux box/container, since the test is Linux-only (`skipif` guards macOS).
2. **The rest of `lib/tests/test_job_hooks.py` and `lib/tests/test_task_dispatch.py`** (same module family) still pass unchanged — no collateral breakage from touching only this one test function.
3. **Full suite on a clean checkout of main** (not just this worktree) — `.github/run-check.sh python` — passes, matching the ticket's "run the failing tests again on a clean checkout of main" break-attempt.
4. **Verify the fix doesn't hide the failure**: diff review confirms no assertion was weakened, no `skip`/`xfail` added, no tolerance widened — the assertion line is byte-for-byte the same as before; only the wait condition changed from a proxy to the real target.
5. **Misuse case the ticket's break-list didn't name but is relevant here**: `jh.process_env` returns `{}` (not a raise) if `/proc/{pid}/environ` is ever unreadable (`OSError`, e.g. process exited early) — confirm the new loop handles that (loop condition `"DISPLAY" not in env` is `True` for `{}` too, so it just keeps polling until deadline, same as a slow-to-populate env; no new exception path introduced).

No concurrency/repeats/permissions/stale-state cases apply beyond #1 above (this is a single-process timing test, not a shared-state or multi-writer system); no dependency to mock since the real collaborator (`/proc`) is used directly, per north-star guidance on testing against the real collaborator.

## Decisions

None — this is a small, mechanical fix-forward with no open design choice for the owner.

## Task List

1. Edit `lib/tests/test_job_hooks.py:172-185`: replace the `os.readlink(f"/proc/{p.pid}/exe").endswith("sleep")` poll loop with a poll on `jh.process_env(p.pid)` until `"DISPLAY" in env` or the 10s deadline, keeping the same `assert` line unchanged.
2. Run `test_the_session_environment_is_read_from_proc` repeatedly (≥20×) on Linux to confirm the race is closed, not just not-reproduced once.
3. Run the full `lib/tests/test_job_hooks.py` and `lib/tests/test_task_dispatch.py` files to confirm no collateral breakage.
4. Run the full `.github/run-check.sh python` suite on a clean checkout of main with the fix applied (not just this worktree), per the ticket's break-attempt instruction.
5. Open the PR naming "Closes #1321", noting the merge gate will self-close the ticket once CI goes green, and noting explicitly that no revert was needed (small fix-forward).