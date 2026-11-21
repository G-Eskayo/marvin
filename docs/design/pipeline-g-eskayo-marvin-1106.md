## North-star fit

**Reuses:** `dashboard/webhook-server/merge_queue.js`'s `createQueueStore()` (the existing `hold`/`markConflict`/`fail` mutator pattern — read-modify-atomic-write via `change()`) gets one more mutator, `resume()`, instead of new storage; `index.js`'s already-defined `repoOfPr()` (line 362) derives the repo from a PR url, reused rather than re-written; `rebuild_and_install.sh`'s existing habit of shelling out to a `~/.agents/lib/*.py` helper for a sub-step (it already does this for `code_sync.py pull` and `error_log.py record`) is reused for the new wait step, and that helper mirrors the exact `decide()-is-pure/main()-gathers-facts` shape already used by its two siblings, `lib/webhook_restart.py` and `lib/dashboard_rebuild.py` (down to the `test_webhook_restart.py` `d(**kw)` test idiom). `MERGE_PORT = 7878` already exists in `lib/health_checks.py`; `GET /merge-queue` and its `{repos: {repo: {running}}}` shape already exist in `merge_queue.js`'s `snapshot()` — no new server endpoint needed.

**Why simplest sufficient:** investigation (below) shows the queue's startup auto-resume (`mergeQueue.kickAll()` on boot, added 2026-10-30 for #231) already re-runs a merge that was mid-flight when the process died — proven by an existing passing test (`merge_queue.test.js:233`, "a restart mid-queue picks up where it was"). The real, confirmed gaps are narrower than a full rebuild: (1) `rebuild_and_install.sh` restarts the merge server completely unconditionally today (lines 84-87, no gate at all) — that's the actual unaddressed half of this ticket; (2) the owner-facing text in `merge_progress.js` still says "Approve again" even though the queue already doesn't need that — stale guidance left over from before #231. Fixing exactly those two things, plus making "goes to the front" explicit and defensive (rather than relying on nobody-having-cut-in-line being merely incidental), is the minimum that satisfies both acceptance criteria without re-building a resume mechanism that already works.

**Tokens:** small, surgical diffs across 5 files + 2 small new files; no new service, no new endpoint, no new storage format.

**Capability:** removes a silent stall that previously needed Gil to notice and re-click Approve — more capable, not more passive (north star 3): the merge keeps moving without him watching for it.

---

## Investigation that shaped this plan

- `rebuild_and_install.sh` (lines 82-87) restarts `com.marvin.dashboard-webhook` via `launchctl kickstart -k` **unconditionally**, with no check at all for an in-progress merge. This is acceptance criterion 1's gap, confirmed by reading the file — nothing mitigates it today.
- The merge queue (`merge_queue.js`, `index.js:507-510`, marvin#231, merged 2026-10-30 — **before** the 2026-11-04 incident quoted in the ticket) already calls `mergeQueue.kickAll()` on every webhook startup, which re-evaluates each repo's persisted queue (`~/.claude/logs/merge-queue.json`) and re-runs whatever was `next` — including a PR that was mid-merge when the process died, since queue items are only removed on a terminal outcome (merged/failed/held), never while running. This is independently proven by the existing test `merge_queue.test.js:233`.
- `index.js:493-498` still runs `takeInterruptedMerges()` (from `merge_progress.js`), which logs `"... Approve again."` and emits a `state: 'failed'` UI event — text written before #231 existed and never updated to reflect that the queue now resumes by itself. This mismatch is the concrete, user-visible form of "instead of 'Approve again'" in the ticket.
- Nothing forces the resumed PR to the *front* explicitly today — it merely stays wherever it already was (which was already "next", since nothing can be approved while the server is down). I'm building an explicit `resume()` anyway: it's what the ticket literally asks for, it's defensive (covers the case where the item ever falls out of the persisted queue for any reason), and it gives the fix something concrete to test and point to, rather than relying on "it already happens to work."
- `GET /merge-queue` (already implemented, `index.js:170-176`) returns `{ repos: { "owner/repo": { items, failed, lastMerged, running } } }` — `running` is a PR url or `null`, exactly what the ticket says to poll.
- `merge_ops.js`'s `maxMergingMs = 45 * 60_000` is the existing convention for "how long a merge can reasonably run" — reused as the wait bound rather than inventing a new number.
- No bash test harness exists in this repo (no bats/shellspec) and `rebuild_and_install.sh` has never had direct tests — consistent with its two Python siblings, the new logic that decides when to stop waiting is extracted into a tiny, pure, pytest-covered function; `rebuild_and_install.sh` itself just calls it, exactly like it already calls `code_sync.py pull`.

## Decisions

None. This is a build-type ticket (CONTEXT.md's "Build-type ticket" — mechanical pass/fail gate, no metrics comparison) with no product choice in it: both the wait bound and poll interval are implementation defaults backed by existing repo precedent (`maxMergingMs`), not something needing Gil's judgment, and nothing in the issue or its four prior comments asks a question.

## Tests to write first

In `lib/tests/test_merge_server_wait.py` (new, mirrors `test_webhook_restart.py`'s `d(**kw)` idiom) — covers "a merge that takes longer than the wait bound," "two rebuilds in a row," and malformed/unreachable-server misuse:
1. `test_restarts_when_no_merge_is_running` — `decide(running=False, ...)` → `"restart"`.
2. `test_waits_while_a_merge_is_running_and_under_the_bound` — `decide(running=True, waited_s=0, bound_s=100)` → `"wait"`.
3. `test_restarts_anyway_once_the_bound_is_reached_even_if_still_running` — the break-it case: `waited_s >= bound_s` with `running=True` still returns `"restart"` (never blocks forever; the queue's own resume covers the interrupted merge).
4. `test_every_decision_carries_a_human_readable_reason` — mirrors the sibling scripts' same test.
5. `test_merge_running_is_false_when_the_server_is_unreachable` — `urlopen` raising `OSError`/`URLError` (connection refused, crashed server) → fail open, `False`, never raises.
6. `test_merge_running_is_false_on_malformed_json` — non-JSON body → `False`, never raises.
7. `test_merge_running_true_when_any_repo_has_a_running_pr` / `test_merge_running_false_when_nothing_is_running` — `{repos: {...}}` shape parsing, multi-repo.
8. `test_independent_calls_dont_share_state` — two `decide()` calls back to back with different args give independent answers (statelessness check for "two rebuilds in a row").

In `dashboard/test/merge_queue.test.js` (existing file, same `world()`/`make()` fixtures) — covers "a crash mid-merge" and "an interrupted PR that merged or closed meanwhile":
9. `it('resume puts an interrupted merge back at the front of the queue, ahead of an earlier real approval')` — approve PR 2 normally, then call `store.resume(repo, url(1))` for PR 1 (simulating the crash-recovery path, never separately approved), `kickAll()`, assert PR 1 runs before PR 2 despite PR 2's earlier `approvedAt`.
10. `it('resume is idempotent: calling it twice keeps one entry, still at the front')`.
11. `it('a resumed PR that merged or closed elsewhere is dropped on the next decision, not re-run')` — PR removed from the fake GitHub world, `store.resume(...)`, `kickAll()` → `w.runs` stays empty, item removed from the store.

In `dashboard/test/merge_gate_progress.test.js` (existing file, existing `takeInterruptedMerges` test at line ~296) — covers the stale-messaging defect:
12. Extend/add a case asserting the logged line no longer says "Approve again" and instead says the PR resumes automatically (the `detail` field in the returned event stays untouched, since nothing consumes it as an instruction to re-approve — only the human-readable log line changes).

## Task List

1. `lib/merge_server_wait.py` (new): pure `decide(running, waited_s, bound_s=2700)` and `_merge_running(url, timeout)` (GET `http://localhost:7878/merge-queue`, parse `{repos}`, fail-open to `False` on any network/JSON error) + `main()` that polls every 15s until `decide` says `"restart"`, then exits.
2. `lib/tests/test_merge_server_wait.py` (new): tests 1-8 above.
3. `dashboard/scripts/rebuild_and_install.sh`: before the existing `launchctl kickstart -k` restart (lines 84-87), inside the same `if launchctl print ...` guard, call `"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/merge_server_wait.py"` (blocking) so the restart only proceeds once it returns; the rebuild/install/relaunch steps above it are untouched (they still happen regardless of a running merge, per the ticket).
4. `dashboard/webhook-server/merge_queue.js`: add `resume(repo, url, { by })` to `createQueueStore()`'s returned object — re-adds/moves the item to the front (`approvedAt` below every current item's), clears any stale `hold`/`failed` entry for that url.
5. `dashboard/webhook-server/merge_progress.js`: change the trailing sentence of `takeInterruptedMerges()`'s log line from `"... Approve again."` to text reflecting automatic resume; leave the returned `event`/`detail` shape untouched (existing test at `merge_gate_progress.test.js:296` keeps passing unchanged).
6. `dashboard/webhook-server/index.js`: extract `const queueStore = createQueueStore()` (currently inlined at the `mergeQueue` construction), pass it as `store: queueStore`; in the startup `for (const { url, event } of takeInterruptedMerges())` loop, derive `repo = repoOfPr(url)` and call `queueStore.resume(repo, url)` when `repo` is non-null, before `mergeQueue.kickAll()` runs.
7. `dashboard/test/merge_queue.test.js`: tests 9-11 above.
8. `dashboard/test/merge_gate_progress.test.js`: test/assertion 12 above.
9. Run the full JS (`npm test` in `dashboard/`) and Python (`pytest lib/tests/`) suites; confirm nothing else regresses (no metrics-comparison gate applies — build-type ticket, mechanical pass/fail).