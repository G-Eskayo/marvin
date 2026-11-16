## North-star fit

**Reuses:** the file's own existing structure — the `## Fallback: manual manifest matching` heading, its numbered-step format, and the already-present `model-scope` row in the `## Tag Namespaces & Fields` table (`skills/index/SKILL.md`, the table right after the fallback section). No new file, script, or mechanism; the fix is a rewrite of prose that already lives next to the code it describes.

**Simplest sufficient approach:** a text-only edit to one file (`skills/index/SKILL.md`). No code change — I read `skills/self-improve/scripts/retrieve.py`'s `retrieve()` (ollama-down branch at the `query_vector is None` check) and `tag_fallback()`/`main()` and confirmed they already do, end-to-end, everything the "manual" steps describe, then print the ranked output.

**Token spend:** saves tokens on the common path, same as the ticket states — an agent that sees `INFO: Ollama unavailable — using tag fallback` currently is told to re-open and hand-score all of `~/.claude/manifest.json`, duplicating work `retrieve.py` already did and already printed.

**Capability:** neutral on the human-facing test — this is MARVIN's own internal retrieval instruction, not user-facing; it makes MARVIN itself less wasteful, not the person more passive.

**Checking the ticket's stated fit (north star 1):** confirmed correct against the code as written. One gap in the ticket's own two-way split, though: reading `retrieve()` closely shows a **third** observable CLI outcome the ticket didn't name — the script can run cleanly, find nothing via semantic search *and* nothing via `tag_fallback()` (no `INFO:` line printed in that branch since Ollama was up), and `main()` prints `"No relevant files found."` to stdout. That's exactly the case PR #1352's code review flagged as uncovered ("script runs cleanly but prints no results... should be told either to proceed without loading skills or to try manual matching"). Redoing manual tag-matching here would just rerun the identical algorithm `tag_fallback()` already ran and already found empty — pure duplication, the same waste this ticket exists to remove. So I'm resolving it myself rather than leaving it a prose question: tell the agent to proceed without loading extra skills in that case. This doesn't conflict with any acceptance criterion (the "manual steps only under failed-to-run" criterion still holds) and directly closes the one piece of send-back feedback from the prior PR's review that bears on correctness.

The other two review notes from PR #1352: the `model-scope` field stays documented after deleting the restated paragraph — confirmed it's still covered by the `## Tag Namespaces & Fields` table's existing `model-scope` row, so no action needed there. The note about not duplicating the Task List verbatim across two design-doc files, and not hard-coding line numbers that'll go stale, is noted below for whoever persists this plan as the committed design doc (per ADR 0029, these docs land as files in this ticket's own PR) — this plan gives one authoritative Task List, not two, and favors section names over line numbers where the two diverge.

## Tests

Ticket's "How we'll try to break it": **Docs-only: exempt** — confirmed, since the only touched file is a prose instruction file (`skills/index/SKILL.md`) read by an agent, not parsed or executed by any script, and `retrieve.py` itself is unchanged. No code path, no input surface, nothing to break. In place of tests, verification is: re-read the edited section against all three acceptance criteria, and diff the quoted `INFO: Ollama unavailable — using tag fallback` string character-for-character against `retrieve.py`'s `print(...)` call to catch drift if that string changes.

## Decisions

None. The three-way split (printed results / printed "no results" / failed to run) is not a judgment call for the owner — it falls directly out of reading `retrieve()`'s two return paths and `main()`'s empty-result branch, and the resolution (proceed without loading, don't duplicate an already-empty scan) is the only answer consistent with this ticket's own stated purpose. Everything else in the ticket is fully specified (`ready-for-agent`, concrete "What to build" + acceptance criteria).

## Task List

1. In `skills/index/SKILL.md`, rewrite the `## Fallback: manual manifest matching` section (currently one intro line + 7 numbered steps + a trailing paragraph) into three explicit outcomes:
   - **Printed ranked results** (with or without the `INFO: Ollama unavailable — using tag fallback` line) → load those paths, nothing to do by hand.
   - **Printed `No relevant files found.`** → `retrieve.py` already tried tag matching too and found nothing; proceed without loading additional skills rather than repeating the same manifest scan by hand.
   - **Failed to run** (missing venv, script not found, a traceback) → the matching never happened; do it by hand — keep the existing numbered steps 1–7 here, unchanged, scoped only to this case.
2. Delete the trailing paragraph restating manifest structure/fields (the one duplicating what `model-scope`, `tags`, `calls[]` already mean), since it's fully covered by the `## Manifest Structure` section and the `## Tag Namespaces & Fields` table further down in the same file.
3. Re-read the edited section against all three acceptance criteria: (a) script-printed-results vs script-failed-to-run are clearly separated, (b) the numbered manual steps sit only under the failed-to-run case, (c) the quoted `INFO:` string matches `retrieve.py`'s stderr output exactly — plus confirm `model-scope` is still documented somewhere in the file after the deletion.
4. No code or test changes — this is the entire scope. No new files beyond whatever design doc the pipeline persists this plan as (one doc, one Task List — not duplicated into a second file).