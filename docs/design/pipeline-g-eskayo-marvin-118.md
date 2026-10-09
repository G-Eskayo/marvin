I have everything needed. Here's the implementation plan for issue #118.

## North-star fit

**Reuses:** `machine_profile.registry_id()` already exists and is already used elsewhere (`device_status.py`) for exactly this purpose — identifying this machine stably by hardware UUID, not label. The evidence-schema section pattern (`## <Header>` → `extractSection`/`parseEvidence` in `mr_review.js`) and its rendering in `MrDetail.jsx`/`MrReview.jsx` already exist for three sections; this adds a fourth the same way. No new IPC, no new backend wiring: `listPipelinePrs` already spreads the full `evidence` object through to the dashboard, so a new key in `parseEvidence`'s return value reaches the UI for free.

**Simplest sufficient approach:** stamp a string at raise time (as the ticket itself chose over inferring from claim-label history) — one new formatting function, one new header constant, two new conditional UI lines. No schema version bump, no migration: old PRs simply lack the section, and the field is already specified as optional.

**Tokens:** spends a small, fixed amount once (a handful of lines across 4 files + tests); saves nothing but isn't meant to — it's a small, bounded feature. The bigger spend risk is repeating the merge-conflict loop that burned 3+ prior attempts; the plan below avoids that by building fresh against **current main**, not by resurrecting stale PR #360.

**User capability:** leaves Gil more able to spot which device actually raised a given PR (relevant now that the pipeline runs across Mac Mini + MacBook Pro) directly in review, instead of having to go dig. Pure capability add, no automation that removes judgment — the human still approves/denies exactly as before.

**Ticket's own stated fit:** none written in the ticket body — nothing to correct.

---

## Why not resume PR #360

PR #360 already implements this correctly in essence, but it has conflicted with main in `lib/mr_raiser.py`/`lib/tests/test_mr_raiser.py` on **8 consecutive automated rebuilds**. Checked against current main: main grew a new `## Code Review` section (commit `b77515a`, 2026-10-09) and a new `## Mutation Score` section (`mr_review.js`/`mr_review.test.js`) in the *exact same functions and fixtures* PR #360 touches, after PR #360 was first opened. Every rebuild lands on a main that has moved again. Rebuilding fresh on top of the current files (read above) sidesteps this — there's nothing to merge.

## A real bug this ticket would otherwise inherit

`machine_profile.load_or_build()` (`lib/machine_profile.py:97-111`) writes its cache file **outside any try/except** (`PROFILE_PATH.write_text(...)`). Today nothing on the PR-raising path calls `machine_profile`, so a permissions/read-only-filesystem problem there is invisible to `mr_raiser.py`. Wiring `registry_id()` into `_default_open_pr` directly would newly make a `~/.claude` permission failure (plausible in a sandboxed/headless pipeline run) **block every PR from being raised**, even after verification passed — turning an unrelated, low-stakes module's bug into a critical-path outage. `_format_device()` must therefore catch and fall back, matching the existing best-effort pattern already used for `_post_fit_check`/dev evidence in this same file.

## Implementation

**`lib/mr_raiser.py`**
- `import machine_profile  # noqa: E402` after the `sys.path.insert` line (same pattern as `mr_notification`).
- `_format_device() -> str`: return `machine_profile.registry_id()`, wrapped in `try/except Exception` → fallback `"unknown-machine"`.
- In `_default_open_pr`, insert `## Device\n\n{_format_device()}\n\n` right after the intro line, before `## Metrics Comparison` (matches the ticket's "alongside the existing sections," keeps order consistent with current main: Device → Metrics → Test Results → Dev Environment → Code Review).
- Update the module docstring's one-line schema list ("...dev-environment evidence attached...") to mention the device field, since it's a factual enumeration that would otherwise go stale.

**`lib/tests/test_mr_raiser.py`**
- Add an **autouse fixture** stubbing `mrr.machine_profile.registry_id` to a fixed value for every test in the module. Without it, all ~20 existing `_default_open_pr`-calling tests would start shelling out to `ioreg`/`sysctl`/`scutil` and writing `~/.claude/machine-profile.json` on whatever machine runs the suite — slow, non-hermetic, and a real shared-state/wrong-permissions risk in CI/sandboxes. This is a correction versus PR #360, which left this unguarded.
- Update `test_default_open_pr_body_uses_the_evidence_schema_headers` to assert `## Device` is present and first in order.

## Tests to write first

Python (`lib/tests/test_mr_raiser.py`):
1. `_default_open_pr`'s body contains `## Device` and the device value, with `registry_id` stubbed.
2. Order assertion updated: `## Device` < `## Metrics Comparison` < `## Test Results` < `## Dev Environment Evidence`.
3. `_format_device()` returns `registry_id()`'s value directly (happy path, unit-level).
4. **`_format_device()` falls back to `"unknown-machine"` and does not raise when `registry_id` raises** (covers the `~/.claude` permission/read-only-filesystem failure mode identified above — "a dependency failing").
5. **`_default_open_pr` still returns a PR url and still opens the PR when `registry_id` raises** (end-to-end: the critical raise-PR path survives this dependency's failure, body shows the fallback text instead of crashing).
6. Autouse stub in place → confirms existing tests stay hermetic (no new assertion needed, but verified by running the full file and checking no real `ioreg`/`sysctl` calls fire — can grep via a monkeypatched `subprocess.run` spy that asserts it's never called with those binaries, if wanted; optional).

JS (`dashboard/test/mr_review.test.js`):
7. `hasEvidenceSchema` still returns `true` for a body with the three required sections but **no** `## Device` (backward compatibility — PRs raised before this ships).
8. `parseEvidence` extracts `device` when present (both `PIPELINE_BODY` → `"mac-mini"`-style value and `MANUAL_SCHEMA_BODY` → a different stub, proving it's not hardcoded).
9. `parseEvidence().device` is `null` when the `## Device` header is absent.
10. `parseEvidence().device` is `null` (not a crash) when the `## Device` section is present but **blank** (a person hand-editing the PR body and leaving it empty — "a person's mistakes"/"empty input").
11. `parseEvidence` does not throw when the `## Device` section's content itself contains a `## ` sequence (malformed/adversarial content inside the stamped value) — documents existing shared section-parsing behavior under corruption without asserting it's "correct" (that limitation is pre-existing across all four sections, out of scope to fix here).
12. Update the existing `'returns nulls for missing evidence sections...'` exact-equality assertion to include `device: null`.
13. Already covered, no new test needed: `hasEvidenceSchema(null/undefined)` → `false` (existing test's `typeof body === 'string'` guard covers the new header too, since `parseEvidence` is never reached for a non-conforming body).

**UI (`MrDetail.jsx`, `MrReview.jsx`):** no existing render-test harness for these components in this repo (checked — only the electron/main logic module has a test file), so no new automated test is added here, consistent with how `subsystem`/`verdict` display is already untested. I'll verify visually via `npm run dev` in the dashboard (list card and detail view, with and without a `## Device` section) before calling this done, per the UI-change rule.

**Verify-fails-without-a-test-change check:** removing the `## Device` line from `_default_open_pr` fails test 1/2; removing the try/except fails test 4/5; removing `device` from `EVIDENCE_HEADERS`/`parseEvidence` fails tests 7-12; removing the UI conditionals isn't caught by an automated test (no harness exists) — covered instead by the manual dev-server check above.