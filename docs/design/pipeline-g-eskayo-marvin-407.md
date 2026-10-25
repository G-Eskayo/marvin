## North-star fit

**What's actually in this worktree today** differs from what the design doc on disk (`docs/design/pipeline-g-eskayo-marvin-407.md`) claims. That doc says the committed `lib/seal_beta_ingest.py` implements a "fictional schema" (`temperature`/`category`/`device_uuid`). It doesn't — I read the file directly: it already models `schema`/`device.model`/`app.build`/`conversations{id,rating,ratingSkipped,lag,rewriteRate,speakers,ending,battery,minutes}`, already stores at `~/.claude/seal-beta/`, already groups by device→build. The plan on disk was already executed, almost line-for-line against its own task list. So this round is not "write the module" — it's "find why a correct-looking, fully-green implementation is still wrong."

**Reuses before adding:** nothing new structurally — `job_events`, the `_result()`/severity convention, `fcntl` locking, `JOB_PLACEMENT`, the plist, are all already in place and correctly wired (`run_all()` registration, `JOB_PLACEMENT["seal-beta-ingest"] = "mini"`, launchd plist pointing at the right program). This plan only corrects logic inside functions that already exist — no new files, no new abstractions.

**I re-verified the "mixed" verdict's regression claim directly** rather than taking the delta at face value: `~/.agents/venv/bin/python -m pytest lib/tests/ -q` right now → `1 failed, 2198 passed, 9 skipped`, and the one failure is `test_portfolio_flux.py::test_queued_generate_target_default_mac_mini_1`, an unrelated flake keyed to real free disk space (`insufficient headroom: 22.4 GB free, need 23.0 GB`) — nothing seal-beta touches that file. This matches baseline `pytest_failed=1` exactly. The prior comparison's `pytest_failed: 1→2` is most plausibly that same disk-dependent test (or a sibling threshold check in the same file) tripping at a moment when free disk was lower — not something this ticket's code caused. I'm not spending any further effort chasing it; it's out of scope and untouched by this diff.

**Where this plan diverges for real, not cosmetically:** I compared the shipped code against the actual source of truth — `~/Developer/clarity-captions/docs/beta/metrics-schema.md` and the ticket's own review comments — line by line, and found four concrete defects the existing (fully green) test suite hides because the tests were written to match the implementation instead of the real collaborator:

1. **`battery.maxThermalState` is modeled as a number (0–3) but the real field is a string enum** (`"nominal"|"fair"|"serious"|"critical"`, from `ProcessInfo.ThermalState` — see metrics-schema.md line 32: `"maxThermalState": "fair"`). `validate_conversation` requires it numeric, so **every real conversation's battery block fails validation** and gets quarantined row-by-row. The job stays green in `job_events` (no crash), `reports.jsonl` just silently stops gaining rows — exactly the "breaks silently" failure mode the north stars rule out. This is the single most consequential bug: ticket §4 explicitly requires "max thermal state" in the summary, and against real data it can never be populated. The first real report landed 2026-10-13 (per the comment thread) — this is live now, not theoretical.
2. **`is_low_sample` contradicts the ticket comment's own worked example.** Comment #4: "very short sessions (0.2 min, 10 lag samples) should be flagged as low-sample." Current code: `samples < 10` — at exactly 10 samples, it says *not* low-sample, and ignores `minutes` entirely. The existing test (`test_is_low_sample_exactly_10`) asserts the wrong behavior as correct.
3. **Device table bug directly contradicts comment #3.** `iPhone18,1` maps to `"iPhone 18"`; the comment says it must show as "the iPhone 17 family." The existing test (`test_device_plain_name_known_model`) asserts the bug as correct.
4. **`ingest_file`'s `enriched = {**conv, ...}` persists every raw field** — including `note` (tester free text) and `startedAt` — into `reports.jsonl` verbatim. Nothing in the ticket requires stripping it, but it's not needed by any summary field either, and keeping free text out of the private store is the safer default. No test currently checks what does or doesn't end up in the persisted row.

**Token cost:** this is a bugfix pass on existing functions, not new surface — cheaper than the already-spent cost of rewriting the module from scratch again.

**Capability, not passivity:** fixing (1) and (2) is what actually makes the ticket's promised per-device thermal/lag signal real instead of permanently empty — otherwise Gil gets a dashboard that looks like it's working and isn't, which is worse than not having it.

**No Decisions section.** All four fixes are corrections against an explicit, already-stated source of truth (the real schema doc, or a review comment's literal worked example) — not new product choices. The `is_low_sample` threshold numbers (30 samples / 1.0 min) are the same reversible defaults already chosen in the on-disk design doc; they were simply never implemented. Nothing here needs Gil to pick between options.

## Tests to write first

All against fixtures shaped like the **real** schema (string thermal states, the literal comment-#4 example values, etc.), in a temp `HOME`, never real `~/Library/Messages`. Each fixes a test that currently encodes the bug, or fills a gap the ticket/comments call for.

**Regression tests for the four found bugs (must change together with the code):**
1. `validate_conversation` with `battery.maxThermalState: "fair"` (the literal metrics-schema.md example) → valid, not rejected.
2. `aggregate()` over rows with thermal states `"nominal"`, `"fair"`, `"serious"`, `"critical"` → `worst_thermal_state == "critical"` (rank table, string in/string out).
3. `aggregate()` with one row carrying an unmapped thermal string (e.g. a future iOS value) → doesn't crash, doesn't win "worst" over a known state.
4. `validate_conversation` with `maxThermalState` as a non-string (e.g. `5`) → still rejected, with a clear reason (type-checked, not enum-checked).
5. Rewrite `test_is_low_sample_exactly_10` → `is_low_sample({"lag": {"samples": 10}, "minutes": 0.2})` is `True` (the literal comment-#4 example).
6. `is_low_sample({"lag": {"samples": 29}})` → `True`; `is_low_sample({"lag": {"samples": 30}, "minutes": 5.0})` → `False` (boundary).
7. `is_low_sample({"lag": {"samples": 100}, "minutes": 0.5})` → `True` (short duration alone is enough, independent of sample count).
8. Rewrite `test_device_plain_name_known_model` → `device_plain_name("iPhone18,1") == "iPhone 17"`.
9. `device_plain_name("iPhone18,2")` (an unconfirmed sibling id) → returns the raw id, not a guess.
10. `ingest_file` with a conversation carrying `note: "Lost it when the waiter talked fast"` and `startedAt: "..."` → the row written to `reports.jsonl` does **not** contain `note` or `startedAt`.

**Gaps against the ticket's own "Tests (adversarial)" list and comments, not currently covered:**
11. Duplicate conversation `id` appearing **twice within the same file's `conversations` list** (not just pre-seeded in the store) → second occurrence skipped, first counted.
12. One file with hundreds (e.g. 500) of conversations → all ingested, `result["valid"] == 500`, no slowdown/crash.
13. `conversations` key missing entirely from the top-level object (not just present-as-wrong-type) → whole-file quarantine.
14. Nested path exactly as comment #5 describes — `Attachments/ab/cd/<UUID>/seal-feedback-*.json` (3 levels deep) → found by the recursive scan.
15. `rating` as a string, `lag` as a string (not a dict), `battery` as a string (not a dict) → each conversation quarantined with a reason, never a `TypeError` escaping `validate_conversation`.
16. A directory literally named `seal-feedback-weird.json` → `load_report` catches `IsADirectoryError` (an `OSError`) and returns a quarantine reason, doesn't crash the scan.
17. A truncated/mid-write `seal-feedback-*.json` (half a JSON object) → quarantined this run; a second run with the completed file ingests cleanly.
18. A truncated line in `reports.jsonl` (simulating a prior crash mid-write) → `load_seen_ids` skips the bad line, keeps the valid ones, job still runs.
19. The store directory (`~/.claude/seal-beta/`) unwritable → `_write_report`/`_write_quarantine` raise and propagate (fails loudly via `job_events`), never swallowed.
20. `fcntl.flock` acquire/release around `_write_report`/`_write_quarantine` asserted via a lock spy (documented as mitigation, not proof of zero races, per the existing honesty convention).
21. A malformed/contradictory row — `rating: 7` **and** `ratingSkipped: true` simultaneously (a plausible "person's mistake"/app bug) — `aggregate()` doesn't go negative or crash on the `unrated` arithmetic; document which bucket wins (rated takes priority: counted in median, not in `skips`).
22. `PermissionError` on the attachments directory still propagates through `_cli` as a failed `job_events` run containing "Full Disk Access" (confirm this existing behavior with a direct test — currently only asserted at the `find_report_files` level, not through the CLI wrapper).
23. Attachments directory exists with zero matching files → `_cli` completes cleanly, `job_events` records a `passed` run with "0 files", no crash.

**Verify-fails-without-matching-code-change:** every test above asserts on the persisted artifact or return value (`reports.jsonl` row contents, `quarantine.jsonl` reasons, `aggregate()`/`summarize()` output, `device_plain_name()` return, `is_low_sample()` return) — never on an internal call being made — so none of them can be satisfied without the corresponding fix landing in `lib/seal_beta_ingest.py`.

## Task List

1. Fix `validate_conversation` in `lib/seal_beta_ingest.py`: require `battery.maxThermalState` to be a non-empty string (not numeric 0–3); add a `THERMAL_RANK = {"nominal": 0, "fair": 1, "serious": 2, "critical": 3}` table.
2. Fix `aggregate()`'s `worst_thermal_state`: rank via `THERMAL_RANK`, ignore unmapped strings when picking the max, return the string label (not a number).
3. Fix `is_low_sample()`: `minutes = conv.get("minutes", 0); samples = conv.get("lag", {}).get("samples", 0); return minutes < 1.0 or samples < 30`.
4. Fix `DEVICE_MODEL_NAMES["iPhone18,1"]` to `"iPhone 17"` (remove the incorrect `"iPhone 18"` entry).
5. Fix `ingest_file`'s row construction: build `enriched` from an explicit allowlist (`id, rating, ratingSkipped, lag, rewriteRate, speakers, ending, battery, minutes, device_model, app_build`) instead of `{**conv, ...}`, so `note`/`startedAt`/other raw passthrough fields never reach `reports.jsonl`.
6. Update `lib/tests/test_seal_beta_ingest.py`: rewrite the two tests that currently assert the bugs (`test_is_low_sample_exactly_10`, `test_device_plain_name_known_model`) to the corrected behavior, and add tests 1–10 (regression) and 11–23 (gap-fill) from the list above.
7. No changes needed to `lib/health_checks.py`, its tests, `JOB_PLACEMENT`, or the launchd plist — all already correct and already covered.
8. Run `lib/tests/test_seal_beta_ingest.py` and `lib/tests/test_health_checks.py` standalone, then the full `lib/tests/` suite once; confirm the only failure (if any) is the pre-existing `test_portfolio_flux.py` disk-space flake, and note it explicitly in the PR description so it isn't mistaken for a seal-beta regression again.