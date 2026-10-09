## North-star fit

**Reuses before adding anything new:** the per-project profile machinery (`config/projects/*.json`, `project_profile.py`) already does three of the five acceptance criteria today and needs no new mechanism:
- AC1 (build the app, report the real result) — already true. `clarity-captions.json`'s `spike-app` tier is `required: true` and runs a real `xcodebuild` (enabled 2026-10-05, commit `00b7462`); the ticket's own "disabled in the project's profile" quote is stale evidence from before that change. The real gap PR 31 exposed was a missing bundle resource, which this required tier already would have caught now that it's on.
- AC3 (route to a capable machine) — already true. `_select_for_profile`/`select_machine` (task_dispatch) already pick a machine from `profile["machines"]`, and `run_ticket.run()`'s `except pp.EnvMissing` already releases the claim and calls `_trigger_redispatch()` with no strike/breaker hit when a machine lacks a capability. I only need `have("simulator", env)` to exist so this existing path fires correctly for screenshot capture.
- AC5 (project instructions read) — covered by one generic addition to `_default_executor`'s prompt (checks for `docs/agents/pr-requirements.md` in the worktree, same way it already tells every project to read `CLAUDE.md`/`CONTEXT.md`/`docs/adr/`), not a per-project edit — generalizes to every future project with such a file, not just clarity-captions.

**What's actually new:** a real iOS-simulator screenshot driver (doesn't exist at all today), and dashboard parsing/flagging for its multi-screenshot evidence shape (today's dashboard only understands one-screenshot-or-N/A).

**Correcting the ticket's own "Decision to make":** it asks for "app states that don't need a microphone or speech model." Marvin's pipeline cannot add that preview-state support itself — this ticket is scoped to the `marvin` repo, and the app's launch-argument handling lives in `clarity-captions`, a different repo the executor has no write access to. So the simplest *sufficient* scope here is: build generic, profile-declared, launch-argument-driven capture plumbing in marvin (the mechanism), and in clarity-captions' profile enable only the one scenario that is safe today — a bare launch with no args, varied by light/dark and portrait/landscape. Per the owner's own comment, tapping "Start" is what spins up the speech engine, not app launch — so a bare-launch screenshot is genuinely safe and genuinely real evidence (it already would have caught PR 31's "project could not even be generated" failure). Additional per-screen scenarios are blocked on clarity-captions adding its own preview launch argument — that's follow-up, cross-repo, out of this ticket, and I say so plainly rather than quietly shipping scenarios that would just screenshot the same launch screen under different labels.

**A prior attempt exists and has a real bug worth not repeating:** PR #361 (already raised against this ticket, now `CONFLICTING` after 4 send-backs for a stale-base conflict in `test_mr_raiser.py`, not a content rejection) built most of this shape, but its `simulator_capture.py` boots a simulator and screenshots it **without ever installing or launching the built app** — every "scenario" would capture the same blank springboard, not the app. It also hardcodes the simulator device name `"temp-device"`, which would collide under parallel dispatch (ADR 0052, already live). I'm reusing its scenario data shape (`screen`/`dark`/`orientation`/`launch_args`, its input sanitization, its `ticket_touches_ui(ui_paths=...)` generalization) because those parts are sound, but fixing install/launch and the device-naming collision, and rebuilding against today's `main` so the stale-base conflict can't recur.

**Tokens:** spends a small, bounded amount of new code (one new module, a few profile fields, dashboard parser additions) to stop a recurring, expensive failure mode — real app-build/run bugs reaching the owner undetected, costing their own manual-build time each time. Saves tokens long-term by making *any* future iOS-simulator project able to reuse the same plumbing with zero new code, just profile config.

**More capable, not more passive:** this doesn't remove the owner's judgment — it gives review (dashboard) a clear, honest flag for exactly the cases that previously slipped through silently (PR 31, PR 33), so the owner spends their attention only where it's actually needed instead of re-discovering breakage by hand.

**Known, explicitly out-of-scope gap found during this audit:** `killer-sudoku.json` has no app-build tier at all (only `swift-tests`), so AC1 is *not* met there. It's a macOS app with no evidence anywhere in this ticket or clarity-captions' history — not part of what this ticket's acceptance criteria were written against. I'm flagging it rather than silently fixing or silently ignoring it; it should be its own ticket.

## Tests to write first

The issue has no literal "How we'll try to break it" section, so this list is built from (a) the three denial/evidence comments on the ticket, which are binding requirements, and (b) ADR 0063's misuse categories applied to every new/changed unit. Tested against the real collaborator (`xcrun simctl`) wherever possible — this worktree is on the machine the ticket is claimed on (`claimed:macbook-pro`), which already has Xcode 27 + an iOS simulator runtime, so the mocked-everything approach PR #361 took is not necessary for the core round trip.

**From the ticket's own denial/evidence comments (binding):**
1. A required build tier that fails for real (e.g. a missing committed resource, PR 31's exact failure) must block the PR — integration-level test using the real `Measurer.__call__` against a profile whose build command genuinely fails (a real non-zero shell command, not a mocked subprocess), asserting `raise_mr` never fires.
2. The dev-evidence text for a bare-launch screenshot must never claim more than what was exercised (no implied "live capture verified") — guards against a PR silently looking more verified than PR 33 actually was.
3. **Correctness bug fix as a test**: capturing a scenario must actually `simctl install` + `simctl launch` the built app with its bundle id and `launch_args` before screenshotting — a sequencing test (mocked collaborator, asserting call order) plus a skip-if-no-simulator real-collaborator test that the screenshot differs from a pre-launch/springboard baseline (not just "file exists, nonzero bytes," which is too weak to prove the real app was ever shown).

**Bad/empty/huge/malformed input:**
4. `validate_scenario`: missing `screen`, non-bool `dark`, invalid `orientation` (kept from #361).
5. `screen` with path traversal, null bytes, or pathological length → sanitized, never escapes `docs/evidence/`, never crashes.
6. `launch_args` containing shell metacharacters, non-string entries, or absurd length → sanitized/rejected, never reaches `subprocess.run` unsanitized.
7. Empty `scenarios` list → `[]` back, no simulator ever booted (kept from #361).
8. Malformed PR-body markdown (truncated image syntax, a `screen` name containing `]`/`)`)→ `parseDevEvidenceSection` never throws, dashboard falls back gracefully.
9. `have("simulator", env)` when `xcrun` returns truncated/non-JSON output → caught, returns `False`, never raises.

**Each dependency failing:**
10. `xcrun`/`simctl` missing entirely → `EnvMissing` (not a ticket failure) — for boot *and* for the new install/launch calls specifically.
11. `install` fails (bad/corrupt bundle) → that scenario reports failed with a reason; other scenarios still run; ticket is not failed.
12. `launch` succeeds but the app crashes immediately → detected as a failure, not silently screenshotted as a success.
13. `screenshot` produces a 0-byte file → treated as a failure, never a false success.

**Repeats and concurrency:**
14. **Bug fix as a test**: two scenarios captured back-to-back, and two *concurrent* `capture_scenarios` calls (simulating ADR 0052 parallel dispatch), must not collide on simulator device naming — replaces #361's hardcoded `"temp-device"` with a worktree/ticket-scoped unique name; test asserts two concurrent calls get distinct device identities.
15. A simulator left booted by a previous crashed run (stale device, same name) must not hang or error the next run — boot is idempotent.
16. Build-output cleanup (`drop_build_output`) must run strictly *after* evidence capture in `run_ticket.run()` — a regression test on that ordering, since silently swapping it later would quietly break screenshot capture with nothing else catching it.

**Wrong permissions / wrong machine:**
17. A machine with Xcode but only a watchOS runtime (no iOS) → `have("simulator")` is `False` (kept + extended from #361).
18. `docs/evidence/` not writable (disk full) → surfaces as a flagged scenario failure, not an unhandled crash that fails the whole ticket.

**Stale state:**
19. A leftover device from a previous crashed run with the same derived name → reused or disambiguated, never a hard failure on `create`.

**A person's mistakes:**
20. A profile author typos `orientation: "Portrait"` (wrong case) → rejected clearly, not silently defaulted.
21. A profile author omits the app's bundle id / product path → capture fails with an actionable reason in the PR; ticket is not blocked (same principle as the existing dashboard-screenshot `except` path).

**Dashboard (real parser functions, no collaborator to fake):**
22. Multi-screenshot PR body (2+ screens, mixed light/dark/portrait/landscape) parses into a structured `screenshots` array.
23. All-scenarios-failed body → `missingEvidence: true`, `failed` reasons surfaced.
24. Partial failure (1 ok + 1 failed) → both preserved, not one clobbering the other.
25. **Non-regression**: the existing single-screenshot/N/A schema (marvin's own dashboard UI PRs, in production use today) still parses exactly as before.
26. `PrCard`/`MrDetail` render the clear flag line when `missingEvidence` is true, and do *not* render it for a clean/N/A case — `renderToStaticMarkup` component test, matching this repo's existing convention (`devices.test.jsx`).

**Verify fails when code changes without a test changing:** each new function above (`simulator_capture.install_and_launch`/`capture_scenarios`, `have("simulator", ...)`, `_format_dev_evidence`'s multi-screenshot branch, `parseDevEvidenceSection`'s new branches, the `_default_executor` doc-check, the `_select_for_profile`/`EnvMissing` reuse path) has at least one test whose assertion would fail if that function's behavior changed, not just a smoke test that it runs.

## Implementation plan

1. **`lib/project_profile.py`** — add `have("simulator", env)`: checks `xcrun simctl list runtimes --json` for an `iOS-` prefixed runtime (not just Xcode/watchOS present). Pure addition, no existing behavior changed.

2. **`lib/evidence_capture.py`** — generalize `ticket_touches_ui`/`_is_ui_path` to accept a caller-supplied `ui_paths` tuple (default stays `UI_PATH_PREFIXES`), so profile-based projects can declare their own UI path prefixes (e.g. `Apps/Spike/`) instead of only the hardcoded dashboard paths.

3. **New `lib/simulator_capture.py`** — `validate_scenario` (screen/dark/orientation/launch_args, sanitized) and `capture_scenarios(worktree_path, scenarios, app_bundle_id, app_path, timeout_s)`:
   - boots a simulator with a **worktree/ticket-scoped device name** (fixes #361's hardcoded-name collision risk),
   - `simctl install` the built `.app` (located via a profile-declared derived-data convention, see #5),
   - sets appearance/orientation,
   - `simctl launch` with the scenario's `launch_args`, waits briefly for the UI to settle,
   - screenshots to `docs/evidence/`,
   - terminates the app and shuts the simulator down in a `finally`, even on failure,
   - raises `EnvMissing`/`TestTimedOut` for machine-level problems (reused from `project_profile`/`evidence_capture`), returns a per-scenario `{ok, screen, path/reason, appearance, orientation}` otherwise so one scenario's failure never blocks the others.

4. **`lib/project_profile.py` `Measurer`** — `evidence()` calls a new `_capture_dev_evidence_if_configured()`: if the profile declares `evidence.dev.capture` scenarios *and* `ticket_touches_ui(ui_paths=profile.get("ui_paths"))`, run `simulator_capture.capture_scenarios`; build `{na: False, screenshots: [...], failed: [...]}` or the all-failed/na-fallback shapes. `EnvMissing` propagates up to `run_ticket.run()`'s existing handler unchanged — reuses the release-claim-and-redispatch path, no new routing code.

5. **`lib/mr_raiser.py` `_format_dev_evidence`** — add the multi-screenshot branch (one `![caption](path)` per screen) and an all/partial-failed branch, using the **same existing `⚠ **Screenshot missing...**` wording** the single-screenshot failure path already uses, so there is one consistent marker string across both PR-body shapes for the dashboard to key off of.

6. **`config/projects/clarity-captions.json`**:
   - change the `spike-app` build command's derived-data path from a `mktemp`+`trap`-deleted dir to a fixed worktree-relative path (so the capture step can find the just-built `.app`); add that path to `build_output` for post-run cleanup.
   - add `evidence.dev.capture`: one scenario family — bare launch (no `launch_args`), light/portrait, light/landscape, dark/portrait, dark/landscape. No per-screen scenarios yet (documented why, see North-star fit).
   - `app_bundle_id`/product name read from `Apps/Spike/project.yml`/Info.plist by whoever executes this ticket (I don't have read access to the clarity-captions clone from here to fill in the real value now).
   - update `evidence.dev.na` fallback wording for when the tier is disabled or a non-UI ticket runs.

7. **`lib/sandbox_orchestration.py` `_default_executor`** — generic addition: if `worktree_path / "docs/agents/pr-requirements.md"` exists, add one line to the prompt telling the agent to read it before planning/PR'ing. Covers clarity-captions today and any future project with the same file, with zero per-project config.

8. **`dashboard/electron/main/mr_review.js` `parseDevEvidenceSection`** — add branches for the multi-screenshot and failed-scenario text shapes from step 5, computing `missingEvidence: !na && (!screenshots || screenshots.length === 0)`. Keep the existing `na`/single-screenshot branches untouched (non-regression for marvin's own dashboard evidence).

9. **`dashboard/src/components/PrCard.jsx` and `MrDetail.jsx`** — render a clear warning line (`⚠ UI change — no screenshot evidence captured`) when `pr.evidence.devEvidence?.missingEvidence`, following the exact existing pattern used for `!pr.hasSchema`.

10. **`CONTEXT.md`** — update the clarity-captions paragraph under "Per-project execution profiles" to describe the new capture capability precisely (what's captured today — bare launch only — and what's explicitly deferred to clarity-captions' own follow-up work), not an overclaiming one-liner.

No new ADR file — this extends the existing "Per-project execution profiles" design-decision log in `CONTEXT.md`, matching how the prior (reverted-by-conflict) attempt already did it.