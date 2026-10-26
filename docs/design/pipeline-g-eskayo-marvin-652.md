## North-star fit

**Reuses, before adding anything new:**
- `lib/host_os.py:memory_dir()` — the one correct, machine-portable way to locate the real memory folder (already used by `marvin_launcher.py`, `marvin_hooks.py`, `rebuild-manifest.py`). The new check must call this, never hardcode a path.
- `marvin_launcher.py`'s `"judge"` launch kind (`KINDS["judge"]`, used today by `skills/safety-monitor/scripts/verify.py:verify()`) — a zero-tool, Haiku, rubric-in/score-out call with no shared context with what it's judging ("a checker must not share the context of what it checks"). This is the exact shape needed for "does claim A contradict claim B" — a bounded, cheap LLM call, not a new call pattern.
- `dashboard/electron/main/docs.js:discoverDocFirstRepos()` — the existing rule for "which repos have docs worth checking" (auto-discovered by `CONTEXT.md` existing, not hand-maintained), plus its cache at `~/.claude/logs/doc-repos-cache.json`. The Python side reads that cache first instead of re-running `gh repo list` from scratch every time two different languages already needed it.
- `lib/owner_decisions.py`'s shape for a new `lib/*.py`: injected `run=subprocess.run` for testability against real `gh` JSON, idempotent dedupe before filing/flagging, a `scan`/`sync`-style CLI.
- `skills/self-improve/scripts/background_review.py` — the exact hook pattern to copy: PostToolUse on a narrow path match → detached subprocess (so the interactive session never blocks on an LLM call) → per-file cooldown lock → a post-hoc, append-only durable file.
- `skills/safety-monitor/scripts/verify.py:quarantine()` / `~/.claude/quarantine.md`'s format — reused as the shape for the new flags file (dated block, quoted claim, checkbox resolution), not reinvented.
- `lib/marvin_hooks.py`'s `HOOKS` table — the single source of truth for `settings.json`'s hook wiring; a new hook is a new table row + `install()`, never a hand-edit of `settings.json`.
- `docs/agents/decisions-format.md` — used below for the real open questions.

**What's new:** one small lib module (candidate retrieval + judge-call glue) and one hook script — no new daemon, no new storage engine, no embeddings pipeline. That's deliberate: I checked whether to reuse the existing ChromaDB `general`/`knowledge` collections (`rebuild-embeddings.py`) as the memory index, and found they're not usable — `rebuild-manifest.py:scan_memory()` only indexes memory files carrying a legacy `tags:` frontmatter field. A live check of `~/.claude/manifest.json` (regenerated this morning) shows **2 of ~150 real memory files** indexed; every file using the current native auto-memory frontmatter (`metadata: {type: ...}`, no `tags:`) is silently skipped. Building the new check on that index would make it almost always find nothing. So memory search here is direct keyword-overlap over the raw files under `memory_dir()` (cheap, no Ollama dependency, no risk of silently degrading if Ollama isn't running — matches [[feedback-robust-durable-code]]). The manifest/embedding gap itself is a separate, real defect I'm not fixing in this ticket (noted as a Decision below so it doesn't get lost).

**Simplest sufficient approach:** two-stage retrieval-then-judge, not an LLM scan of everything. Cheap keyword/entity overlap narrows memory files and repo docs to a handful of candidates; only those go to the Haiku judge call. This is the same shape `qa_query.py --lateral` and `verify.py` already use (cheap retrieval, bounded model reasoning), just with plain-text overlap instead of embeddings, because embeddings for repo docs don't exist yet and building that pipeline is out of scope for a "flag a contradiction" ticket.

**Token/cost:** one Haiku judge call per surviving candidate (typically 0–3 per write), not per file in memory or per repo. Repo-side `gh` calls are also narrowed first by keyword-matching the claim against each repo's name/description before fetching its `CONTEXT.md`/ADR content, so a decision about one product doesn't fetch every repo's docs.

**Phone-OS fit:** none directly — this is a correctness/reliability fix for memory, which the phone-OS vision depends on being trustworthy, but it doesn't itself move toward reachable-from-anywhere.

**More capable or more passive:** more capable — it stops MARVIN handing Gil a stale fact silently; it doesn't do anything a human would otherwise have had to do by hand (nobody was manually cross-checking memory against repos before).

## Tests first

No "How we'll try to break it" section exists on this ticket. Per the standing instruction, the full adversarial list below stands in for it.

1. **The literal planted case** (acceptance criterion's own test): memory file says `"free and non-commercial forever"`; a new write says `"$5 app"` for the same subject → `check_decision()` returns a flag naming the stale memory file.
2. **Reverse direction**: the stale claim lives in a repo's `CONTEXT.md`/ADR and the new claim is a memory write (not just memory-is-stale; repo-is-stale too).
3. **No contradiction, just overlap**: two claims share keywords but don't conflict (e.g., same product, different unrelated fact) → no flag. Guards against "same entity mentioned" being mistaken for "contradicts."
4. **Empty/whitespace-only new text** (an `Edit` whose `new_string` is blank, or a `Write` that clears a file) → no candidate search attempted, no crash.
5. **Huge new text** (a full `CONTEXT.md` rewrite, thousands of lines) → candidate extraction stays bounded (caps processed length), doesn't hang or blow the judge-prompt budget.
6. **Malformed/binary-ish content** (null bytes, non-UTF8 bytes slipped into a `.md` write) → read fails safely, check no-ops, doesn't crash the hook.
7. **Each dependency failing**: `gh` unavailable/non-zero exit when fetching repo docs → repo-side search degrades to "no repo candidates," memory-side search still runs; the judge call (`marvin_launcher.launch`) timing out or returning unparseable output → fails open (no flag), matching `verify()`'s existing fail-open contract, logged not swallowed.
8. **Repeats**: the same file edited twice in quick succession → cooldown lock collapses it to one check, not two detached subprocesses racing to append duplicate flags.
9. **Concurrency**: two machines/sessions trigger the hook for different files at the same moment → both can append to `~/.claude/stale-decisions.md` without one clobbering the other (append-then-read-back-and-verify, same pattern as `background_review.py`'s reconcile step, not a blind overwrite).
10. **Idempotence**: the exact same contradiction found twice (e.g., re-run of the one-off sweep, or a second edit reconfirming the same new fact) → not appended twice (reuse `quarantine()`'s "skip if identical entry already queued" dedupe).
11. **Wrong file shape matched**: a file literally named `CONTEXT.md` that isn't a repo-root docs file (e.g., inside `node_modules`, or a random nested doc) → excluded by checking it sits at an actual repo root (sibling `.git` or `docs/adr`), not matched by filename alone.
12. **Wrong machine / stale cache**: `~/.claude/logs/doc-repos-cache.json` missing or from a different machine's run → falls back to a live `gh repo list` discovery rather than silently searching zero repos.
13. **Stale state**: the repo doc that supposedly contains the old claim was itself already corrected on GitHub since the local checkout/cache was made → the repo-side fetch reads live content via `gh api`, not a local possibly-stale clone, so this can't produce a false flag against already-fixed content.
14. **A person's mistake**: Gil edits memory with a typo/placeholder ("TBD", "???") as the "new claim" → no crash, and the judge is not asked to adjudicate nonsense against real content as if it were a confident fact (candidate extraction requires a minimum signal — e.g., at least one concrete noun/number — before even attempting retrieval).
15. **Permissions**: memory directory or a repo's local checkout is unreadable (permission denied) → check logs via `hook_errors.log_hook_error()` and no-ops, doesn't crash the triggering `Write`/`Edit`.
16. **The hook never blocks the tool call it fires on** — same contract as `background_review.py`: detached subprocess, main hook process exits immediately regardless of what the check finds.
17. **Handoff/self-improve surfacing**: `~/.claude/stale-decisions.md` has pending entries → the handoff doc includes them under "Open questions / next steps"; with zero pending entries → no empty/awkward section is emitted.
18. **Sweep is genuinely report-only**: running the one-off sweep over current memory files does not modify any memory file, `CONTEXT.md`, or ADR — it only writes the dated report to `~/.claude/outbox/`.

## Decisions

<!-- marvin:decisions -->
### flags-file: Where do flagged contradictions live and how are they resolved?
- [ ] A: A new dedicated file, `~/.claude/stale-decisions.md`, in `quarantine.md`'s exact format (dated block, quoted old+new claim, checkbox approve/dismiss)
- [ ] B: Reuse `~/.claude/suggestions.md` as-is (same entry format `architecture-review` already uses), no new file

### repo-search-scope: How thoroughly should the repo side search on every write?
- [ ] A: Keyword-filter repos by name/description first (cheap), only fetch `CONTEXT.md`/ADRs for repos that plausibly match — may miss a contradiction if the new claim doesn't name the product/repo
- [ ] B: Always fetch and scan every auto-discovered doc-first repo's `CONTEXT.md` + ADRs on every trigger — more thorough, more `gh` API calls per write

### judge-model: Which model judges "does this contradict that"?
- [ ] A: Haiku via the existing `"judge"` launch kind (cheap, same as `verify.py`'s existing safety judge)
- [ ] B: Sonnet (costlier per call, lower miss risk — this ticket exists because a miss already caused real, visible harm to Gil)

### hook-scope: Which sessions run the check?
- [ ] A: Interactive sessions only (matches `rebuild-manifest.py`/`background_review.py`'s existing precedent for session-upkeep hooks)
- [ ] B: All sessions including headless ticket-executor runs (decisions can also get written during autonomous work, not just live grilling)

### manifest-gap: Found while scoping — a related defect, not mine to fix here
- [ ] A: File it as a separate ticket/suggestion now (memory indexing is ~99% broken for the current native auto-memory frontmatter schema)
- [ ] B: Leave it for whoever next touches `rebuild-manifest.py`/`rebuild-embeddings.py`, no ticket filed

## Task List

1. **`lib/stale_decision_check.py`** — core module: `extract_terms()`, `find_memory_candidates()` (reads `host_os.memory_dir()` directly, bounded length, skips the file that just changed), `discover_doc_repos()` (reads `~/.claude/logs/doc-repos-cache.json`, falls back to live `gh repo list` + CONTEXT.md existence check), `fetch_repo_docs()` (raw content via `gh api .../contents/{path}` with `Accept: application/vnd.github.raw`), `find_repo_candidates()` (name/description keyword pre-filter per Decision `repo-search-scope`), `judge_contradiction()` (wraps `marvin_launcher.launch("judge", ...)`, injectable `judge=` callable for tests, fails open on any error/timeout/unparseable output), `check_decision()` (orchestrates both sides), `flag()` (idempotent append to the file chosen in Decision `flags-file`), `sweep()` (report-only, writes to `~/.claude/outbox/stale-decisions-sweep-<date>.md`), CLI entry (`check` / `sweep`).
2. **Tests for `lib/stale_decision_check.py`** covering cases 1–15, 18 above — `run=`/`judge=` injected fakes returning realistic `gh`/judge output shapes, no real network/model calls.
3. **`rubrics/stale_decision.md`** (new, alongside `skills/safety-monitor/scripts/rubrics/*.md`'s existing pattern) — the judge prompt: given OLD claim + NEW claim, answer contradiction yes/no + one-line reason, nothing else.
4. **`lib/stale_decision_hook.py`** — PostToolUse hook: path-matches memory files (mirrors `rebuild-manifest.py:_hook_should_skip`'s exact matching logic), `CONTEXT.md` at a verified repo root, and `docs/adr/*.md`; extracts the new/changed text from the tool payload (`content` for `Write`, `new_string` for `Edit`/each item for `MultiEdit`) instead of re-reading the whole file; per-file cooldown lock; detached subprocess that calls `check_decision()` + `flag()` (mirrors `background_review.py`'s structure exactly).
5. **Tests for the hook**, covering cases 4–9, 11, 16 above (payload shapes for Write/Edit/MultiEdit, cooldown collapsing repeats, never blocking the originating tool call).
6. **Wire the hook**: add a row to `lib/marvin_hooks.py`'s `HOOKS` table (kind per Decision `hook-scope`), run `marvin_hooks.py install` to regenerate `~/.claude/settings.json`, update `docs/session-start-checklist.md` only if Decision `flags-file`/future scope ever adds a SessionStart surface (not required by the acceptance criteria as written).
7. **Edit `skills/handoff/SKILL.md`** — add a rule (next to the existing `owner_decisions.py waiting` rule) to check the flags file before writing "Open questions / next steps" and list unresolved entries there.
8. **Edit `skills/self-improve/SKILL.md`** — add a short step surfacing the flags file's pending count in its reporting, same lightweight treatment `suggestions.md`'s pending count gets elsewhere.
9. **One-off sweep run**: execute `stale_decision_check.py sweep` once over current memory, commit its outbox report for review (report only, per acceptance criterion 3 and test 18).
10. **CONTEXT.md entry** documenting the new "stale-decision check" (trigger, search scope, flags-file location) in the same style as the Quarantine/Owner-decisions sections it's modeled on, plus a line in `docs/session-start-checklist.md`'s surrounding docs noting where this lives if Decision `hook-scope`/`flags-file` change scope later.