## North-star fit

**Reuses:** the repo-wide fix already merged for this exact symptom — `conftest.py`'s `_no_embedding_model_download` autouse fixture (root `conftest.py:163-170`), landed in PR #1163 (closing #1156, commit `71c86d38`), whose own message says it "Covers paper-dive's 35 and **improve's 2 cross_machine_merge tests** that had the same latent download." I verified this directly rather than trusting the commit message:
- `pytest skills/improve/scripts/tests/test_cross_machine_merge.py -v` → 6/6 pass in 0.70s.
- Same file under `pytest -n 6` (pytest-xdist, matching the ticket's own break-it list) → 6/6 pass, no cross-worker interference.
- Read `chromadb`'s `ONNXMiniLM_L6_V2.__call__` source (`.../onnx_mini_lm_l6_v2.py:258-270`): the only place `_download_model_if_not_exists()` is ever invoked. The root conftest fixture replaces `__call__` itself with `hashed_embedding`, so that call site is unreachable — this isn't a probabilistic guard, it's structurally impossible to hit the download path through any `collection.add()`/`.query()`, in any process, under any cache state (cold or warm), which is why it's safe under `-n 6` with no shared-cache race.

**Conclusion:** both acceptance criteria in #1098 are **already met** by code already on `main`. No change to `cross_machine_merge.py` or its test file's embedding mechanism is needed — the ticket's own literal suggestion (pass a fake `embedding_function` to each `get_or_create_collection` call) would be a second, redundant mechanism doing the same job the global fixture already does, which fails the Colton check (imitating a solved pattern instead of reusing it) and spends tokens for nothing (north star 1).

**Simplest sufficient remaining work:** two things the broader fix didn't cover, both cheap:
1. A **file-local regression test** for `test_cross_machine_merge.py` specifically — today only `lib/tests/test_no_model_download.py`'s synthetic "papers" collection exercises the "fails loudly if a download is attempted" guard; nothing exercises it through the real `sync_paper_knowledge` path. One small test + a local copy of `test_no_model_download.py`'s `no_download`-style fixture (same ~8 lines, two call sites don't justify a shared conftest per the composability rule) closes that gap and makes "verify fails when code changes without a test changing" concrete for this file.
2. The ticket's own `## Recurrence check` section (`probe: ci-onnx-download-failures`, baseline 6, check-on 2026-11-18) — required by the repo's "every fix gets an outcome check" decision (CONTEXT.md, Gil 2026-10-26) — isn't registered in `lib/purpose_metrics.py` yet, so the PR's fit check will warn without it.

**Tokens/compute:** spends a small, bounded amount (one new test, one new probe) rather than re-deriving a mechanism that already exists; saves the CI minutes and re-approval cycles the ticket describes, which is the whole point.

**Leaves the user more capable:** yes — closes a real, recurring CI-flakiness cost with no new manual step for Gil; the recurrence probe (once the Decision below is answered) gives ongoing, unattended visibility rather than requiring him to notice a six-run failure storm again.

---

## A gap in the repo's own convention (flagged, not worked around)

`purpose_metrics.py`'s PROBES convention (CONTEXT.md: "a named probe... that counts the fixed symptom **in a log that already exists**... a missing log means the symptom is absent (0), not unknown") assumes a local, offline-safe log file (`errors.jsonl`, `launches.jsonl`, the webhook log). **No such local log captures this symptom** — CI runs on GitHub-hosted `ubuntu-latest` runners (moved there in #1117 specifically so it *isn't* tied to Gil's Macs), and `main_red.py` only records *which* check failed, never the failure text inside a job's log. The only place "onnx_models"/`INVALID_PROTOBUF` ever appeared is GitHub's own Actions log, fetched live over the API — a fundamentally different failure mode (unreachable API ⇒ *unknown*, not *0*) than every existing PROBE. This is a real mismatch between the ticket's literal ask and the recorded convention, not something to quietly paper over — hence the Decision below.

## Decisions

<!-- marvin:decisions -->
### recurrence-probe: How should `ci-onnx-download-failures` be implemented?
- [ ] A: Exact fidelity — reuse `_ci_python_minutes`'s run/job-listing pattern (`lib/purpose_metrics.py:111`) to find "Python tests" job runs in the 7-day window; for any with `conclusion` in `{failure, timed_out}` only (bounded cost), fetch that job's raw log via `gh api repos/{repo}/actions/jobs/{id}/logs` and count it if it contains `onnx_models` or `INVALID_PROTOBUF` (case-insensitive). Matches the ticket's literal spec; breaks the "missing log ⇒ 0" PROBES convention (a GH API outage reads as unknown, handled like `_ci_python_minutes` already is — `check_issue` catches the exception and retries tomorrow).
- [ ] B: Cheaper proxy — same run/job listing, but count any "Python tests" job with `conclusion` in `{failure, timed_out}` in the window, no log-text fetch at all. Pure reuse of an existing call shape (zero new GH API surface), but trips on *any* Python-tests failure, not just this one — noisier against the baseline of 6.
- [ ] C: No new probe — close #1098 citing #1156/PR #1163 as the fix (already verified above), with a comment explaining the mechanism is structural (the download call site is unreachable, not merely guarded) so the original symptom can't recur through its original path; rely on the existing `test_no_model_download.py` suite as the standing repo-wide guard. Accept the fit-check's warning on the PR (not a block) rather than build a mechanism that doesn't fit the PROBES convention.

### regression-test: Add the file-local no-download regression test to `test_cross_machine_merge.py`?
- [ ] Yes — add it regardless of the recurrence-probe decision (cheap, closes a real coverage gap, matches "tests try to break it")
- [ ] No — the suite-wide `test_no_model_download.py` + autouse fixture is sufficient; skip it

---

## Tests to write FIRST

From the ticket's "How we'll try to break it," plus misuse cases it didn't list:

1. **No network** — new `test_sync_paper_knowledge_never_downloads_the_embedding_model` in `test_cross_machine_merge.py`: a local fixture monkeypatches `ONNXMiniLM_L6_V2.DOWNLOAD_PATH` to an empty tmp dir and `_download` to raise (same shape as `lib/tests/test_no_model_download.py`'s `no_download` fixture), then runs the "imports new entries" scenario (the one path that calls `col.add()`) and asserts it completes without the download guard firing. This is the one genuinely new test; everything else below is verification, not new assertions.
2. **Several processes at once / `-n 6` twice** — operational verification, not a new assertion (the mechanism is a per-process class-method monkeypatch, so there's nothing stateful to race): run `pytest skills/improve/scripts/tests/test_cross_machine_merge.py -n 6 -v` twice in a row. Already done once above (6/6 passed); repeat once more before closing.
3. **Fresh, empty HOME** — already covered unconditionally by root `conftest.py`'s `make_test_home` (every test in the repo runs under a fresh temp HOME); no new test needed, already exercised by the passing runs above.
4. **Each existing misuse case already in the file** (unreachable remote, malformed JSON, already-known ids not overwritten, cursor reuse, no-new-items) — already present and passing (6/6); no gap to fill.
5. **If Decision `recurrence-probe` picks A or B** — new tests in `lib/tests/test_purpose_metrics.py`, mirroring `test_ci_python_minutes_*`'s injectable-`fetch` style:
   - zero failures in the window → `0.0`
   - a failure inside the window is counted; one just outside the 7-day cutoff is not
   - no "Python tests" job in the listed runs → `0.0`, not an error (unlike `_ci_python_minutes`, which raises on "nothing measurable" — here zero failures is the expected steady state, not an error)
   - a job with a missing/malformed `conclusion` field is skipped, not counted
   - the run-listing `fetch` raising (GH API unreachable) propagates, matching `_ci_python_minutes`'s convention and `check_issue`'s catch-and-retry-tomorrow handling
   - **(Option A only)** the log-text fetch is only called for already-failed jobs (assert call count), a failed job whose log lacks both signature strings is not counted, one whose log contains either string (either case) is counted, and the log-fetch itself failing is handled the same as the run-listing fetch failing
   - the probe is registered: `"ci-onnx-download-failures" in pm.PROBES`

## Task List

1. [ ] Get the owner's answers on the two Decisions above (recurrence-probe approach; whether to add the file-local regression test).
2. [ ] Write `test_sync_paper_knowledge_never_downloads_the_embedding_model` (and its local `no_download`-style fixture) in `skills/improve/scripts/tests/test_cross_machine_merge.py` — only if Decision `regression-test` says yes.
3. [ ] If `recurrence-probe` = A or B: write the new probe's tests in `lib/tests/test_purpose_metrics.py` first (per the list above), confirm they fail against today's `purpose_metrics.py` (no such function/registration exists yet).
4. [ ] Implement `_ci_onnx_download_failures(...)` in `lib/purpose_metrics.py`, reusing `_ci_python_minutes`'s run/job-listing shape, per the chosen option (A: + bounded log-text fetch on failed jobs only; B: conclusion-only count). Register it in `PROBES` with baseline documentation pointing at #1098/#1156.
5. [ ] Run the new and existing tests green; re-run `skills/improve/scripts/tests/test_cross_machine_merge.py` once more under `-n 6` (twice) to reconfirm no regression.
6. [ ] If `recurrence-probe` = C: skip 3–5; instead draft the closing comment for #1098 citing #1156/PR #1163 and the verification evidence above, and confirm the PR's fit check only warns (doesn't block) with no Recurrence check registered.
7. [ ] Open the PR (or, if C and no code changed at all, close #1098 directly with the evidence comment) naming #1098, referencing #1156/PR #1163 as prior art, and carrying the Decisions section above for anything not yet answered.