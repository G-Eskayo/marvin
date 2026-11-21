1. `lib/label_catalog.py`: `FIXED`, `CORE`, `known_project_ids()`, `lookup()`.
2. `lib/label_catalog.py`: `label_call()`, `failed_label()`, `call_repo()` (reusing `pr_ticket_check`'s URL regexes/`repo_here`), `without_label()`.
3. `lib/tests/test_label_catalog.py` covering tasks 1–2 (tests #2, #4 lookup cases, #5, #6, #15's catalog half).
4. `bin/gh`: `_heal_labels()` + wiring into the non-interactive branch behind the `try/except ImportError`, `MAX_LABEL_HEALS`, dual stdout/stderr capture scoped to healable calls, `--body-file -` stdin-once handling, per-heal/refusal log lines.
5. `lib/tests/test_gh_gate.py` additions covering tasks #1, #3, #7–#13, #15's healing half.
6. `lib/project_onboard.py`: re-point `TRIAGE_LABELS`/`TRIAGE_LABEL_COLORS` at `label_catalog`; confirm existing `test_project_onboard.py` passes unchanged; add test #14.
7. `lib/purpose_metrics.py`: `_label_problems()` + `PROBES["label-problems"]` entry; `lib/tests/test_purpose_metrics.py` additions covering test #13's probe half.
8. Full `lib/tests` run (`~/.agents/venv/bin/python -m pytest lib/tests -q`) plus the dashboard JS suite untouched-check, since no dashboard file changed.