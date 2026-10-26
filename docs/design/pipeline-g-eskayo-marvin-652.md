## North-star fit

**Reuses, before adding anything new:**
- `lib/project_catalog.py`'s `tokens()` (cheap lexical overlap) and `discover_memory()` (reads `~/.claude/.../memory/*.md`, truncates to 1500 chars, skips `MEMORY.md`) — the pre-filter and the memory corpus reader.
- `skills/paper-dive/scripts/continuity_checker.py`'s shape (`extract_core_claim`/`classify_continuity`/`_parse_continuity_result`): an injectable `chat_fn`, a local Ollama `qwen2.5:14b` judge, `VERDICT:`/`RATIONALE:` parsing. I'm duplicating the small `ollama_chat` helper rather than importing it — `continuity_checker.py` is scoped to paper-dive's Chroma/paper domain and lives under a different skill's `sys.path` root; `logic_auditor.py` and `continuity_checker.py` already each keep their own copy rather than share one, so a third copy matches existing precedent, not a new pattern.
- `skills/self-improve/scripts/background_review.py`'s detached-subprocess-with-cooldown pattern — "a real LLM call here would otherwise stall the hook chain," so the PostToolUse hook spawns the check non-blocking instead of calling Ollama inline.
- `skills/handoff/scripts/emit-resume-prompt.py`'s PostToolUse stdin-JSON skeleton (`tool_name`/`tool_input.file_path`, fail-silent).
- `lib/output_contracts.py`'s `suggestions_state()` — a generic `## `/`**Status**:`/`**Added**:` block reader already written; the new flags file reuses it verbatim instead of a new parser, and gets a `Contract` entry for free Health tracking.
- `~/.claude/suggestions.md`'s exact entry grammar (confirmed by reading the live file) — the new `stale-decisions.md` entries use the same shape.
- `lib/session_start_report.py`'s `check_*()` + `_safe()` pattern — a new `check_stale_decisions()` added the same way `check_suggestions()` already works (inline regex, no new dependency), which is how *both* a handoff-resuming session and a self-improve-triggered session actually see it (SessionStart fires regardless of which skill resumes — more direct than editing two separate SKILL.md files with duplicated prose).
- `skills/architecture-review`/`audit`'s "report to a queue, never auto-edit" rule, and `feedback-use-outbox-not-scratchpad-for-deliverables` — the one-off sweep writes a report, it doesn't touch memory or repo files.
- `lib/host_os.memory_dir()` for the memory path (already handles the cross-machine re-rooting and malformed-settings fallback — no need to re-derive or re-test that).

**Why this is the simplest sufficient approach:** no new ChromaDB collection, no new calibration/review-feedback system (ADR 0015's quarantine loop is a bigger mechanism than this needs — AC2/AC3 only ask for a flagged list surfaced and a report, not a trained threshold). Detection is two cheap stages — lexical overlap first, LLM judge only on survivors — which directly targets why the last two attempts likely timed out (an unbounded all-pairs LLM sweep over ~140 memory notes, or a synchronous Ollama call inside a hot-path hook).

**Where it spends/saves:** spends a few Ollama calls (local, $0) only on lexically-overlapping pairs; saves by never calling an LLM on unrelated files, and never blocking the interactive loop (detached subprocess, per `background_review.py`'s own stated reason for existing).

**Does it leave Gil more capable, not more passive?** Yes for the live check (catches a wrong-answer risk before it propagates, the exact failure that opened #652) — it flags, it never silently rewrites memory or the repo, so Gil still decides what's actually true.

## Tests to write first

No "How we'll try to break it" section exists on #652 itself, so this list is derived from the standing misuse checklist:

1. **The planted case from AC1**: memory note says "free and non-commercial forever"; new text says "$5 one-time App Store app" about the same project → `find_stale_claims` returns a STALE flag (mocked `chat_fn`, as `continuity_checker`'s own tests do — never a real Ollama call in tests).
2. **Consistent claims don't flag**: two notes about the same topic that don't contradict (mocked `chat_fn` returns CONSISTENT) → no flag.
3. **No lexical overlap → never reaches the judge**: assert the mock `chat_fn` is not called at all when candidates share zero significant tokens with the new text (bounds cost; this is the regression test against the earlier timeouts).
4. **Empty new text / empty memory dir / empty repo (no `.git`, no `CONTEXT.md`)** → returns `[]`, no crash.
5. **Huge/malformed file**: a candidate file far larger than the truncation limit → text is truncated before it reaches the prompt (bounds prompt size/time), and a file that isn't valid UTF-8 is read with `errors="ignore"` rather than raising.
6. **Ollama down / `chat_fn` raises** → `check_file` catches it, fails closed (no flag, no crash), same as every other hook in this codebase (`except Exception: ...` with `log_hook_error`, not a bare swallow).
7. **Repeats**: calling `check_file` twice on the same new file against the same old note appends the flag only once (idempotency — `existing_pending_keys` dedupe).
8. **Concurrency**: two near-simultaneous `append_flags` calls each use the existing tmp-file-then-replace write (matches `output_contracts.run_promotion`'s own pattern) rather than a bare write — test that a write never truncates an in-progress read.
9. **Wrong permissions**: memory dir or repo dir unreadable (`OSError`) → treated as "no candidates," not a crash.
10. **Stale/missing project catalog** (sweep only): `project_catalog.read_catalog()` returns `None` or a catalog with no matching project → sweep degrades to memory-vs-memory only, doesn't crash, and says so in the report.
11. **A person's mistake**: `stale-decisions.md` hand-edited into a shape `suggestions_state()` can't parse → reading it for the pending count returns 0 rather than raising (matches `output_contracts.py`'s existing tolerance).
12. **Hook filter correctness**: a `Write` to an unrelated file (e.g. `foo.py`) never triggers the check; a `Write` to `CONTEXT.md`, `docs/adr/0099-x.md`, or a memory note does; `MEMORY.md` itself is excluded (it's an index, not a claim).
13. **Sweep bound**: with N memory notes, assert the number of `chat_fn` invocations is bounded by the prefilter, not O(N²) unconditionally (direct regression test for the timeout failure mode).

## Decisions

<!-- marvin:decisions -->
### model: Which model judges contradictions?
- [ ] A: Local Ollama `qwen2.5:14b` (zero-cost, same model `continuity_checker`/`logic_auditor` already use; unvalidated on real claims, like those)
- [ ] B: Escalate to Claude (Haiku or Sonnet) given this bug directly caused a wrong answer to Gil

### hook-scope: Which writes trigger the live check?
- [ ] A: Exactly what the ticket names — memory notes, `CONTEXT.md`, `docs/adr/*.md` (optional)
- [ ] B: Also `README.md`, since product-facing facts (like Seal Speak's price) sometimes live there instead of CONTEXT.md

### sweep-output: Where does the one-off sweep's report go?
- [ ] A: `~/.claude/outbox/stale-decisions-sweep-<date>.md` — a historical report, separate from the live flag queue (matches AC3's "report only" wording most literally)
- [ ] B: Appended into the same `~/.claude/stale-decisions.md` queue as live-detected flags, so everything surfaces through the one `check_stale_decisions()` session-start check

## Task List

1. `lib/stale_decision_check.py`: candidate gathering — `repo_root()`, `repo_doc_candidates()`, `memory_candidates()` (wraps `project_catalog.discover_memory`), `gather_candidates()`.
2. Same file: lexical pre-filter using `project_catalog.tokens()`.
3. Same file: `classify_claim_pair()` + its Ollama prompt/parse helpers, `chat_fn`-injectable per `continuity_checker`'s pattern.
4. Same file: `find_stale_claims()` pipeline (gather → prefilter → classify → STALE-only flags), with the truncation and bounded-candidate-count guards from tests 5 and 13.
5. Same file: `format_entry()`, `existing_pending_keys()`, `append_flags()` (tmp-file-then-replace write), `check_file()` (read-and-check entry point for the hook).
6. `lib/tests/test_stale_decision_check.py`: tests 1–9, 11–13 above.
7. New PostToolUse hook script (e.g. `lib/stale_decision_check_hook.py`), modeled on `emit-resume-prompt.py` + `background_review.py`'s detached-subprocess/cooldown: filters the written path per the `hook-scope` decision, spawns `stale_decision_check.py check <path>` detached and non-blocking.
8. Test 12 (hook path filtering) against the hook script directly.
9. `lib/output_contracts.py`: add `STALE_DECISIONS` path constant and a `Contract("stale-decision-check", "~/.claude/stale-decisions.md", "handoff/self-improve session-start review or Gil", 1, lambda: suggestions_state(_read(STALE_DECISIONS)))` entry.
10. `lib/session_start_report.py`: add `check_stale_decisions()` (same inline-regex shape as `check_suggestions()`), wire it into `main()`'s `notes` tuple.
11. `docs/session-start-checklist.md`: add the new row to the table (required by its own "editing this checklist" rule).
12. `skills/handoff/SKILL.md`: one Rules-section line pointing at the new check, mirroring the existing `owner_decisions.py` rule.
13. One-off sweep: `sweep()` in `stale_decision_check.py` (memory-vs-memory, bounded pairwise prefilter, plus memory-vs-linked-project-repo-docs via `project_catalog`'s existing memory↔project linking) + `render_sweep_report()`; test 10.
14. Wire the new PostToolUse hook entry into `~/.claude/settings.json`'s `Write|Edit` block (outside this repo's git history, same as every existing hook script — `emit-resume-prompt.py`, `background_review.py`, etc. — were wired).
15. Run the full `lib/tests/` suite to confirm no regression, and run the sweep once for real to seed the queue/report with whatever it finds today (report only, per Decision `sweep-output`).