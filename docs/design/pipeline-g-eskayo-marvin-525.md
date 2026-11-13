## North-star fit

- **Reuses:** `skills/qa-agent/scripts/tests/test_qa.py` — the existing test file and its pattern of importing script internals directly (`from qa_capture import build_entry`, `SCRIPTS = Path(__file__).resolve().parents[1]`) rather than a new test file. The `Path.home()` construction is already the established pattern in this same codebase, used at `qa_capture.py:17/22` and `qa_query.py:17` — the SKILL.md snippet is simply the one place that never adopted it.
- **Simplest sufficient approach:** a 3-line doc edit (SKILL.md's fenced snippet) plus a 1-line help-string edit (`qa_capture.py`), derived from data that already exists (`_PATTERN_TYPE_KEYWORDS`). No new abstraction, no new file.
- **Tokens:** spends a handful of tokens now; saves many later — every sub-agent that today copies the documented snippet burns a turn on `FileNotFoundError` before anyone notices it's a doc bug, not a runtime bug.
- **North star 4 (tool for tools):** directly serves it — this is the documented way other skills query the shared KB; it must work the first time it's copied.
- **More capable, not more passive:** yes — removes a silent landmine that currently forces whoever hits it to debug a false lead.

No decisions needed — the ticket's "What to build" section fully specifies the fix (inline `str(Path.home() / ...)`, `check=True`, dict-derived help string); there's no open design choice for the owner.

## Tests (written first)

All added to the existing `skills/qa-agent/scripts/tests/test_qa.py` — no new test file (composability: one test module per script area already established).

1. **`test_sub_agent_snippet_no_tilde_and_check_true`** — add a small test-local helper that extracts the fenced ` ```python ` block under `## Sub-agent usage` in `SKILL.md`; assert the block contains no literal `"~/` substring and does contain `check=True`. *(Acceptance criterion 1; breaking case: "snippet edited back to a `~` path".)*
2. **`test_sub_agent_snippet_extraction_fails_loudly_if_section_missing`** — call the same extraction helper against markdown text with the `## Sub-agent usage` header removed/renamed; assert it raises instead of silently returning nothing (so future docs drift can't make test 1 vacuously pass). *(Misuse the ticket's list didn't name: a person's edit mistake.)*
3. **`test_pattern_type_help_lists_every_keyword`** — run the real `qa_capture.py --help` via `subprocess.run([sys.executable, ...], capture_output=True, text=True)` (real CLI, not a mock) and assert every key of the imported `_PATTERN_TYPE_KEYWORDS` dict appears in stdout. *(Acceptance criterion 2; breaking case: "someone adds a 15th pattern type" — this test re-derives its expectation from the live dict each run, so it can only pass if the help text is actually built from the dict.)*
4. **`test_check_true_raises_on_query_failure`** — invoke the real `qa_query.py` via `subprocess.run([..., "--bogus-flag"], check=True)` (an argparse error forces a non-zero exit) and assert `pytest.raises(subprocess.CalledProcessError)`, confirming the `check=True` semantics the fix relies on actually surface an exception rather than leaving `json.loads` to choke on empty stdout. *(Breaking case: "`qa_query.py` exits non-zero".)*

Test against the real `qa_query.py` / real venv interpreter throughout (per `~/.agents/venv/bin/python -m pytest ...`, the convention this test file's own docstring already documents) rather than mocking `subprocess.run` — a mock would hide exactly the tilde-expansion bug this ticket exists to catch.

Out of scope: the ticket's "Recurrence check" probe (counting `FileNotFoundError: '~/` in sub-agent tool logs) is not in "What to build" or the acceptance criteria — flagging it here rather than building unscoped logging infra now, consistent with minimising added surface.

## Task List

1. Add the 5 tests above to `skills/qa-agent/scripts/tests/test_qa.py` (test-local extraction helper, no production code changes yet) — confirm they fail against current code.
2. Fix `skills/qa-agent/SKILL.md` lines 62–70: add `from pathlib import Path` inside the snippet, replace the two `"~/..."` strings with `str(Path.home() / ".agents/venv/bin/python")` and `str(Path.home() / ".agents/skills/qa-agent/scripts/qa_query.py")`, add `check=True` to the `subprocess.run` call.
3. Fix `skills/qa-agent/scripts/qa_capture.py` line 144–146: replace the hardcoded `--pattern-type` help string with `"mechanism type: " + "|".join(_PATTERN_TYPE_KEYWORDS)`.
4. Run `~/.agents/venv/bin/python -m pytest skills/qa-agent/scripts/tests/test_qa.py -v` — confirm all tests (existing + new) pass.
5. `marvin-show` the diff to Gil before opening the PR.