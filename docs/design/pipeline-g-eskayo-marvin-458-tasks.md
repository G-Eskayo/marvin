1. `lib/brief_fallback.py::past_deadline`: add `grace_minutes: int = 0`; apply via `deadline + timedelta(minutes=grace_minutes)`. Fix the module docstring's "30 minutes later" → "an hour later (09:30, 10:00, 10:45)".
2. `lib/brief_fallback.py::should_run`: add `grace_minutes: int = 60`, forward to `past_deadline(...)`, include in the "deadline has not yet passed" reason string. Update docstring.
3. `lib/tests/test_brief_fallback.py`: add tests 1-4 above.
4. `lib/morning_brief.py::write()`: replace `path.exists()` with `brief_fallback.produced(path)` at the top gate; add a second `produced()` re-check immediately before `path.write_text(...)` — if true, return the existing path without writing.
5. `lib/tests/test_morning_brief.py`: add tests 5-8 above.
6. Run the five targeted suites; confirm the fail-before/pass-after split matches exactly.
7. PR description: carry forward the `retire-cross-machine-merge` decision unchanged; note that installing the six plists via `launchctl bootstrap` on the physical Mini/MacBook is a manual step this diff cannot perform.