## North-star fit

**Reuses:** the existing `No-test-reason:` commit-message mechanism (`lib/commit_check.py:36` `_REASON` regex, enforced via `lib/test_change_rule.py`'s `check()`/`MARVIN_RULES`) — rule 1's new guidance points at this real, already-enforced convention instead of inventing a new annotation or exemption path. No new code, tooling, or file is added; this is a three-sentence edit to one existing doc (`skills/prototype/SKILL.md`).

**Simplest sufficient approach:** the contradiction the ticket names is purely textual (two skills give conflicting defaults with no stated precedence, and rule 6 doesn't say how "absorb" avoids promoting untested code into production) — the fix is the same shape: wording, not mechanism. `skills/prototype/SKILL.md` already classifies as a doc (not matched by `CODE_EXT` in `lib/test_change_rule.py`), so no test infrastructure is needed or possible here — confirmed against the ticket's own "How we'll try to break it: Docs-only: exempt."

**Tokens:** spends a handful of tokens now (one small, well-scoped doc edit) to save tokens on every future prototype invocation — today an agent loading both `tdd` (always-on per `claude-config/CLAUDE.md`'s Development Defaults) and `prototype` rule 4 either burns tokens writing adversarial tests for code rule 6 says to delete, or silently skips them with nothing on record. Fixing the wording once removes that repeated judgment call. North star 4 (tool for tools: skills that don't contradict each other).

**More capable, not more passive:** this doesn't change what the agent *does* during prototyping — it removes an ambiguity the agent currently has to guess through alone, and closes the one real risk (untested prototype code slipping into production verbatim because rule 6 read as permission to "fold" it in).

**Ticket's stated fit** ("North star: 4, tool for tools") checks out against the code as above — no correction needed.

## Tests first

None. The ticket's "How we'll try to break it" section states "Docs-only: exempt," and this is confirmed against `lib/test_change_rule.py`: `skills/prototype/SKILL.md` has no extension in `CODE_EXT`, so `kind()` classifies it as `"other"` (docs) regardless — it was never going to trip the commit check or need a test change. No misuse case applies to a documentation wording fix; there's no input, dependency, concurrency, or permission surface to attack.

## Decisions

None needed. The "What to build" section gives exact replacement text for rules 4 and 6, and a concrete instruction for rule 1; nothing is left for the owner to choose. (The "Original ticket text" detail block includes a parenthetical `(CLAUDE.md Development Defaults)` after "global `tdd` default" that the triaged "What to build" section dropped — I'm treating "What to build" as authoritative/final and using its exact wording, since triage already resolved that phrasing.)

## Task List

1. Edit `skills/prototype/SKILL.md` rule 4 (currently line 25): append the sentence `This overrides the global \`tdd\` default for prototype code only. The prototype is the experiment, not the product.` to the existing "Skip the polish" bullet.
2. Edit `skills/prototype/SKILL.md` rule 6 (currently line 27): replace "fold the validated decision into the real code" with "carry the validated *decision* into the real code by re-implementing it under the normal `tdd` workflow. Never promote the prototype code itself", keeping the surrounding "either delete it or ... — don't leave it rotting in the repo" structure intact.
3. Edit `skills/prototype/SKILL.md` rule 1 (currently line 22): append guidance that a prototype stays uncommitted while it's alive, or, if it must be committed, the commit's `No-test-reason:` line (the real mechanism in `lib/commit_check.py`, ADR 0063 gate 4) states `prototype, deleted once <question> is answered`, naming the actual question.
4. Re-read the full edited file once to confirm the three rules still read coherently together and no other rule (2, 3, 5, "When done") now contradicts the new rule 6/1 wording.
5. No test changes, no commit-check reason needed (docs-only change, confirmed in Tests First above) — open the PR directly.