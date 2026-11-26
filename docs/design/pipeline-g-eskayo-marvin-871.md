## North-star fit

**Reuses before adding anything new:**
- `code_sync.py:_run_lock` (lib/code_sync.py:1027) — the flock-on-a-file-in-`.git`, auto-released-on-crash pattern ("a killed run never leaves a lock behind, only the file") is the exact concurrency primitive the ticket asks for. I generalize it into a new small module instead of duplicating it inline a third time.
- `cleanup_sweep.py:decide_worktree`/`_in_use`/`_cwds_in_use` (lib/cleanup_sweep.py:118-138, 476) and `disk_triggers.py:decide_merged` (lib/disk_triggers.py:244) — both already gate worktree mutation on "is a process inside it"; this is the existing choke point for "don't touch a worktree someone's using," just with an lsof-cwd blind spot (no process holds that cwd *between* an agent's tool calls, which is exactly the gap #761 exposed). I extend these two existing guards rather than inventing a new deletion-gating mechanism.
- `health_checks.py:check_recent_errors`/`check_machine_state_everywhere` (lib/health_checks.py:1544, 1586) — the established "one row per Mac, built from `machine_profile.remote_macs()` + an SSH-or-local runner, folded into `default_checks()`" shape for a per-Mac Health card. The dashboard (`HealthDashboard.jsx`) already renders any `{id, label, severity, detail}` generically, so **no frontend work is needed** for the Health card half.
- `lib/tool_requirements.py`'s own `requires_tool`/`require_path` markers — declaring is already solved; I only add a way to *enumerate* what's declared, I don't change how tests declare things.
- Explicitly **not** reusing the 4 duplicated `_pid_alive()`/`partition_alive()` implementations (dispatch_concurrency.py, task_dispatch.py, model_queue.py, job_hooks.py): flock's OS-level "the fd closes when the process dies" guarantee makes a PID-liveness poll both unnecessary and strictly weaker (PID reuse races) for this specific lock, so I don't add a 5th copy.

**Simplest sufficient approach:** one new module (`worktree_lock.py`) wrapping one flock per `(clone, branch)`, located under the stable `clone/.git/marvin-worktree-locks/` (not the worktree's own private gitdir, since the worktree may not exist yet or may be the stale one about to be removed — the lock must be resolvable before the worktree is). No PID bookkeeping, no polling daemon, no new dashboard surface for the lock itself.

**Where it spends/saves:** the lock check is a single flock syscall (microseconds) on the hot path (`_create_worktree`) — free. The Health card costs one `pytest --collect-only` per Mac per sweep cycle (a handful of seconds, well inside the existing `CROSS_MACHINE_BUDGET_S=200` budget already paid by sibling cross-machine checks) — no new caching layer, no new cron job.

**Phone-OS direction:** both halves make the pipeline more self-healing and visible without a human SSHing in (`check_dispatch_lock`'s own docstring: a stuck lock sat "silently blocking... with no symptom other than 'nothing is happening'" for 15 days) — reliability work, which is north star 2's precondition.

**More capable or more passive:** this is pure infrastructure hardening; it removes a failure mode (two helpers corrupting one worktree) and a blind spot (a missing tool silently skipping tests on one Mac) that a human currently has to notice by accident. Strictly more capable, nothing a person was doing by hand is being taken over.

## Tests to write first

**Lock primitive (`lib/tests/test_worktree_lock.py`), against real flock/real subprocesses — a mock would hide the kernel's own rules, exactly like `test_code_sync_run_lock.py`'s own rationale:**
1. Two real processes try to acquire the same `(clone, branch)` lock at once — only one succeeds, the other gets `WorktreeBusy` (mirrors `test_four_runs_started_together_on_one_clone_never_race`).
2. A held lock's process is killed (`SIGKILL`) — a fresh `acquire()` succeeds immediately, no wait (mirrors `test_a_lock_file_left_by_a_dead_run_does_not_block`).
3. A lock released normally (context exits) is immediately acquirable again.
4. `acquire()` on a clone whose lock directory doesn't exist yet (first-ever ticket, no prior worktree) still works — no chicken-and-egg with the worktree itself.
5. A zero-byte / corrupt lock file (process crashed mid-write) never blocks a fresh `acquire()` — flock is the truth, not the file's JSON body.
6. `read()`/`is_locked()` peek correctly without disturbing a real held lock (doesn't accidentally release someone else's lock).
7. Two near-simultaneous `acquire()` calls for **different** branches on the same clone never contend with each other (per-branch granularity, not a whole-repo lock).
8. Lock path safe for ticket refs containing `/` and `#` (branch names already get sanitized elsewhere — same characters must round-trip here).

**Wiring into `_create_worktree` (extend `lib/tests/test_sandbox_orchestration.py`):**
9. A live lock holder blocks `_create_worktree` from force-removing/recreating the same branch's worktree — raises `WorktreeBusy`, and the first holder's files are untouched (real two-process test, not a mock, since this is the literal #761 reproduction).
10. A dead holder's worktree is still force-removed and recreated exactly as today (regression: existing re-dispatch/stale-branch tests at lines 539-612 must keep passing unchanged).
11. `execute_ticket`/`run_ticket.build()` turns `WorktreeBusy` into the same no-strike, claim-released, redispatch-triggered outcome as `EnvMissing` (extend `lib/tests/test_run_ticket.py`).

**Wiring into cleanup (`lib/tests/test_cleanup_sweep.py`, `lib/tests/test_disk_triggers.py`):**
12. `decide_worktree` returns "keep" for a worktree a live process locks, even when it looks empty/dirty/mergeable by every other signal (extends the existing `in_use` test).
13. `disk_triggers.decide_merged` likewise keeps a locked worktree even though its PR merged.
14. `_default_remove_worktree`/`backup_worktree` refuse (defense-in-depth re-check) if the lock is acquired *after* `decide_worktree` ran but *before* the destructive git call — closes the TOCTOU gap.

**Misuse not in the ticket's own list:**
15. `acquire()` called with a `clone` path that isn't a git repo at all → clear error, not a silent no-op lock.
16. Two helpers for *different* tickets, different branches, same clone, running concurrently (today's normal parallel dispatch, ADR 0052) — never serialize against each other.
17. The lock directory itself (`clone/.git/marvin-worktree-locks/`) never appears in `git status`/is never committable (git always ignores `.git/`).

**Health card (`lib/tests/test_tool_requirements.py`, `lib/tests/test_health_checks.py`):**
18. `requires_tool("rg")`/`requires_tool("gitleaks")`/`requires_tool("node")`/`requires_tool("sh")`/`requires_tool("zsh")` and `require_path(ORGANIZE / "find_file.py")` are all discovered by the catalog collector, matching today's real declarations (`grep`'d above) — a regression test fails the moment a test changes its declaration without the catalog test changing too (ADR 0063 gate 2, "verify fails when code changes without a test changing").
19. A tool declared under two different spellings in two tests (e.g. `"rg"` vs `"ripgrep"`) shows as two separate entries, not silently merged — matches the ticket's explicit break-it case.
20. A machine that "hasn't reported yet" (unreachable, asleep, SSH failure, malformed JSON back) reports yellow "can't read," never green, never crashes the whole sweep (mirrors `check_recent_errors`'s unreachable branch).
21. Catalog collection run with `$MARVIN_SELECTED_TESTS` set in the parent environment still discovers the **full** declared set, not a PR's narrowed selection (must not inherit the gate's own test-selection narrowing).
22. Catalog collection doesn't touch the real `~/.claude` (goes through the same `conftest.py` sandbox every other test run does) — `require_path`'s recorded value must still read as the real, portable `~`-relative path, not the sandboxed temp path.
23. An empty declared set (hypothetically no tests declare anything) reports green "0 declared," not an error.
24. Bad/huge input: a test file with a syntax error in the suite doesn't abort the whole catalog collection for every other file (pytest's own per-file collection-error handling must be respected, not swallowed into "0 tools found").

## Decisions
<!-- marvin:decisions -->
### wait-behavior: When `_create_worktree` finds the worktree's lock already held by a live process, should it wait or fail fast?
- [x] Fail fast (no wait): release the claim immediately and let redispatch retry later, same as today's `EnvMissing`/`model_unavailable` outcomes (Recommended — matches existing precedent, never burns a helper's compute idling)
- [ ] Wait up to a bounded timeout (e.g. 60s, mirroring `code_sync.RUN_LOCK_WAIT_S`) before giving up, in case the first holder is seconds from finishing

## Task List

1. **`lib/worktree_lock.py`** — new module: `_lock_path(clone, branch)` under `clone/.git/marvin-worktree-locks/<safe-branch>.lock`; `acquire(clone, branch, who, wait_s=0.0)` (flock-based, writes `{pid, who, started_at}` once held, raises `WorktreeBusy(holder)` on failure); `LockHandle.release()`; `read(clone, branch)` (peek, no acquire); `is_locked(clone, branch)` (cheap try-lock-then-unlock peek for callers that only need a boolean).
2. Tests 1-8 above for `worktree_lock.py`, written first.
3. Wire `_create_worktree` (lib/sandbox_orchestration.py:432) to call `worktree_lock.acquire(repo_path, branch, ticket_ref)` as its first statement, before `_fetch_base`/`_preserve_prior_attempt`/the force-remove; never explicitly released (process-exit bounds it, same assumption `model_queue.py`/`dispatch_concurrency.py` already make). Add `WorktreeBusy` to the module's public exports alongside `TaskListTooVague`/`ModelRunFailed`.
4. Tests 9-10.
5. Wire `run_ticket.py build()` (lib/run_ticket.py:325) with an `except WorktreeBusy as exc:` branch parallel to `except pp.EnvMissing`, and `settle()` (lib/run_ticket.py:369) with the matching `outcome.get("worktree_busy")` branch (same body as `env_missing`'s).
6. Test 11.
7. Extend `cleanup_sweep.py`'s `_list_root` (lib/cleanup_sweep.py:151) to compute a `"locked"` field via `worktree_lock.is_locked(clone, branch)`, and `decide_worktree`'s first guard (lib/cleanup_sweep.py:482) to `if wt.get("in_use") or wt.get("locked"): return "keep", ...` with a distinguishing reason string.
8. Extend `disk_triggers.py`'s `decide_merged` (lib/disk_triggers.py:244) with the same `worktree_lock.is_locked` guard.
9. Add the same `is_locked` re-check immediately before the destructive call in `_default_remove_worktree` and `backup_worktree` (lib/cleanup_sweep.py:199, 215), closing the decide-then-act TOCTOU gap.
10. Tests 12-17.
11. **`lib/tool_requirements.py`**: add `_declared_tools`/`_declared_paths` module-level accumulators; extend the existing `pytest_collection_modifyitems` to record every `requires_tool` marker's args; branch `require_path` on `MARVIN_CATALOG_TOOLS=1` to record-and-continue instead of skip; add `pytest_collection_finish` to print the accumulated catalog as one parseable JSON line when that env var is set.
12. Add `health()` to `tool_requirements.py`: globs real test files (`test_*.py`) under this repo (explicit file args, not a bare directory, so `test_slot.is_heavy` doesn't queue it behind a real merge), runs `pytest --collect-only -q` as a subprocess with `MARVIN_CATALOG_TOOLS=1` and `MARVIN_SELECTED_TESTS` unset, parses the catalog line, then checks each declared tool via `shutil.which` and each declared path via `os.path.exists(os.path.expanduser(...))` against this machine's *real* environment (not the test sandbox). Add a `python lib/tool_requirements.py health` CLI entrypoint printing that result as JSON.
13. Tests 18-24.
14. **`lib/health_checks.py`**: add `_local_tool_health()` (direct import + call) and `_run_tool_health_remote(host)` (ssh + the CLI above), and `check_tool_requirements_everywhere(reachability, local=..., remote=...)` modeled on `check_recent_errors`/`check_machine_state_everywhere` — one `tools@{dev}` row per Mac (from `machine_profile.remote_macs()`), green if nothing declared is missing, yellow listing what's missing otherwise, yellow "can't read" if unreachable/malformed. Register it in `default_checks()` (lib/health_checks.py:1902) with `CROSS_MACHINE_BUDGET_S`, next to `"machine-state"`.
15. Tests for `check_tool_requirements_everywhere` itself (unreachable Mac, malformed JSON back, both Macs clean, one Mac missing a tool).
16. Full local suite (`MARVIN_MERGE_GATE=1 pytest -n auto`) and manually confirm the new `tools@<mac>` rows render in the existing Health tab with no frontend change, via `marvin-show` on the running dashboard.