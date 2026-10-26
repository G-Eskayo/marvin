## North-star fit

**Reuses, before adding anything new:**
- `lib/project_catalog.py`'s existing project↔memory association (`build_catalog`'s "memory pointers" step, `tokens()`/`slug()` matching, `MATCH_THRESHOLD`) as the candidate-pairing stage — it already answers "which memory notes mention project X" and which repos have `CONTEXT.md`/ADRs (`docs{context,readme,adrCount}`, `github_docs_probe`). No new matching logic.
- `lib/marvin_launcher.py`'s existing `"judge"` launch kind (`KINDS["judge"]`, already used by `skills/safety-monitor/scripts/verify.py` and `lib/fit_check.py`) — "a checker must not share the context of what it checks," clean cwd, Haiku-tier — for the one step that genuinely needs judgment (is this actually a contradiction, not just a related update). `lib/fit_check.py`'s own shape (`_check`/deterministic facts always, injectable `judge: Callable[[str], str]` only when a fact is flagged) is copied directly, including its test strategy (inject a fake judge, no mocking of `subprocess`/Ollama needed).
- `skills/self-improve/scripts/background_review.py`'s detached-`Popen` + mtime-cooldown-lock pattern for the new PostToolUse hook, instead of inventing a new concurrency/backgrounding model.
- The existing append-only flagged-queue convention (`quarantine.md`, `suggestions.md`, `auto-fix-log.md`, `sync-log.md`) for where flags live, and the existing `lib/owner_decisions.py`-into-`handoff/SKILL.md` wiring shape for how a skill folds an external check's output into its own flow.
- `lib/marvin_hooks.py`'s single `HOOKS` table as the one place any new PostToolUse hook is registered (no parallel hook-wiring mechanism).

**Why this is the simplest sufficient approach:** the hard part of "did this decision supersede an earlier one" is semantic judgment, which the codebase already solved once (the Judge primitive) rather than reinventing with embeddings/ChromaDB (qa-agent's/self-improve's heavier infra) that this problem doesn't need — the corpus per project (a handful of memory notes + one repo's docs) is small enough that deterministic project-matching + a capped number of cheap Judge calls is enough. No new persistent vector store, no new background-agent shape.

**Tokens:** spends a small, capped number of Haiku `judge` calls (only when Stage A already found a same-project candidate — "B always [free], C only when B flags [costs]," `fit_check.py`'s own rule) instead of a Judge call on every write regardless of relevance. Saves tokens versus the alternative of dispatching a full Sonnet/Opus background-analyst agent (ADR 0016's rejected "dedicated infrastructure" option) for every memory/doc write.

**Phone-OS direction:** incremental — makes MARVIN's memory trustworthy regardless of which device/session wrote it, a precondition for "one computer, two machines" ever being safe to rely on for recall.

**User capability:** leaves Gil more capable — he stops being the one who has to notice "wait, that's not current" (as happened with Seal Speak's price) and instead gets it flagged automatically; he still makes the actual call on which copy is current (report-only, no auto-edits, per the ticket).

## Decisions

Genuinely open: how aggressively to spend the Judge call. Stage A (project-match) is free; Stage B (Judge) has a real per-call token cost that recurs on every qualifying memory/`CONTEXT.md`/ADR write, system-wide, which matters given the roadmap's M3 move to a $20-plan budget.

<!-- marvin:decisions -->
### judge-trigger: How many Judge calls should the live check spend per write?
- [ ] A: Judge every Stage-A candidate (every memory note + doc section the project-match surfaces) — highest recall, most calls (typically 1–3 per qualifying write).
- [ ] B: Judge only the single most textually-different candidate per write — cheaper, risks missing a contradiction when more than one older claim is stale.
- [ ] C: Skip the Judge entirely; treat any Stage-A project match as itself a flag — zero extra LLM cost, but will over-flag routine same-topic updates that merely add detail rather than contradict.

### sweep-cadence: Does the one-off sweep (acceptance criterion 3) ever re-run, or truly one-off?
- [ ] A: Truly one-off — run once by hand after this ships, never scheduled.
- [ ] B: One-off now, but leave the `sweep` subcommand in place so a future ticket can decide to schedule it (no scheduling built in this ticket either way).

## Tests (written first)

The ticket has no "How we'll try to break it" section, so this list is derived directly from the north-star's own adversarial-testing definition, scoped to what this checker actually touches: memory files, a project's `CONTEXT.md`/`docs/adr/*.md`, the project catalog cache, the Judge call, and the hook that triggers all of it.

1. **The planted case itself**: memory contains a note stating "Seal Speak is free forever"; a new write states "$5 app"; `check_claim()` (Stage A + injected fake judge returning CONTRADICTS) returns a flag naming the stale file. This is the acceptance-criterion-1 test.
2. **True negative**: a new write about the same project that only adds detail (judge returns CONSISTENT) produces no flag — proves the checker isn't just "same topic = flag."
3. **No project match**: a memory note that doesn't match any catalog project (e.g. a generic `feedback-*` note) → zero candidates, zero Judge calls, no flag — proves Stage A gates Stage B and the Judge is never invoked needlessly.
4. **Empty / malformed input**: an empty file write, a write with no frontmatter, a write that's pure whitespace, a `MEMORY.md` index write (must be excluded — it's an index, not a memory, same exclusion `project_catalog.discover_memory()` already applies) — all no-op without raising.
5. **Huge input**: a memory corpus of hundreds of files and a repo with dozens of ADRs — Stage A candidate count must stay bounded (capped per Decision `judge-trigger`), not O(n²) Judge calls across the whole corpus.
6. **Dependency failures**:
   - `project_catalog`'s catalog file missing or stale/corrupt JSON → check degrades to "no candidates" (reported, not crashed), matching `project_catalog.read_catalog`'s existing graceful-`None` behavior.
   - the Judge launch (`marvin_launcher.launch("judge", ...)`) times out, returns a non-zero exit, or returns unparseable text → treated as "couldn't judge," not silently "no contradiction."
   - target repo has no local path and the `gh api` docs fetch fails (network/rate-limit) → same graceful skip, not a crash, matching `github_docs_probe`'s existing `except Exception: pass`.
7. **Repeats / idempotency**: running the live check twice on the same write (e.g. an editor auto-save firing Write twice) must not duplicate the same flag in `contradictions.md`, and must not spend a second Judge call for an already-flagged pair.
8. **Concurrency**: two sessions on two machines write conflicting memory notes for the same project within the hook's cooldown window — mirrors `background_review.py`'s own `COOLDOWN_SECONDS` test case; verify the second write's hook either coalesces into the same pending check or still eventually runs (no silent drop), and that two processes appending to `contradictions.md` concurrently don't corrupt it (same append-safety expectation as `retrospective-log.md`).
9. **Wrong permissions / machine**: `~/.claude/contradictions.md`'s parent directory not writable, or running on a machine where `host_os.memory_dir()` doesn't exist yet → fails loud/logged (via the existing `hook_errors.log_hook_error` pattern), never silently swallowed, matching the roadmap's "silent failure is the recurring real problem" principle.
10. **Stale state**: the project catalog says a project has no local path, but it actually does now (catalog hasn't refreshed) → candidate search must not hard-fail; it's an acceptable, documented gap (same one `project_catalog.py` itself already documents for its own data), not something this ticket needs to fix.
11. **A person's mistake**: Gil hand-edits `contradictions.md` (e.g. deletes a line to "resolve" a flag) — the sweep/live-check must not treat a missing prior flag as needing to be re-derived identically; re-running must not re-add a flag Gil already removed by hand within some reasonable window — exact behavior here is intentionally out of scope for this ticket (no resolution/dismissal UI is being built), but the test proves the checker doesn't fight a hand-edit (append-only, never rewrites existing lines).
12. **Hook trigger precision**: PostToolUse fires on Write/Edit/MultiEdit to unrelated files (a Python source file, a random `.md` in some other project) → hook exits immediately without reading memory/catalog at all — proves the path filter (memory dir, `CONTEXT.md`, `docs/adr/*.md`) is correct and cheap, mirroring `background_review.py`'s own `in_handoffs` check.
13. **One-off sweep, acceptance criterion 3**: run against a fixture memory directory + fixture repo containing a known contradiction and a known non-contradiction → report lists exactly the real one, under the correct repo heading, and **no file on disk is modified** (report-only guarantee, asserted by hashing every input file before/after).

## Implementation Status

### ✅ Completed Tasks

1. **✅ DONE** — Add `judge`-style candidate lookup to `lib/stale_decision_check.py`: `find_candidates(new_text, project_hint=None) -> list[Candidate]`
   - Reuses `project_catalog.read_catalog()`/`tokens()` ✓
   - Matches against project's memory, CONTEXT.md, docs/adr/*.md, README.md ✓
   - Returns up to 8 candidates ranked by relevance ✓

2. **✅ DONE** — Add Judge step: `judge_contradiction(claim, state) -> Flag | None`
   - Uses `marvin_launcher.launch("judge", ...)` with Haiku ✓
   - Injects rubric, parses verdict, returns Flag or None ✓
   - Fails open (no crash on Judge error) ✓

3. **✅ DONE** — Add `check_claim(file_path, text) -> list[Flag]` entry point
   - Composes find_candidates + judge_contradiction ✓
   - Idempotent against contradictions.md ✓
   - Tests written and passing (12+ test cases) ✓

4. **✅ DONE** — Add `sweep() -> list[Flag]`
   - Iterates all memory files (excluding MEMORY.md) ✓
   - Calls check_claim on each, collects flags ✓
   - Report-only (caller appends to contradictions.md) ✓
   - Tests written and passing ✓

5. **✅ DONE** — Add contradictions.md template and readers
   - `~/.claude/contradictions.md` quarantine-style template ✓
   - `open_flags()` reads unresolved flags ✓
   - `_parse_flag_header()` and `_is_resolved()` utilities ✓

6. **✅ DONE** — Write `lib/stale_decision_hook.py`
   - PostToolUse hook with detached Popen pattern ✓
   - 5-minute cooldown lock ✓
   - Triggers on memory/CONTEXT.md/docs/adr/*.md writes ✓
   - Logs to `.stale_decision_check.log` with start/end markers ✓

7. **✅ DONE** — Register hook in `lib/marvin_hooks.py`
   - Added to HOOKS list with correct matcher (_EDITS = "Write|Edit|MultiEdit") ✓
   - Note added that `marvin_hooks.py install` must be run on each Mac after merge ✓

8. **✅ DONE** — Update `skills/handoff/SKILL.md`
   - Added rule to check contradictions.md before writing handoff ✓
   - Fold flagged contradictions into "Key decisions made" / "Open questions" ✓

9. **✅ DONE** — Update `skills/self-improve/SKILL.md`
   - Added gate to check contradictions.md before codifying patterns ✓
   - Prevent locking in disputed intent ✓

10. **✅ DONE** — Write test suite: `lib/tests/test_stale_decision_check.py`
    - 19 comprehensive tests, all passing ✓
    - Covers: tokenization, snippet extraction, candidate matching, judge parsing, flag operations, hook patterns
    - Uses mocks for catalog/judge (no subprocess/network overhead) ✓
    - See test output: `19 passed in 0.47s` ✓

### ⏳ Pending: Decisions and Final Wiring

11. **AWAITING DECISION** — `judge-trigger` and `sweep-cadence` (see Decisions section above)
    - Once decided: finalize step 2's judgment strategy
    - Once `sweep-cadence` is known: wire launchd job if "daily" / "weekly"
    - Note: all code is in place; scheduling is the remaining piece

## Task List (for reference)