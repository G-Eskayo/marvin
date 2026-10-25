1. **Fix defect #1** — `skills/improve/scripts/daily_digest.py:335`: remove the stray `marker +` prefix; restore `OUT_FILE.write_text(header + health_section + content + "\n")`.
2. **Fix defect #2 in `daily_digest.py::main()`** — reorder: keep the `should_run()` call first (unchanged), then add `if OUT_FILE.exists() and brief_fallback.produced(OUT_FILE): skip` immediately after it (restores the old short-circuit, now content-aware), then generate, then keep the existing pre-write `produced()` recheck before `write_text`.
3. **Same fix in `research_digest.py::generate()`** — add the `out_path.exists() and brief_fallback.produced(out_path)` guard right after the `should_run`-equivalent gate (currently just `if brief_fallback.produced(out_path):` with no `.exists()` short-circuit guard — add it so an absent local file never triggers a remote SSH check at this point) and before the fetch/correlate work starts.
4. **Same fix in `run_colony.py::main()`** — add `if out_path.exists() and brief_fallback.produced(out_path): skip` right after the existing `should_run()` gate check, before `source_monitor.main()` runs, so the fetch/correlate steps aren't wastefully re-run on a day the digest is already written.
5. **Fix defect #3 — test isolation.** Add one new autouse fixture to `lib/tests/conftest.py`:
   ```python
   @pytest.fixture(autouse=True)
   def _isolate_machine_role(monkeypatch):
       # brief_fallback.should_run() resolves this machine's role via machine_profile.registry_id(),
       # which reads the real ~/.claude registry and, off the primary, can SSH a real peer.
       # Default every test to primary (the old, gate-less behavior); a test opts into the
       # standby path by overriding this or by passing device_id explicitly.
       import machine_profile
       monkeypatch.setattr(machine_profile, "registry_id", lambda: "mac-mini-test")
   ```
6. Create `skills/improve/scripts/tests/conftest.py` and `skills/research-colony/scripts/tests/conftest.py`, each with the identical fixture from step 5 (no existing conftest.py in either directory to extend).
7. Add test #8 (both variants), #9, #10 (three variants) from the "Tests to write first" list above, to `lib/tests/test_brief_fallback.py`'s sibling test files as named.
8. Edit `skills/improve/scripts/tests/test_daily_digest.py`'s existing `test_main_short_circuits_when_out_file_exists` — leave it textually unchanged; confirm (don't modify) that it now passes once steps 1–2 land. If it still fails after step 2, that's a sign step 2's ordering is wrong, not a reason to weaken the test.
9. Leave untouched (already correct, verified by direct read): `lib/brief_fallback.py`, `lib/tests/test_brief_fallback.py`, `lib/morning_brief.py`, `lib/tests/test_morning_brief.py`, `lib/health_checks.py`, `lib/tests/test_health_checks.py`, `lib/cron_health.py`, `CONTEXT.md`, all four `.plist` files, `skills/research-colony/scripts/tests/test_run_colony.py`.
10. Run only the targeted files listed under "Verify fails when code changes without a test changing" above; confirm each new/changed test fails against the current dirty-worktree code and passes after steps 1–6.
11. Add the Decisions section above to the PR body, unanswered.
12. In the PR description, state plainly: (a) `cross_machine_merge.py` is untouched pending the `retire-cross-machine-merge` Decision; (b) the actual Mini/MacBook launchd install-location swap is a manual `launchctl bootstrap`/`bootout` step on each physical machine that this diff cannot perform — until done, AC1 isn't in effect on the ground, only ready to be made effective; (c) name the three root-cause defects found and fixed (undefined `marker`, the dropped primary short-circuit, the missing test-isolation fixture), since that's the actual explanation for the prior "regressed/mixed" verdict, not a restatement of the previous (incorrect) diagnosis.
13. Surface item 12(b) directly, not only in the PR body — it's a step Gil must finish by hand.