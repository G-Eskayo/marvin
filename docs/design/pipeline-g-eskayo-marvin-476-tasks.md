1. ✅ COMPLETED: In `skills/index/SKILL.md`, rewrite the `## Fallback: manual manifest matching` section into three explicit outcomes:
   - **Printed ranked results** (with or without the `INFO: Ollama unavailable — using tag fallback` line) → load those paths, nothing to do by hand.
   - **Printed `No relevant files found.`** → `retrieve.py` already tried tag matching too and found nothing; proceed without loading additional skills rather than repeating the same manifest scan by hand.
   - **Failed to run** (missing venv, script not found, a traceback) → the matching never happened; do it by hand — keep the existing numbered steps 1–7 here, unchanged, scoped only to this case.

2. ✅ COMPLETED: Delete the trailing paragraph restating manifest structure/fields since it's fully covered by the `## Manifest Structure` section and the `## Tag Namespaces & Fields` table.

3. ✅ COMPLETED: Verified edited section against all three acceptance criteria:
   - (a) script-printed-results vs script-failed-to-run are clearly separated ✓
   - (b) the numbered manual steps sit only under the failed-to-run case ✓
   - (c) the quoted `INFO: Ollama unavailable — using tag fallback` string matches `retrieve.py`'s stderr output exactly ✓
   - `model-scope` is still documented in the Tag Namespaces & Fields table (line 56) ✓

4. ✅ COMPLETED: No code or test changes — text-only edit to `skills/index/SKILL.md`. Design doc and Task List persisted as single files, not duplicated.