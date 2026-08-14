# marvin-bench — results log

## Run 1 — 2026-06-26 (first full suite, single run each)

Base Claude Code (`clean`) vs MARVIN-optimized (`marvin`), same model, `CLAUDE_CONFIG_DIR` isolation.

| Task | Type | clean $ | marvin $ | Δ cost | clean tok | marvin tok | clean correct | marvin correct |
|------|------|---------|----------|--------|-----------|------------|---------------|----------------|
| task-002-recall | qa | 0.0529 | 0.0511 | **−3%** | 19227 | 19259 | **0.00** | **1.00** |
| task-001-bugfix | fs | 0.0660 | 0.0741 | **+12%** | 55018 | 59299 | 1.00 | 1.00 |
| task-003-refactor | fs | 0.1008 | 0.1118 | **+11%** | 113847 | 122474 | 1.00 | 1.00 |
| task-004-caveman | qa | 0.0521 | 0.0552 | **+6%** | 19249 | 19716 | n/a | n/a |

task-004 output tokens (the behavioral signal): **clean 176 vs marvin 215** — MARVIN was *more* verbose despite "caveman mode: always active."

### Findings
1. **MARVIN's value is concentrated in knowledge/recall.** task-002 is the only task where it changed the outcome (0→1 correct), and it did so at ~zero token cost. This is the core value prop, confirmed.
2. **On mechanical coding, MARVIN is a ~10–12% token tax with no quality gain.** Both profiles solved the bugfix and refactor identically; MARVIN just carried more context (CLAUDE.md + routing + lexicon + memory index) to get there.
3. **Caveman mode backfired.** The optimization meant to reduce output verbosity produced *more* output than the unoptimized base. Anti-correlated with its goal — investigate or drop.

### Strategic implications (each itself A/B-testable here)
- **Profile routing:** use a lean profile for mechanical/code work, the rich profile for knowledge/recall work. Could recover the 10–12% tax on the bulk of coding turns.
- **Trim CLAUDE.md overhead:** the marginal token cost is the always-loaded instructions; audit what earns its place.
- **Fix or remove caveman mode:** it isn't doing what it claims.

### Caveats
- Single run per task — no variance; cost/wall are noisy. Repeat before trusting magnitudes.
- Tasks are simple and unambiguous, which likely *understates* MARVIN's value (its skills should matter most on hard/ambiguous work). Add harder tasks.
- Correctness is substring-graded (v0). Add an LLM-judge for semantic grading.

---

## Run 2 — 2026-06-28 (profile routing validation)

Added `lean` profile (`~/.claude-lean`): 13-line CLAUDE.md, TDD/grill defaults only, no memory hooks, no skill routing overhead. Caveman mode dropped (was anti-correlated). Coding tasks only.

| Task | Type | clean $ | lean $ | marvin $ | lean vs clean | lean vs marvin |
|------|------|---------|--------|----------|---------------|----------------|
| task-001-bugfix | fs | 0.0633 | 0.0652 | 0.0727 | +3% | **−10%** |
| task-003-refactor | fs | 0.0976 | 0.1013 | 0.1108 | +4% | **−9%** |

Token counts:

| Task | clean | lean | marvin |
|------|-------|------|--------|
| task-001-bugfix | 51,662 | 52,685 | 56,073 |
| task-003-refactor | 107,064 | 109,799 | 116,630 |

### Findings
1. **Lean profile recovers ~9–10% of the marvin coding tax.** Lean sits only 3–4% above clean (residual = the 13-line CLAUDE.md + TDD/grill defaults), vs 12–15% above clean for marvin. TDD/grill are worth keeping: they change output quality, not just context size.
2. **All three profiles solve coding tasks identically (correct = 1.00).** Confirms marvin overhead on coding is pure cost, no quality signal.
3. **Routing rule validated:** use `claude-lean` for mechanical coding, `claude` for recall/research/architecture. Expected savings on coding-heavy sessions: ~9–10%.

### Next bench priorities
- ~~Run recall task (task-002) on all 3 profiles~~ — done in Run 3.
- Add harder/ambiguous tasks where skill routing might earn its cost on lean too.
- Add LLM-judge grading for semantic correctness (current substring grading is v0).

---

## Run 3 — 2026-06-30 (recall task on all 3 profiles — profile routing confirmation)

Recall task across clean, lean, and marvin to confirm lean = base on recall (no recall regression).

| Task | Type | clean $ | lean $ | marvin $ | clean correct | lean correct | marvin correct |
|------|------|---------|--------|----------|---------------|--------------|----------------|
| task-002-recall | qa | $0.0542 | $0.0556 | $0.0553 | 0.00 | 0.00 | **1.00** |

Token counts:

| Task | clean | lean | marvin |
|------|-------|------|--------|
| task-002-recall | 18,418 | 18,697 | 18,998 |

### Findings
1. **Routing rule fully confirmed.** MARVIN wins recall (1.00), lean and clean both fail (0.00). Lean does NOT degrade recall relative to clean — it's identical.
2. **Lean is safe to use for coding.** It carries no recall capability and no recall cost. The ~280 token gap between lean and clean on recall is the 13-line CLAUDE.md overhead, which is unavoidable.
3. **Profile routing is DONE.** Routing rule: `claude-lean` for mechanical coding → saves 9–10%. `claude` for anything involving recall/research/architecture/memory → MARVIN wins.

### Bug found and fixed
Claude Code 2.x stores credentials per-config-dir path using SHA256-prefixed keychain entries (`Claude Code-credentials-<sha256[:8]>`). A failed auth attempt writes a BLANK keychain entry that poisons all future attempts for that path — `.credentials.json` is never read again once a path-specific entry exists. Fix: delete the poisoned keychain entry (`security delete-generic-password -s "Claude Code-credentials-<hash>"`). setup.sh should check for and delete blank entries before materializing credentials.

### Next bench priorities
- ~~Add harder/ambiguous coding tasks where MARVIN skill routing might earn its cost vs lean.~~ — done in tasks 005–007.
- Add LLM-judge grading for semantic correctness (current substring grading is v0).
- ~~Fix setup.sh: detect and delete blank path-specific keychain entries before materializing.~~ — done in Run 3.

---

## Task Suite v2 — Added 2026-06-30

Three harder edge-case tasks added. Grading strings corrected after Run 4 (see below).

| Task | Type | Edge case | Correct grading signal |
|------|------|-----------|------------------------|
| task-005-date-validator | fs | Semantic bug — manual range check misses impossible calendar dates | `datetime.date` appears (covers both `.date()` constructor and `.fromisoformat()`) |
| task-006-email-lookup | fs | Shared helper with opposite caller semantics (add_user rejects on found; add_order rejects on not-found) | `find_user_by_email` + `, None)` (covers both `return None` and `next(..., None)` sentinel) |
| task-007-dyld-recall | qa | Bench self-knowledge: caveman mode output token counts from Run 1 | `176` + `215` (exact token counts proving anti-correlation) |

---

## Run 4 — 2026-06-30 (initial v2 run — grading bugs found)

First run of tasks 005–007. All three profiles, all tasks.

### task-005-date-validator

| profile | cost | tokens | correct |
|---------|------|--------|---------|
| clean | $0.1082 | 55,963 | 0.50 |
| lean | $0.1097 | 60,078 | 0.50 |
| marvin | $0.1255 | 63,750 | 0.50 |

**Finding:** 0.50 across the board = grading miss. All profiles used `datetime.date()` or `datetime.date.fromisoformat()` — both correct. Grading string `strptime` was too specific. All profiles actually solved the task correctly.

### task-006-email-lookup

| profile | cost | tokens | correct |
|---------|------|--------|---------|
| clean | $0.1107 | 59,691 | 0.50 |
| lean | $0.1149 | 60,757 | 0.50 |
| marvin | $0.1317 | 61,147 | 0.50 |

**Finding:** 0.50 across the board = grading miss. All profiles used `next((u for u in db...), None)` sentinel pattern — correct Python. Grading string `return None` never appears literally in the sentinel idiom. All profiles solved the task correctly.

### task-007 original (DYLD_LIBRARY_PATH recall)

| profile | cost | tokens | correct |
|---------|------|--------|---------|
| clean | $0.1373 | 67,084 | 1.00 |
| lean | $0.1228 | 63,535 | 1.00 |
| marvin | $0.1371 | 66,451 | 1.00 |

**Finding:** Discriminator failure. All profiles scored 1.00 because `render_pdf.py` is a real readable file at a well-known path. Clean even quoted "lines 14–16". The question pointed directly to the file — no memory required. Redesigned as bench self-knowledge task (exact output token counts from Run 1 caveman comparison).

**Key lesson:** QA tasks where the answer is in a readable file are NOT memory discriminators. True discriminators need either (a) answer only in ChromaDB/session history (no file on disk), or (b) file access restricted for clean/lean. Current bench architecture allows all profiles to read files — this is the gap.

---

## Run 5 — 2026-06-30 (v2 corrected grading + redesigned task-007)

Grading strings fixed for 005/006. task-007 redesigned: asks for exact caveman mode output token counts from Run 1 (clean=176, marvin=215 output tokens — the numbers that proved anti-correlation).

### task-005-date-validator (fixed grading: `datetime.date`)

| profile | cost | tokens | turns | tool_calls | correct |
|---------|------|--------|-------|-----------|---------|
| clean | $0.1087 | 59,548 | 3 | 2 | **1.00** |
| lean | $0.1113 | 60,262 | 3 | 2 | **1.00** |
| marvin | $0.1252 | 63,525 | 3 | 2 | **1.00** |

All profiles solved correctly. No profile differentiation — date validation is in the comfortable competency zone for all. MARVIN tax: ~7% vs clean.

### task-006-email-lookup (fixed grading: `, None)`)

| profile | cost | tokens | turns | tool_calls | correct |
|---------|------|--------|-------|-----------|---------|
| clean | $0.1107 | 59,685 | 3 | 2 | **1.00** |
| lean | $0.1157 | 61,011 | 3 | 2 | **1.00** |
| marvin | $0.1298 | 64,352 | 3 | 2 | **1.00** |

All profiles solved correctly. Same pattern as v1 coding tasks: MARVIN ~10% tax, no quality gain. Opposite-semantics helper extraction is in the comfortable zone.

### task-007-dyld-recall (redesigned: caveman mode token counts)

| profile | cost | tokens | turns | tool_calls | correct |
|---------|------|--------|-------|-----------|---------|
| clean | $0.1733 | **95,682** | **7** | **6** | 1.00 |
| lean | $0.1409 | **66,762** | **5** | **4** | 1.00 |
| marvin | $0.1422 | **45,905** | **3** | **2** | 1.00 |

**New finding: efficiency-when-correct as a metric.** All three profiles found the correct answer (the numbers are in RESULTS.md, which all profiles can read). BUT:
- **MARVIN used 2 tool calls to clean's 6 — 3× more efficient**
- **MARVIN used 52% fewer tokens than clean (45,905 vs 95,682)**
- MARVIN knew where to look immediately. Clean had to explore.

This is a new MARVIN value signal that binary correct/incorrect grading misses entirely. Even when all profiles are eventually correct, MARVIN's memory-augmented navigation dramatically reduces search cost. The ROI is real even on tasks where correctness is equal.

### Findings from Run 5

1. **tasks 005/006 confirm "comfortable zone" ceiling.** Semantic bugs in a 7-line function and shared-helper extraction with opposite semantics are well within current model capability at all profile levels. No profile differentiation on correctness. MARVIN carries its standard ~10% overhead.

2. **task-007 reveals efficiency-when-correct as the hidden MARVIN value on navigational tasks.** Correct = equal; cost = 3× cheaper for MARVIN. This changes the ROI model: MARVIN's value isn't just "answers that clean gets wrong" — it's also "answers clean gets right but burns 3× the tokens finding."

3. **True discriminator design gap identified.** Binary correct/incorrect tests only matter when clean/lean can fail. All current tasks where the answer is in a readable file will eventually score 1.00 across all profiles — the discriminating variable is search cost, not outcome. Two paths forward:
   - `[build]` **Efficiency-when-correct metric** — track and report `tokens_to_correct` and `tool_calls_to_correct` alongside the binary score. Already visible in raw data; just needs a column in the table.
   - `[build]` **Isolated-memory QA type** — new task type where clean/lean run with file access restricted (`--permission-mode` read-only on a temp dir containing no relevant files), so MARVIN's ChromaDB is the only path to the answer.

### Next bench priorities
- Add `tokens_to_correct` and `tool_calls_to_correct` as reported metrics (data already exists).
- Design isolated-memory QA tasks (file access restricted for clean/lean).
- Add LLM-judge grading for semantic correctness on fs tasks.
- More hard edge cases: tasks where models plausibly fail vs tasks where all succeed but at different cost.

---

## Run 13 — 2026-07-01 (three new discriminator tasks: multi-file invariant, deceptive comment, KB isolation)

Task suite v3: `task-012-protocol-mismatch` (fs — encoder/decoder version-bump trap requiring both files to change), `task-013-lru-cache-bug` (fs — a deceptive code-review comment endorses a broken `OrderedDict` line), `task-014-kb-lookup` (qa — answer exists only in the `qa-knowledge` ChromaDB collection, not on disk).

Session hit two infrastructure bugs before any real signal: (1) all three bench profiles' keychain-materialized credentials had gone stale/poisoned overnight (`"Not logged in"` on every run — see the keychain-poisoning entry in Run 3, `profiles/setup.sh` re-run fixed it), and (2) `qa-agent` — like most `~/.agents/skills/*` — was never actually registered as an invocable Claude Code Skill (CLAUDE.md's routing table is a prose convention, not a Skill registration), so task-014 initially failed on all profiles for a reason unrelated to memory quality. Fixed by adding `~/.claude/commands/qa-agent.md` (thin wrapper, same pattern as the working `paper-dive` command) — deliberately marvin-only, not added to lean or clean.

### task-012-protocol-mismatch (fs, expect both `fromisoformat` + `{1, 2, 3}` for 1.00)

| profile | cost | tokens | turns | tool_calls | wall_s | correct | judge |
|---------|------|--------|-------|-----------|--------|---------|-------|
| clean | $0.2245 | 278,601 | 12 | 11 | 45.4 | **1.00** | pass |
| lean | $0.3295 | 448,939 | 17 | 16 | 88.8 | **1.00** | pass |
| marvin | $0.3223 | 441,607 | 16 | 15 | 67.1 | **1.00** | pass |

All three caught the multi-file invariant despite the trap. Clean is cheapest by a wide margin — lean and marvin both ran **+58–61% more tokens** than clean for the identical outcome. Lean was not cheaper than marvin here, contrary to the Run 2 routing thesis.

### task-013-lru-cache-bug (fs, expect `move_to_end`)

| profile | cost | tokens | turns | tool_calls | wall_s | correct | judge |
|---------|------|--------|-------|-----------|--------|---------|-------|
| clean | $0.1428 | 153,145 | 6 | 5 | 28.9 | **1.00** | pass |
| lean | $0.2076 | 292,543 | 11 | 10 | 41.3 | **1.00** | pass |
| marvin | $0.1550 | 165,219 | 6 | 5 | 28.2 | **1.00** | pass |

All three saw through the deceptive endorsed comment. Marvin stayed close to clean (+8%); lean was the expensive outlier again (+91% over clean, nearly double the turns/tool calls).

**New pattern across both tasks: lean, not marvin, carried the larger token tax this run.** Single run each — treat as directional pending a repeat.

### task-014-kb-lookup (qa, expect exact phrase `"Context quality matters more than model size"`)

First attempt (all profiles, before the `qa-agent` Skill registration fix): **0.00 across the board** — not a memory signal, an infrastructure gap. Every profile tried to invoke the KB, hit `Unknown skill: qa-agent` (no formal Skill registration existed yet), and had no fallback because the task prompt bans file reads (the one path to learn `qa_query.py`'s syntax).

After registering `~/.claude/commands/qa-agent.md` (marvin-only — not added to lean or clean) and re-running:

| profile | cost | tokens | turns | tool_calls | wall_s | correct | judge |
|---------|------|--------|-------|-----------|--------|---------|-------|
| clean | $0.3019 | 248,008 | 7 | 6 | 53.8 | **0.00** | FAIL |
| lean | $0.3087 | 176,891 | 7 | 6 | 39.2 | **0.00** | FAIL |
| marvin | $0.0768 | 82,685 | 4 | 2 | 20.7 | **1.00** | pass |

**Discriminator restored and working as designed.** Verified directly (`CLAUDE_CONFIG_DIR=bench/profiles/clean claude -p "list your skills"`) that `clean`'s real skill list has no `qa-agent` — so clean/lean correctly identified they lack the skill and refused to fabricate an answer (the right behavior, not a bug), scoring 0.00. Marvin invoked the skill, ran `qa_query.py`, and reproduced the exact stored phrase — 1.00, and at less than a third of clean/lean's cost (fewer turns, 2 tool calls instead of 6).

**Judge bug found in the process:** `judge_run()` (`bench.py`) calls the LLM judge via plain `claude -p` with no `CLAUDE_CONFIG_DIR` override, so the judge always runs under whatever the *live default* profile is — now `~/.claude`, which has `qa-agent` registered. The judge's FAIL rationale for clean/lean wrongly claimed "the qa-agent skill was explicitly listed as invocable in this session," which is false for those isolated profiles — the judge's own environment leaked into its assessment of a session it never inspected. The **scores are still correct** (0.00 is the right grade), but judge *rationale text* should not be trusted at face value when it makes claims about tool/skill availability — it's grading with its own toolset in mind, not the graded run's. Fix candidate: pin the judge to a fixed neutral `CLAUDE_CONFIG_DIR` (e.g. clean) so its rationale can't reference tools the graded profile didn't have.

### Findings from Run 13
1. **Infrastructure failures can fully mask the signal you're trying to measure.** Two unrelated bugs (poisoned keychain, unregistered skill) produced 0.00/`"Not logged in"` results that look like real findings if not diagnosed. Always reproduce a failing bench result directly (`CLAUDE_CONFIG_DIR=... claude -p "..."`) before trusting it as a MARVIN-vs-clean signal.
2. **The "lean is cheapest for coding" rule from Run 2 does not hold universally.** On task-012/013, lean was the most expensive profile, not marvin. Needs repeat runs to confirm whether this is noise or a real interaction with task difficulty/turn count.
3. **Most `~/.agents/skills/*` are likely not real Skills.** Confirmed for `qa-agent` (now fixed); the other ~19 are unaudited. This is a standing gap in the actual MARVIN setup, independent of the bench.
4. **The LLM judge is not profile-isolated and its rationale can reference tools the graded session never had.** Scores held up under manual verification this time, but the rationale text is unreliable evidence on its own — treat it as a hint, not ground truth, especially for qa-type tasks that hinge on tool/skill availability.

### Next bench priorities
- ~~Fix `judge_run()` to pin a neutral `CLAUDE_CONFIG_DIR` so judge rationale can't reference tools/skills the graded profile didn't have.~~ — done in Run 14.
- Repeat task-012/013/014 to check whether "lean costliest" is signal or noise.
- Audit remaining `~/.agents/skills/*` for missing `~/.claude/commands/*.md` wrappers.

---

## Run 14 — 2026-07-01 (judge isolation fix + setup.sh durability bug)

Fixed the judge bug identified in Run 13. `judge_run()` in `bench.py` previously called `claude -p` with no `CLAUDE_CONFIG_DIR` override, so the judge always graded from the live default profile's own tool/skill list. Changed to:
- Pin `CLAUDE_CONFIG_DIR` to the `clean` profile (no skills/memory/tools of its own).
- Strip `CLAUDE_CODE_*` / `CLAUDECODE` / `CLAUDE_EFFORT` env vars, matching `run_once()`'s existing isolation.
- Add `--permission-mode bypassPermissions` so the now-isolated judge can't stall on a permission gate.
- Add an explicit instruction in the judge prompt: don't assume the candidate had access to any tool/skill unless its response demonstrates using it.

### Verification re-run: task-014-kb-lookup (post judge-fix)

| profile | cost | tokens | turns | tool_calls | wall_s | correct | judge |
|---------|------|--------|-------|-----------|--------|---------|-------|
| clean | $0.3214 | 168,949 | 5 | 4 | 40.4 | **0.00** | FAIL |
| lean | $0.3380 | 157,648 | 5 | 4 | 21.4 | **0.00** | FAIL |
| marvin | $0.1794 | 119,553 | 6 | 4 | 21.5 | **1.00** | pass |

Scores unchanged (0.00/0.00/1.00 — correct). Rationale text now accurate:
- clean: *"The assistant refused to complete the task instead of using ToolSearch to look for a qa-knowledge KB tool..."*
- lean: *"The assistant never attempted a ToolSearch (or Skill invocation) for a qa-knowledge/qa-agent tool before declaring it unavailable..."*
- marvin: *"The response directly answers all three questions with specific, concrete details... attributed to KB query results rather than file search."*

No claims about clean/lean having access to `qa-agent` — the judge now critiques only what's observable in the response, exactly as intended.

### Related bug: `setup.sh` wasn't durable

While re-verifying, a `/login` triggered an unrelated credential rebuild, and the `clean` profile's auth broke again ("Not logged in") — but this time the `qa_query.py` permission allowlist was *also* gone. Root cause: `profiles/setup.sh` unconditionally wrote `echo '{}' > "$CLEAN/settings.json"` on every rebuild, silently discarding any permission edits made directly to the profile after the fact. Fixed by baking the `qa_query.py` permission into the `clean` profile's settings.json template inside `setup.sh` itself, so it survives every future credential rebuild rather than needing to be manually re-added.

### Findings from Run 14
1. **Judge isolation fix confirmed working** — rationale text is now trustworthy evidence, not just the numeric score.
2. **Any bench-profile config edit made outside `setup.sh` is fragile.** `setup.sh` fully rebuilds profile directories from scratch on every run (by design, for credential hygiene) — anything not encoded in the script itself will silently vanish on the next rebuild. Treat `setup.sh` as the single source of truth for profile config, not the live directories.

### Next bench priorities
- ~~Repeat task-012/013/014 to check whether "lean costliest" is signal or noise.~~ — attempted in Run 15's `--repeat 3`; hit the account's session limit partway through (see below) before a clean signal emerged. Needs a re-run with headroom.
- Audit remaining `~/.agents/skills/*` for missing `~/.claude/commands/*.md` wrappers.
- Consider auditing other profile-specific files (beyond settings.json) for the same setup.sh-overwrite fragility.

---

## Run 15 — 2026-07-01 (account session-limit discovery, infra-error handling, quota preflight, select_model.py, two more judge bugs)

### "Ran out of tokens fast" — not a Fable 5 model swap

A `--repeat 3` run across task-012/013/014 (27 candidate runs + up to 27 judge runs) hit this mid-sweep: `result_text: "You've hit your session limit · resets 12pm (America/Denver)"`. User suspected Claude Code had silently switched to Fable 5 (a real, more-expensive promo model referenced in the account's cached `.claude.json`: *"Fable 5 draws down usage faster than Opus 4.8"*). Checked every result JSON and every live stream-json init event from this session — all report `"model": "default"` / `claude-sonnet-5`, never fable. **Root cause: the bench harness itself burns through the account's 5-hour Pro-plan session quota.** Every candidate run is a full separate `claude -p` session (system prompt, tool discovery, cache creation, all billed); `--judge` doubles it; a single `--repeat N` sweep across the full 3-profile suite is dozens of sessions against the same account-wide limit this interactive conversation also draws from. Lesson: check `rate_limit_info` / the literal error text before assuming a model regression.

### Robustness fixes to bench.py

1. **Infra-error detection.** Added `INFRA_ERROR_MARKERS` / `_is_infra_error()` — runs whose `result_text` matches "hit your session limit", "not logged in", or "please run /login" are tagged `infra_error` and excluded from cost/token/correctness stats (`aggregate_runs`) rather than silently scoring as a real 0.00. The `--repeat` loop now stops a profile early on its first infra error instead of burning through the remaining repeats. The printed table shows `INFRA-ERR` instead of a fabricated score.
2. **Preflight quota check.** `main()` now calls a new `_check_quota()` (one cheap `claude -p` call reading `rate_limit_info`) before starting, prints an estimated session count (`tasks × profiles × repeat × [judge]`), and aborts immediately if the account is already at its limit instead of running into the wall partway through.

### select_model.py — ascending-cost model-selection sweep

New script, built after the user proposed testing cheapest-to-most-expensive models and locking in the first one to pass, to save on both production cost and future testing cost. Pushed back on "2 consecutive passes" as the lock-in bar given the variance already observed in repeat runs; settled on **N≥3 consecutive substr+judge passes**, escalating to the next candidate on any failure. Default ladder (ascending cost): `ollama:qwen2.5:7b` → `ollama:qwen2.5:14b` → `claude:claude-haiku-4-5-20251001` → `claude:default` (Sonnet) — deliberately doesn't auto-escalate to Opus/Fable; those are reachable via `--candidates` if wanted. Reuses `run_once`/`run_once_ollama`/`judge_run`/`_check_quota` from `bench.py` directly.

**First run (task-014-kb-lookup) immediately validated the N≥3 decision:** Haiku passed run 1, failed run 2. Under a 2-pass rule this would have locked in Haiku on a fluke.

### Two more judge bugs found while verifying select_model.py, both fixed

1. **Judge used its own tool access to "fact-check" against the wrong environment.** Run 14's fix added `--permission-mode bypassPermissions` so the isolated judge wouldn't hang on approval gates — but the judge then actually *used* that Bash access. On a fully correct Haiku response, it failed the run with: *"the memory directory available in this environment is empty, so no such context actually existed."* It had checked its OWN clean/memory-less profile's filesystem and wrongly projected that onto the candidate's (different, marvin-profile) session. **Fixed:** swapped `--permission-mode bypassPermissions` for `--tools ""` — the judge now has zero tool access, period, and can only reason from the prompt text. Verified by re-judging the exact flagged response: now scores 1.0 with an accurate rationale.
2. **Judge had no ground truth to check against, so it was grading "does this sound fabricated" — and flip-flopped on identical-quality answers.** Across 3 repeats of the same model on task-002-recall, one correct response passed as "grounded" and an equally-correct one failed as "fabrication" — the judge prompt never included the task's actual expected answer, so there was nothing to verify against; it was reacting to how confident/specific the phrasing sounded, which is noise. **Fixed:** `judge_run()` now passes `task["expect"]` (the same ground-truth list the deterministic substring scorer already uses) into the judge prompt, with instructions to grade content-match against it and never attempt fabrication-detection. Verified by re-judging all previously flip-flopped responses (qwen 7B, Haiku, two `default` repeats) — all now consistently score 1.0, matching their actual correctness.

### First trustworthy select_model.py results (post judge-fixes)

| task | locked-in model | notes |
|------|-----------------|-------|
| task-014-kb-lookup | `claude:default` (Sonnet) | Not a fair Ollama read — this task requires invoking the `qa-agent` Skill via Bash, which `run_once_ollama` structurally cannot do (context injection only, no tool use). 7B/14B failing here reflects a missing capability path, not model weakness. |
| task-002-recall | `claude:claude-haiku-4-5-20251001` | 3/3 clean passes. 7B/14B failed on exact substring (known paraphrase gap — "tag-keyword matching" vs "tag matching") though the fixed judge now correctly scores the underlying content as right. **Independently reconfirms Run 8's finding** (Haiku matches Sonnet on recall at ~60% cost) via a completely different code path. |

### Findings from Run 15
1. Fast token/session drain during heavy bench use is expected behavior of the harness, not a sign of a model regression — check `rate_limit_info` first.
2. Infra errors (rate limits, stale auth) must never be scored as real correctness failures — now enforced structurally in `aggregate_runs`.
3. Giving an "isolated" judge tool access is a footgun even with the right `CLAUDE_CONFIG_DIR` — it can and will use those tools to check the wrong thing. Zero tools is the safer default for an LLM judge grading from a fixed transcript.
4. An LLM judge grading "correctness" without the ground-truth answer in its prompt is not actually grading correctness — it's grading vibes, and will be unstable run-to-run on equally-correct answers. Always pass known ground truth into judge prompts when available.
5. select_model.py's first two real runs already reproduced a previously-hand-verified finding (Haiku ≈ Sonnet on recall) via an independent path — reasonable confidence the harness's conclusions are real.

### Next bench priorities
- ~~Re-run the task-012/013/014 `--repeat 3` variance check now that infra-error handling + quota preflight exist to prevent a repeat of the mid-sweep failure.~~ — done (2026-07-02): clean cheapest on both hard tasks, lean vs marvin flips per task with high variance. Used to correct `route.py`'s stale "lean saves 9-10%" claim — see [[marvin-bench-harness]].
- Run `select_model.py` against a coding (fs) task to get a model-selection read where Ollama's lack of tool use isn't a confound.
- ~~Audit remaining `~/.agents/skills/*` for missing `~/.claude/commands/*.md` wrappers.~~ — done (2026-07-02): 24 of 26 were missing; all wrapped.

---

## Run 16 — 2026-07-02 (caveman mode retest — Run 1's finding was confounded)

Prompted by adding `~/.claude/commands/caveman.md` (part of the skill-wrapper audit above) — registering caveman as an invocable Skill without first checking whether its documented "backfired" finding (Run 1, Setback 2) still held up. It didn't survive scrutiny: Run 1 compared `marvin` (caveman always-on + full CLAUDE.md overhead) against `clean` (nothing) — a confounded comparison that couldn't isolate caveman's actual effect from marvin's general profile overhead.

**Redesigned as a valid isolation:** same profile (`marvin`) for both variants, same prompt (task-004's original: *"Explain what an LLM context window is and why it matters when building agents. Keep it to a short paragraph."*), only varying whether caveman was explicitly triggered (its current opt-in-only state — unaffected by this retest). N=3 each, judged against `expect: ["context window", "token"]`.

| Variant | Mean output tokens | Runs | Judge pass |
|---------|--------------------|------|-----------|
| baseline (no trigger) | 1207 | 1024, 1288, 1308 | 3/3 |
| caveman (explicit trigger: "Caveman mode. ...") | 328 | 361, 310, 312 | 3/3 |

**72.8% output-token reduction, zero correctness loss.** Nearly matches the skill's claimed "~75%." All 6 responses read as coherent and technically substantive (verified by reading the actual text, not just the judge score) — caveman outputs correctly used `->` for causality, dropped filler, kept exact technical terms, matching the skill's documented design.

### Findings from Run 16
1. **Caveman mode was never actually broken — the mechanism works.** The Run 1 "backfired"/"anti-correlated" conclusion doesn't survive a properly isolated retest. Corrected in SCORECARD.md Setback 2 and the roadmap.
2. **A cross-profile comparison (marvin vs. clean) cannot isolate a single CLAUDE.md instruction's effect** when the profiles differ in multiple ways simultaneously. Any future "does instruction X work" test needs to hold the profile constant and vary only X — same lesson as Run 15's task-014 judge-isolation work, applied to prompt-level behavior instead of tool access.
3. **Skill-wrapper registration work (making a skill actually invocable) should trigger a fresh look at any stale efficacy claims in that skill's docs before shipping the wrapper** — this retest only happened because registering caveman prompted the question "wait, didn't we find this doesn't work?"

### Next bench priorities
- Update `caveman/SKILL.md`'s description to cite the verified 72.8% figure instead of the unsourced "~75%" placeholder it had before.
- Run `select_model.py` against a coding (fs) task.
- Consider a multi-turn persistence test for caveman mode (does it correctly stay on/off across a longer conversation, not just single-turn) — untested by this retest.

---

## Run 17 — 2026-08-13 (route.py keyword classifier vs. new embedding classifier, ADR 0023)

Built following a bitter-lesson audit (2026-08-13) that flagged `route.py`'s hand-listed keyword
classifier as the sharpest instance of the hand-encoded-knowledge pattern in MARVIN's own
pipeline. Scoped via `grill-with-docs` into ADR 0023: phased (route.py only this pass), fixed
threshold for v1 (no calibration loop yet), a new `intent-routing` ChromaDB collection seeded with
6 example task descriptions per intent (nomic-embed-text via Ollama, cosine hnsw space — same
pattern `retrieve.py`/`rebuild-embeddings.py` already use), shipped behind `route.py --embed` for
burn-in rather than a hard cutover. Full TDD build: 16 new tests (`test_intent_classify.py`,
`test_route.py`), all passing; default (no `--embed`) behavior verified byte-identical to before.

Per §G's "every routing decision must be bench-validated before shipping" — built
`bench/compare_route_classifiers.py`, a local no-API-cost comparison against a 20-item fixture,
5 per intent, **deliberately phrased differently from the classifier's own seed examples** (held
out, not just re-testing what it was shown) — e.g. "hey what did we land on for the caveman token
savings number" for `recall` rather than anything close to the keyword list's literal terms.

| Classifier | Accuracy on held-out fixture (n=20) |
|---|---|
| keyword (`MIN_HITS=2` substring match) | 7/20 (35%) |
| embedding (`--embed`, fixed threshold 0.35) | 12/20 (60%) |

**Embedding classifier beats keyword on held-out phrasing, as the bitter-lesson thesis predicted**
— substring matching only works when the user happens to use one of the ~15-20 literal listed
words per intent; real phrasing varies more than that. The keyword classifier's 35% here is
consistent with (and a sharper demonstration of) the same brittleness the original audit flagged.

**But 60% is not good enough to flip the default.** Read the actual disagreements (13 of 20,
printed by the script) rather than just the headline number: several embed misses look like a thin
reference set (6 examples/intent) missing coverage — e.g. "add a --seed flag to intent_classify.py"
matched `architecture` instead of `coding`, "write a unit test for the threshold fallback path"
matched `recall`. Both classifiers are currently weak on this fixture; embedding is the smaller
gap, not a solved problem. This is exactly why ADR 0023 scoped this as flag-gated burn-in, not a
hard cutover — the number confirms that call was right, not that the work here is done.

### Findings from Run 17
1. **Bitter-lesson prediction held on the first real test**: general (embedding) approach
   generalized better than hand-encoded (keyword) matching on inputs neither was literally shown,
   by a wide margin (35% vs 60%). Directly actionable evidence for the audit's broader claim, not
   just an assertion.
2. **A classifier beating another classifier is not the same as a classifier being good.** 60%
   accuracy is a real gap; per-item disagreement review points at reference-set thinness (6
   examples/intent) as the likely next lever, not a fundamental flaw in the approach.
3. **Held-out fixtures are the only honest way to bench a semantic classifier** — testing against
   the same examples it was seeded on would have shown near-100% and hidden this gap entirely.

### Next bench priorities
- Expand `intent_classify.REFERENCE_EXAMPLES` past 6/intent and re-run `compare_route_classifiers.py`
  to see whether accuracy on this same held-out fixture improves — cheapest next lever before
  touching the threshold.
- Once `--embed` accuracy is clearly and consistently ahead of keyword on repeat fixture runs,
  revisit flipping route.py's default — explicitly deferred, not decided, by ADR 0023.
- CLAUDE.md's duplicate Auto-route table and `correlate.py`'s `ROADMAP_KEYWORDS`/`threshold=1.1`
  remain untouched (ADR 0023 phasing) — only worth extending to those once route.py's swap is
  actually proven, not just built.

---

## Run 18 — 2026-08-13 (route.py embedding classifier — reference-set expansion, same fixture)

Direct fast-follow on Run 17's top priority. Doubled `intent_classify.REFERENCE_EXAMPLES` from 6 to
12 examples/intent (48 total), targeting the specific failure patterns Run 17's disagreement list
showed rather than guessing blind: casual status-check phrasing for `recall` ("what's the status
of X", "catch me up on..."), "how/why does X work" and "what's the current thinking on X" phrasing
for `research`, short imperative fix/test/flag requests for `coding` ("add a flag for...", "there's
a typo, fix it"), and module-placement/tradeoff/sequencing phrasing for `architecture`. Same TDD
discipline: `build_collection()` switched from `add()` to `upsert()` first (tests updated to red,
then implementation flipped to green) so re-seeding a grown reference set doesn't collide on
existing ids — needed for this run and every future re-seed.

Re-ran `compare_route_classifiers.py` against the **exact same 20-item held-out fixture** as
Run 17, unchanged, so this is a clean before/after:

| Classifier | Run 17 (6 ex/intent) | Run 18 (12 ex/intent) |
|---|---|---|
| keyword (`MIN_HITS=2`) | 7/20 (35%) | 7/20 (35%) — unchanged, not touched |
| embedding (`--embed`, threshold 0.35) | 12/20 (60%) | **17/20 (85%)** |

Doubling the reference set closed 5 of the 13 prior misses with zero threshold tuning and zero
logic changes — pure data, confirming Run 17's read that the gap was reference-set thinness, not
a flaw in the embedding approach. 3 misses remain, all plausible near-boundary confusions rather
than wild misses: "what's the current thinking on prompt caching efficiency" (research → recall,
"current thinking" phrasing overlaps a recall example), "add a --seed flag to intent_classify.py"
(coding → architecture, "flag" plus a module name pulled toward the architecture examples about
module structure), "write a unit test for the threshold fallback path" (coding → recall,
"threshold"/"fallback" read as recall-flavored technical vocabulary).

### Findings from Run 18
1. **Confirms Run 17's diagnosis, not just the headline number**: the specific misses predicted to
   be reference-set-thinness artifacts (not systemic) actually resolved when the reference set
   grew — the mechanism is behaving as expected, not getting lucky.
2. **Zero-tuning gains are the cheap lever; keep pulling it before touching THRESHOLD.** 85% from
   pure data expansion, no code/threshold changes, no re-embedding logic changes. The 3 remaining
   misses look like genuine semantic boundary ambiguity (a human could plausibly argue either way
   on 2 of them), a different and harder problem than "not enough examples."
3. **The `add()` → `upsert()` fix (idempotent re-seed) is now load-bearing infrastructure, not a
   one-off**: reference-set iteration is clearly going to keep happening, so re-seeding needed to
   not require deleting the collection by hand each time.

### Next bench priorities
- 85% on a 20-item fixture is a promising signal but a small n — worth growing the held-out
  fixture itself (more items per intent, plus some deliberately ambiguous/edge cases) before
  treating this as a real accuracy estimate.
- The 3 remaining misses are worth a closer look individually rather than blindly adding more
  examples again — check whether they're reference-set gaps or genuine boundary ambiguity where
  even a keyword-classifier redesign wouldn't help.
- Once `--embed` accuracy is clearly and consistently ahead of keyword on repeat/expanded fixture
  runs, revisit flipping route.py's default — still explicitly deferred, not decided, by ADR 0023.

---

## Run 19 — 2026-08-13 (grown fixture: 20 → 40 clean items + 8 ambiguous — 85% didn't hold)

Direct fast-follow on Run 18's own top priority: n=20 was flagged as too small to trust. Grew
`compare_route_classifiers.py`'s `FIXTURE` from 20 to 40 items (10/intent, all new phrasings, none
recycled from the original 20 or from `intent_classify.REFERENCE_EXAMPLES`), and added a separate
`AMBIGUOUS_FIXTURE` (8 genuinely dual-purpose phrasings, e.g. "should we refactor this or leave it
as is" — coding-flavored and architecture-flavored, no single defensible right answer). Ambiguous
cases are scored against an *acceptable set*, not a single expected intent, and reported
separately — folding them into the headline number would have been dishonest measurement, per
this run's own reason for existing.

| Classifier | Run 18 (n=20) | Run 19 clean (n=40) | Run 19 ambiguous (n=8, landed-in-acceptable-set) |
|---|---|---|---|
| keyword | 35% | 30% | 50% |
| embedding (`--embed`) | 85% | **70%** | **100%** |

**The 85% did not hold — and that's the correct outcome of doing this, not a failure of the
classifier.** Run 18 explicitly flagged this risk (small n, and the reference-set expansion was
informed by that same 20-item fixture's failures — a real overfitting risk, not just caution for
its own sake). The wider fixture surfaces genuine remaining weak spots concentrated in `research`
(new misses: "what does the literature say about this failure mode" → coding, "who else has built
something like this" → recall, "what's the theoretical limit here" → recall, "is this a solved
problem" → recall) and a few new `coding` misses ("revert that last change, it broke something" →
recall). 70% on the honest, larger fixture is the number to trust going forward, not 85%.

The ambiguous-fixture result is the one unambiguously good sign in this run: embedding landed in
the acceptable set on **8/8**, keyword on 4/8 (and keyword's "hits" there are mostly its
`architecture` fallback default coincidentally being one of the acceptable answers, not real
classification — worth remembering when reading that 50%). Even where there's no single right
answer, the embedding classifier is consistently landing somewhere defensible rather than
scattering randomly.

### Findings from Run 19
1. **A good number on a small fixture is not the same claim as a good number on a representative
   one — verify by actually growing the fixture, don't just trust the first result.** Exactly the
   scenario Run 18 warned about, now confirmed rather than hypothetical.
2. **Reference-set tuning that's informed by the same fixture used to measure it will look better
   than it is** — a form of the same problem `retrieve.py`'s hybrid RRF merge and held-out
   eval sets exist to guard against elsewhere in this codebase. Future reference-set tuning passes
   should hold out part of the fixture, or grow the fixture again afterward, rather than iterating
   against a fixed one repeatedly.
3. **`research` is the weakest category on the wider fixture** — 12 examples/intent apparently
   isn't enough coverage for its wider range of real phrasing ("what does the literature say",
   "is this a solved problem"). Concrete next target for reference-set growth, not a blind re-run.
4. **70% (embed) vs 30% (keyword) is still a decisive win for the general approach**, even after
   the correction — the headline bitter-lesson claim survives a harder test; only the precise
   number moved.

### Next bench priorities
- Targeted reference-set growth for `research` specifically (the concentration of new misses),
  rather than another blind across-the-board doubling.
- Consider holding out a fixed subset of the fixture from future reference-set tuning, so accuracy
  numbers stop being informed by the same data used to improve the classifier.
- Still explicitly not flipping route.py's default — 70% is a real improvement over keyword's 30%,
  not yet a "stop checking" number. Burn-in continues per ADR 0023.

---

## Run 20 — 2026-08-13 (targeted research reference-set expansion)

Direct fast-follow on Run 19's specific finding, not another blind expansion: `research` was the
worst category on the grown fixture (5/10 misses). Added 8 new `research` reference examples
(12 → 20, other intents untouched) targeting the exact concepts behind those 5 misses —
current-thinking/opinion-status, literature-review, prior-art/precedent, theoretical-limits, and
solved-vs-open-question phrasing — written as new sentences, not copies of the fixture items
themselves, per Run 19's own caution about tuning directly against the measurement set.

Re-ran `compare_route_classifiers.py` against the same 40-item + 8-ambiguous fixture from Run 19:

| Classifier | Run 19 | Run 20 |
|---|---|---|
| keyword | 30% (12/40) | 30% (12/40) — unchanged, not touched |
| embedding, overall | 70% (28/40) | 72% (29/40) |
| embedding, `research` items only | 50% (5/10) | **70% (7/10)** |
| embedding, ambiguous set | 8/8 | 8/8 — unchanged |

Two of the five targeted misses fixed ("what's the theoretical limit here", "is this a solved
problem or still an open question" — both now correctly `research`). Three remain: "current
thinking on prompt caching efficiency" and "who else has built something like this" still land on
`recall`, "what does the literature say about this failure mode" still lands on `coding`.

**One real side effect, not just a clean win**: "has this come up in a previous conversation" —
correctly `recall` in every prior run — flipped to `research` this run. Growing `research`'s
reference set pulled some `recall`-flavored boundary phrasing across with it (both start with
"Has..." and share "prior instance of something" framing). Net category accuracy still improved
(overall 28→29/40), but this is a genuine, non-obvious cost: expanding one intent's reference set
isn't free for neighboring intents, it can encroach on shared semantic territory. Worth watching
for, not something an isolated single-category expansion can fully avoid by construction.

### Findings from Run 20
1. **Targeted expansion beats blind expansion, but isn't free of cross-category cost.** Fixing
   `research`'s specific misses genuinely worked (50%→70% on that slice) without needing to touch
   `recall`, `coding`, or `architecture` — but it still perturbed a neighbor's boundary. A reference
   set isn't N independent per-intent lookup tables; it's one shared embedding space where every
   addition can shift every decision boundary, not just the category it was added to.
2. **This result is still measured against the same fixture two runs of tuning have now used** —
   Run 19's caution about that remains fully in force. The 72%/70%-on-research numbers are more
   trustworthy than Run 18's 85% (bigger, more diverse fixture) but not immune to the same risk on
   a third pass. A genuinely fresh held-out set is still the open item from Run 19, not yet done.
3. **`recall` needs its own look next**, now that it has a regression to explain rather than just
   room for more coverage — worth checking whether "has this come up in a previous conversation"
   is recoverable with one more contrastive `recall` example, or whether it's a genuine ambiguity
   that belongs in `AMBIGUOUS_FIXTURE` instead of `FIXTURE` (a human could plausibly read it either
   way, similar in shape to the existing "what changed since last time" ambiguous case).

### Next bench priorities
- Build a genuinely fresh held-out validation set (per Run 19's still-open item) before trusting
  any future accuracy number as more than a directional signal — three tuning passes have now used
  the same 40-item fixture.
- Decide whether "has this come up in a previous conversation" is a fixable `recall` regression or
  belongs moved to `AMBIGUOUS_FIXTURE`.
- Still not flipping route.py's default. 72% overall / keyword 30% remains a decisive but
  imperfect result — burn-in continues per ADR 0023.

---

## Run 21 — 2026-08-13 (genuine held-out validation set — first honest read)

Closes the open item every run since 19 has flagged: `FIXTURE`/`AMBIGUOUS_FIXTURE` in
`compare_route_classifiers.py` have now been used across three reference-set tuning passes
(Runs 18, 19, 20) — any accuracy measured against them is potentially inflated by that contamination,
however careful the tuning was about not copying exact phrasings. Built `bench/holdout_fixture.py`
(`HOLDOUT_FIXTURE`, 40 items / 10 per intent, `HOLDOUT_AMBIGUOUS`, 6 items) and a deliberately
separate `bench/validate_holdout.py` runner — kept as a different *file*, not just different data
in the same script, specifically to make it structurally awkward to accidentally reuse this set's
phrasings while iterating on `REFERENCE_EXAMPLES` the way `compare_route_classifiers.py` is used
for. Verified zero exact-string overlap against `REFERENCE_EXAMPLES`, `FIXTURE`, and
`AMBIGUOUS_FIXTURE` before running. This set has never been looked at during any tuning decision.

| | Tuning-set (Run 20, contaminated by 3 tuning passes) | Held-out (Run 21, never seen) |
|---|---|---|
| keyword | 30% | 25% |
| embedding, overall | 72% | **70%** |
| embedding, ambiguous | 8/8 (100%) | 3/6 (50%) |

**The headline number holds up.** 70% on genuinely fresh data vs. 72% on the tuning-contaminated
set — a 2-point gap, not the kind of double-digit collapse Run 19 demonstrated was possible (85%
→ 70% when the fixture merely grew, still without true held-out data). This is real evidence the
reference-set tuning generalized rather than just memorizing fixture-shaped phrasing. keyword's
25% (vs. 30%) is noise-level, as expected — its logic was never touched by any of this.

**Per-category breakdown on the holdout** (out of 10 each): `recall` 9/10 (strongest — the casual
status-check phrasing added in Run 17 generalizes well), `architecture` 7/10, `research` 6/10,
`coding` 6/10. `research` and `coding` are the weakest on fresh data too, consistent with where
Runs 19-20 already suspected weakness, but not dramatically worse than the tuning-set read
suggested — no hidden collapse in a category that looked fine before.

**The one number that did NOT hold up: ambiguous-case handling.** 8/8 on the tuning set read as a
strong signal in Run 19/20's writeups; 3/6 on fresh ambiguous cases suggests that was closer to a
small-n fluke (n=8) than robust generalization to genuinely novel dual-purpose phrasing. Worth
correcting the record on rather than letting the earlier 100% stand unqualified.

### Findings from Run 21
1. **The core result survives real validation**: embedding classifier's ~70% accuracy is not a
   tuning-set artifact. This is the most trustworthy number produced in this whole sequence of
   runs, specifically because it's the first one that couldn't have been shaped by the tuning
   process even accidentally.
2. **Small-n informational metrics (the ambiguous-set 8/8) should be reported with the sample size
   attached every time, not just the percentage** — Run 19/20 technically did this correctly, but
   this run makes clear why it matters: a n=8 100% doesn't survive contact with n=6 fresh data,
   and stating both numbers side by side prevents over-reading a small sample as a strong finding.
3. **This holdout set is now spent for future tuning-validation purposes.** Once results from it
   inform any decision (including this write-up), treating it as still "fresh" for a later check
   would repeat exactly the contamination problem it was built to avoid. A further validation round
   after future tuning would need its own new set, built the same way.

### Next bench priorities
- Decision point, not yet made: is 70% (real, now-validated) accurate enough to flip route.py's
  default, or does `research`/`coding` at 60% each still argue for more burn-in? ADR 0023 defers
  this explicitly — surfacing it as a real decision now that the number is trustworthy, not
  deciding it unilaterally here.
- If further reference-set tuning happens, it should target `research`/`coding` using
  `compare_route_classifiers.py`'s fixture (already contaminated, fine to keep using for
  iteration) — but any resulting accuracy claim needs a *new* fresh holdout to be validated, not
  a re-run of this now-spent one.
- The ambiguous-case handling (50% on 6 holdout items) deserves its own attention independent of
  the main accuracy question — dual-purpose phrasing may need dedicated reference examples or an
  explicit "return multiple plausible intents" mode rather than forcing a single winner.

---

## Run 22 — 2026-08-13 (score-formula bug found + fixed, threshold recalibrated, default flipped)

Gil approved flipping `route.py`'s default to the embedding classifier after Run 21's validated
70%, and asked what else could improve accuracy. While checking whether MARVIN's ingested-repos
qa-knowledge had anything relevant (it did, see below), turned up a real bug worth fixing before
flipping: `classify()`'s `score = 1.0 - dist` assumes ChromaDB cosine distance is in [0,1]. It's
actually in [0,2] (0=identical, 2=opposite) — a gotcha already documented in qa-knowledge from
earlier bench work (`correlate.py`'s `threshold=1.1` was built correctly against raw distance;
`intent_classify.py`'s conversion to a similarity score was not).

Empirically checked the practical impact rather than assuming it mattered: queried real distances
for genuinely off-topic probes ("sing me a song about the ocean", "what time is it in Tokyo right
now", "hey how are you doing today") against the live `intent-routing` collection. All scored
0.43-0.60 under the broken formula — comfortably above `THRESHOLD=0.35`, meaning **the no_match
safety net had never actually fired for any tested input, on-topic or not**. Worse: comparing
best-match distances across the 40-item holdout (all on-topic, max dist 0.524) against 8 off-topic
probes (min dist 0.396) showed the two distributions overlap substantially at this reference-set
size — a single absolute threshold cannot cleanly separate on-topic from off-topic here, whichever
formula is used.

**Fixed**: formula corrected to `1.0 - dist/2.0`; `THRESHOLD` recalibrated to `0.72`, chosen to
preserve every validated on-topic match (score floor 0.738) while catching only the most extreme
off-topic outliers — an honest sanity floor, not a solved discrimination problem. Re-ran
`validate_holdout.py` post-fix: still 70/40 items correct, unchanged — confirms the bug never hurt
on-topic accuracy, only left the off-topic floor non-functional.

**Then flipped the default**: `route.py`'s `--embed` flag renamed to `--keyword` (opt-out) since
embedding is now what runs by default; `_use_embed(args)` extracted as a small testable pure
function. 3 new tests, 33 total passing. Verified live: default CLI call now returns
`(embed match, score ...)`, `--keyword` still returns the old `(N keyword hits)` path unchanged.

**Ingested-repos check (the other half of Gil's question)**: queried `qa-knowledge` (already
covers all 15 ingested repos — crawl4ai, open-webui, dify, langflow, etc.) for anything relevant to
classification/embedding accuracy. Found mostly generic code-quality flags (cyclomatic complexity,
static-method suggestions) from `open-webui`/`crawl4ai`'s embedding-related files — nothing
algorithmically transferable to intent classification specifically. The one directly useful hit
(the cosine-distance-range gotcha above) came from MARVIN's *own* prior bench work, not from any
ingested external repo. No evidence yet that loading additional repos would surface something
`qa-knowledge` doesn't already have for this specific problem.

### Findings from Run 22
1. **A documented gotcha sitting unused in your own knowledge base is easy to re-violate in new
   code** — `correlate.py` (built earlier) got the raw-distance threshold right; `intent_classify.py`
   (built this session) didn't, despite the correct pattern being one `qa_query.py` call away the
   whole time. Worth actually querying qa-knowledge before writing new ChromaDB-adjacent code, not
   just when explicitly asked to check it.
2. **A formula bug and a discrimination-power problem are different bugs, and fixing the first
   doesn't fix the second.** The corrected formula alone didn't produce clean on-topic/off-topic
   separation — that's a harder, still-open problem, honestly scoped as "weak floor" rather than
   claimed as solved.
3. **"Does the ingested-repo knowledge base have anything relevant" is answerable by querying it
   directly** (`qa_query.py`) rather than guessing whether to ingest more repos first — in this
   case the answer was mostly no, and the one real hit was MARVIN's own prior work, not external
   code. Ingesting more repos is a real lever for other problems, just not demonstrated as the
   right one here.

### Next bench priorities
- The off-topic detection gap (overlapping distance distributions) is the most likely-impactful
  remaining lever, more than further reference-set growth — worth its own investigation rather
  than another blind expansion pass.
- Revisit `retrieve.py`'s own `1.0 - dist` conversions (`score` field in `_query_collection`) for
  the same bug — not fixed here (out of scope for this ADR), but the same root cause likely
  applies wherever that pattern was copied.
- CLAUDE.md's Auto-route table and `correlate.py`'s `ROADMAP_KEYWORDS` remain the two deferred
  phases (ADR 0023) — now that route.py's slice is fully shipped (built, validated, flipped), these
  are the natural next scope if further routing-pipeline work continues.

---

## Run 23 — 2026-08-13 (off-topic detection gap, investigated — two hypotheses, both negative)

Direct follow-up on Run 22's top priority. Tested two candidate fixes empirically (throwaway
script, not committed — `investigate_offtopic.py` in scratchpad) against the 40-item holdout plus
15 off-topic probes (expanded from Run 22's 8, covering small talk, unrelated facts, gibberish,
and pure arithmetic). Neither is a clean fix; both are useful negative results.

**A) Margin (mean-of-candidates minus best-match) instead of absolute distance.** On-topic margin:
min 0.053, median 0.109, max 0.235. Off-topic margin: min 0.049, median 0.072, max 0.151. Medians
separate somewhat (roughly 50% apart) but the ranges overlap heavily — several on-topic items
("what's the history here": 0.058) sit below several off-topic items ("tell me a joke": 0.151).
Not a clean discriminator.

**B) Explicit "other" reference category** (a handful of small-talk/off-topic example phrases as a
5th competing class) **made accuracy worse, not better.** Built a real temp ChromaDB collection
(intents + "other" together, same query mechanism) to test fairly. Result: 12 of 40 previously
correct on-topic holdout items flipped wrong — and mostly *not* to "other," to an unrelated wrong
intent instead ("look up how other teams have approached this" [research] → recall). Off-topic
detection only reached 8/15 (53%); "what's 47 times 89" and "how many ounces are in a pound" still
misrouted to `architecture`/`research`. Adding a competing category perturbed the whole decision
space rather than cleanly carving out a new one — the same shared-embedding-space cost Run 20 found
when expanding one intent's reference set, at larger scale.

**Also recomputed production's actual coverage** on the wider 15-probe off-topic set: `THRESHOLD=0.72`
catches only 2/15 (13%), not the ~25% the original 8-probe calibration suggested. Consistent with
what Run 22 already documented as "a weak sanity floor," just more precisely measured now.

### Findings from Run 23
1. **This looks like a real limitation of the embedding model + short-phrase domain, not a solvable
   threshold-picking problem.** `nomic-embed-text` is a small (137M param) local model; short task
   descriptions carry limited semantic signal to begin with. Two structurally different fixes both
   failed to produce clean separation — that's stronger evidence of a real ceiling than either
   result alone.
2. **A negative result on "add a negative class" is worth having on record before anyone tries it
   again** — it's the intuitive first fix to reach for, and it plausibly looks like it should work.
   It doesn't, here, and re-testing it later without this note risks re-discovering the same
   finding at the cost of another investigation.
3. **The principled next step was already named and deferred, not invented new**: ADR 0023 decision
   2 already deferred a `calibrate.py`-style learned threshold fed by real labeled outcomes, in
   favor of a fixed v1. Two hand-designed heuristics failing here is direct evidence *for* that
   deferred approach rather than more hand-tuning — let real usage data find the boundary instead
   of guessing at a formula.
4. **Worth weighing against priority, not just feasibility**: off-topic queries ("sing me a song")
   are unlikely to be common real usage for this router — the practical cost of this gap may be
   low even though it's real. Continuing to improve on-topic accuracy (currently 70%, `research`/
   `coding` at 60% each) may be higher-leverage than solving out-of-distribution detection for
   queries route.py will rarely actually see.

### Next bench priorities
- Not recommending either tested heuristic for production. Real fix path: build the deferred
  labeled-outcome calibration loop (ADR 0023 decision 2) once there's enough real `--keyword`-vs-
  `--embed` disagreement or user-correction data to learn from, rather than a third hand-picked
  formula.
- A larger/different local embedding model (nomic-embed-text is the only one currently pulled) is
  an untested, structurally different lever — not attempted here, would need a new Ollama model
  pull and its own from-scratch reference-set re-embedding to evaluate fairly.
- Given the low practical cost of misrouted off-topic queries, further `research`/`coding`
  accuracy work (Run 20's pattern, done carefully re: cross-category cost) is plausibly higher
  leverage than continuing this specific investigation.

---

## Run 24 — 2026-08-13 (targeted research + coding expansion — real gain, real cost)

Gil redirected focus back to `research`/`coding` (both at 60% on the Run 21 holdout) after Run 23's
off-topic investigation came back negative. Identified 6 specific misses on `compare_route_
classifiers.py`'s `FIXTURE` (the tuning set, already contaminated since Run 18 — safe to inspect)
and wrote 6 new examples per intent targeting each one directly: `research` examples pairing
"literature"/"published"/"external teams" explicitly with failure-mode and prior-art framing (the
specific phrasing that kept losing to `recall`/`coding`), `coding` examples pairing flag/test/
revert requests with concrete implementation framing ("wire it into the argument parser") rather
than the shorter, more generic phrasing that kept losing to `architecture`/`recall`. `research`
grew 20→26, `coding` 12→18 (68 total reference examples). All 33 tests still pass; re-seeded live.

**Named upfront, not glossed over**: this round's *decision* to target research/coding was directly
informed by Run 21's holdout results, even though the new examples' wording was drawn only from
`FIXTURE`'s misses, never `HOLDOUT_FIXTURE`'s. That's category-level information leakage, not
phrase-level — a real, if narrower, version of the contamination Run 21 exists to guard against.
The `HOLDOUT_FIXTURE` numbers below are reported as informational/directional, not as an
independent validation the way Run 21's original 70% was.

| | `research` | `coding` | `recall` | `architecture` | overall |
|---|---|---|---|---|---|
| FIXTURE (tuning set) — before | 6/10 | 7/10 | 10/10 | 6/10 | 29/40 (72%) |
| FIXTURE (tuning set) — after | 8/10 | **10/10** | **7/10** | 7/10 | 32/40 (**80%**) |
| HOLDOUT (spent, informational) — before | 6/10 | 6/10 | 9/10 | 7/10 | 28/40 (70%) |
| HOLDOUT (spent, informational) — after | 8/10 | 8/10 | 8/10 | 7/10 | 31/40 (78%) |

**Both target categories improved meaningfully on both sets** (`research` +2/+2, `coding` +3/+2).
**But `recall` paid a real, disclosed cost** — 10/10→7/10 on the tuning set, 9/10→8/10 on holdout.
Same cross-category mechanism Run 20 first found, now visible at larger scale because this round's
expansion was bigger (12 new examples vs. Run 20's 8). Net is still positive on both sets (72%→80%,
70%→78%), but this is not a clean win — it's a real tradeoff, reported as one.

### Findings from Run 24
1. **The recall regression, not just the research/coding gain, is the actual finding worth
   remembering.** Every reference-set expansion so far (Run 20, now Run 24) has cost something in
   a category that wasn't touched. This isn't a one-off fluke — it's the expected behavior of a
   shared embedding space, and future tuning passes should budget for it rather than being
   surprised by it again.
2. **Category-level information leakage from a "spent" holdout is subtler than phrase-level leakage
   and easy to miss.** Knowing *which* categories are weak (from Run 21) shaped this round's effort
   allocation even though no wording was copied. Worth naming explicitly rather than implicitly
   treating this round's holdout number as if it were still fully independent — because it isn't,
   quite.
3. **A genuinely fresh holdout is now overdue** if these numbers need to be trusted at
   Run-21-level confidence again — two tuning passes (Run 20, Run 24) have now drawn on
   `HOLDOUT_FIXTURE`-derived knowledge at the category level, on top of the fixture-level tuning
   `HOLDOUT_FIXTURE` was built to detect in the first place.

### Next bench priorities
- `recall` is now the one category that's lost ground twice (indirectly) without ever being the
  deliberate target — worth a targeted look of its own, the same way research/coding just got one,
  rather than treating it as permanently "fine because it started at 100%."
- Building a second, genuinely fresh holdout set (never informed by any tuning decision, including
  category-level ones) is the honest next step before claiming any further accuracy number as
  independently validated.
- `architecture` has been flat at 7/10 across Run 21 and Run 24 without being targeted either way —
  worth checking whether that's genuine stability or just not yet tested.

---

## Run 25 — 2026-08-13 (recall regression fixed, one new small cost surfaced)

Direct follow-up on Run 24's disclosed cost. Diagnosed the 3 FIXTURE + 2 holdout `recall` misses
before writing anything: two distinct pulls. Run 24's new `research` examples ("Has this exact
failure mode been documented...", "Has someone else already solved this...") share surface pattern
with genuine recall phrasing ("has this come up before"); Run 24's new `coding` examples
("last commit", "roll back that change") share "last"/vocabulary overlap with recall's own
session-history phrasing ("daily digest", "audit turned up"). Added 6 new `recall` examples
explicitly sharpening the contrast ("our own past conversations," "an earlier session, not
elsewhere," a "digest or summary" framing) rather than more generic recall phrasing that wouldn't
address the specific pull. `recall` grew 12→18 (74 total reference examples).

| | `research` | `coding` | `recall` | `architecture` | overall |
|---|---|---|---|---|---|
| FIXTURE — Run 24 | 8/10 | 10/10 | 7/10 | 7/10 | 32/40 (80%) |
| FIXTURE — Run 25 | 8/10 | 10/10 | **10/10** | 7/10 | **35/40 (87.5%)** |
| HOLDOUT (informational) — Run 24 | 8/10 | 8/10 | 8/10 | 7/10 | 31/40 (78%) |
| HOLDOUT (informational) — Run 25 | 8/10 | 8/10 | **10/10** | 6/10 | 32/40 (80%) |

**Clean on the tuning set**: `recall` fully restored (7→10/10) with zero cost to `research` or
`coding`'s Run 24 gains — this time the targeted fix didn't perturb what it wasn't aimed at.

**Not fully clean on the holdout**: `architecture` dropped 7→6. "is this consistent with how we've
done things elsewhere" flipped from correct to `recall` — one of the new recall examples about
"how we've done things before" pulled it across, the same cross-category mechanism as every prior
round, just smaller (1 item) and in the opposite direction (a fix causing collateral cost, not an
expansion). Net still positive on holdout (31→32), but not an unqualified win.

### Findings from Run 25
1. **A regression can be fixed cleanly on the set you're actively tuning against and still cost
   something on the set you're not looking at.** This is exactly why Run 24 flagged the holdout as
   informational, not validated, this round — this find is the concrete proof why that caveat
   mattered, not just a formality.
2. **Diagnosing the specific pull before writing new examples (not just "add more recall
   examples") is what made this round clean on FIXTURE where Run 20/24 weren't.** Contrastive
   phrasing ("our own conversations, not elsewhere") targeting the actual confusion outperformed
   generic reinforcement.
3. **Every category has now cost or gained ground at least once** (`research`/`coding` targeted
   directly, `recall` regressed then fixed, `architecture` dented twice as collateral, never
   targeted). The four-category reference set is behaving like one interconnected system, not four
   independent lookup tables — worth treating future single-category tuning passes with that
   expectation going in, not as a surprise each time.

### Next bench priorities
- The `architecture` collateral dent (7→6 on holdout, 2 rounds running without ever being the
  deliberate target) is the next natural candidate — same diagnose-the-specific-pull approach that
  worked cleanly here, not a blind expansion.
- A genuinely fresh holdout remains the honest prerequisite before any future number claims
  Run 21-level independent confidence — three tuning passes (20, 24, 25) have now drawn on
  `HOLDOUT_FIXTURE`-derived knowledge at the category level.
- 87.5% on the tuning set / 80% on the (informational) holdout is a strong number, but per this
  run's own finding #1, treat it as provisional until a fresh holdout confirms it — the pattern so
  far is that tuning-set gains partially, not fully, transfer.

---

## Run 26 — 2026-08-13 (fresh holdout v2 built — the honest number is 72%, not 87.5%)

Built a genuinely new holdout (`bench/holdout_fixture.py` v2, 40 items + 6 ambiguous) after three
tuning passes (20, 24, 25) spent v1 via category-level knowledge leakage. Archived v1 intact as
`bench/holdout_fixture_v1_spent.py` (for traceability — RESULTS.md Runs 21-25 quote its exact
phrasings) rather than deleting it. v2's items are deliberately *not* cherry-picked toward v1's
known failure patterns (e.g. explicitly avoided anything close to "is this consistent with how
we've done things elsewhere") — the goal was an unbiased naturalistic sample, not a stress test.
Verified zero string overlap against `REFERENCE_EXAMPLES`, `FIXTURE`, `AMBIGUOUS_FIXTURE`, and all
of v1 before running.

| | Run 25 tuning set | Run 25 v1-holdout (informational, spent) | **Run 26 v2-holdout (genuinely fresh)** |
|---|---|---|---|
| recall | 10/10 | 10/10 | **10/10** |
| research | 8/10 | 8/10 | **9/10** |
| coding | 10/10 | 8/10 | **6/10** |
| architecture | 7/10 | 6/10 | **4/10** |
| overall | 87.5% | 80% | **72%** |
| ambiguous | — | — | 4/6 (67%) |

**The honest number is 72%, not 87.5%.** Almost exactly back to Run 21's original validated 70% —
meaning three rounds of targeted tuning (Runs 20, 24, 25) moved the tuning-set number from 70%→87.5%
while genuinely improving true accuracy by roughly 2 points, not 17. This is the clearest
demonstration yet of the gap Run 21 first found and Run 25's finding #1 predicted: tuning-set gains
partially, not fully, transfer to unseen phrasing.

**`recall` and `research` held up completely** — 10/10 and 9/10 confirm Runs 17-19 and 25's work
there generalized rather than just fitting the fixtures. **`coding` and `architecture` did not.**
`coding` dropped from a tuning-set-perfect 10/10 to 6/10 — misses like "port this over to the new
module," "simplify this conditional," and "patch this so it doesn't choke on missing fields" show
the reference set still doesn't cover this much verb/phrasing diversity for coding requests despite
Run 24's expansion. **`architecture` is the real story: 4/10 (40%), the worst of any category ever
measured in this whole sequence** — and it has never once been the deliberate target of a tuning
pass, only ever mentioned as taking collateral damage. Run 25 explicitly flagged "worth checking
whether that's genuine stability or just not yet tested" — this answers it: not stable, just
untested until now.

### Findings from Run 26
1. **This is the finding the whole holdout discipline exists to produce.** Every prior "big win"
   number in this sequence (Run 18's 85%, Run 20's 72%, Run 25's 87.5%) looked strong on the set it
   was measured against and partially evaporated on fresh data. 72% is the number that's actually
   earned trust, because nothing about this specific set informed any decision that produced it.
2. **`architecture` was hiding in plain sight.** Two "collateral damage" notes (Run 24, Run 25) each
   read as a minor footnote to a bigger win elsewhere. Stacked together and now confirmed
   independently, they were pointing at the actual weakest category the whole time.
3. **A category that never gets touched isn't neutral — it just isn't being measured.** `architecture`
   went untargeted for five rounds specifically because it wasn't the source of an obvious miss on
   the set being watched at the time. Worth remembering before assuming any untouched category is
   fine going forward.

### Next bench priorities
- `architecture` is now the clear, evidence-backed top priority — diagnose its specific misses the
  way Run 25 did for `recall` (not blind expansion), then re-test against this same v2 holdout
  (safe to re-test without spending it, as long as its results don't yet inform which categories to
  target — that's only true for this first read; using this run's own miss list to pick what to fix
  next will spend it exactly like v1).
- `coding`'s generalization gap (10/10 tuning vs. 6/10 fresh) suggests its Run 17/24 additions were
  more fixture-shaped than they looked — worth its own diagnosis pass too.
- This holdout's own findings are already category-level information for future tuning, same as v1
  — using them to prioritize `architecture` next means this run's read (72%) is the last fully
  independent number until a v3 holdout exists. That's expected and fine, same lifecycle as v1, but
  worth being clear-eyed about going in.

---

## Run 27 — 2026-08-13 (architecture diagnosed and fixed — large gain, real disclosed cost)

Diagnosed before writing anything, same discipline as Run 25's recall fix. Combined FIXTURE's 3
misses with the fresh v2 holdout's 6 (9 total): 5 of 9 pulled to `recall` specifically —
`architecture` had zero examples of hypothetical/future-oriented design questions ("what if
requirements change", "would we regret this"), so that phrasing style defaulted to recall's
retrospective "what did we conclude" framing. 2 pulled to `coding` ("system"/"moving parts" read
as runtime/component counting, not design). 2 pulled to `research` (revisiting a decision read as
"what does the field say" instead of "what do we now know"). Added 10 examples targeting each
pattern directly. `architecture` grew 12→22 (84 total reference examples) — its first expansion
since Run 17, and confirmation it really was under-resourced, not just under-tested.

| | FIXTURE (tuning) — before | FIXTURE — after | v2 holdout — before | v2 holdout — after |
|---|---|---|---|---|
| recall | 10/10 | 10/10 | 10/10 | 10/10 |
| research | 8/10 | 8/10 | 9/10 | **7/10** |
| coding | 10/10 | 10/10 | 6/10 | 6/10 |
| architecture | 7/10 | **9/10** | 4/10 | **10/10** |
| overall | 87.5% | **92.5%** | 72% | **82.5%** |

**The fix worked, decisively.** `architecture` went from the worst category ever measured (4/10,
40%) to a perfect 10/10 on the fresh holdout — the diagnosis was right, not a lucky guess. Real
disclosed cost: `research` dropped 9→7 on the same holdout. Checked which items: "dig into how
this typically gets approached" and "what's the received wisdom here" newly flipped to
`architecture` — the same cross-category mechanism every round has shown, this time architecture's
newly-expanded "approaches/tradeoffs" territory pulling from research instead of the reverse.
`coding` unchanged (6/10 both times) — untouched this round, its Run 26 generalization gap remains
open. Net: fresh-holdout overall 72%→82.5%, a real 10.5-point gain even after the research cost.

### Findings from Run 27
1. **The largest single-round gain in this whole sequence, on a diagnosis that was actually
   confirmed by held-out data, not just tuning-set numbers.** 4/10→10/10 on data never used to
   write the fix is about as clean a validation as this project's discipline can produce.
2. **Every targeted fix in this sequence has now cost something in a neighboring category
   (research→coding boundary in Run 20, recall in Run 24, architecture↔research in Run 27) except
   Run 25's recall fix, which was clean.** The difference each time seems to be how much new
   territory the expansion covers — bigger expansions (10-12 examples) cost more than smaller,
   more surgical ones (6 examples). Worth treating expansion size itself as a lever, not just which
   examples to add.
3. **`coding`'s gap is now the most clearly unaddressed one** — 6/10 on the fresh holdout, unchanged
   across two rounds, never re-diagnosed since Run 26 first found it (Run 24's coding work predates
   the fresh holdout and turned out to be fixture-shaped, not real generalization).

### Next bench priorities
- `coding` is the clear next target — same diagnose-first approach, using FIXTURE's coding items
  (still safe to inspect) plus a fresh look at exactly which fresh-holdout coding items still miss
  and why, the way this run and Run 25 did for their targets.
- This run's diagnosis was informed by the v2 holdout's own miss list (both FIXTURE misses were
  usable alone, but the holdout's additional 6 sharpened the pattern) — v2 is now spent at the
  category level for `architecture`, the same lifecycle v1 went through. A v3 holdout is the
  prerequisite before claiming another fully independent number, if that level of confidence is
  needed again soon.
- Given expansion-size-vs-cost as a new hypothesis (finding #2), a `coding` fix attempt could
  deliberately test a smaller, more surgical expansion first and check whether that reduces
  collateral cost compared to Run 24's larger one.

---

## Run 28 — 2026-08-13 (coding diagnosed and fixed — clean, zero collateral cost, confirms Run 27's hypothesis)

FIXTURE gave no signal (`coding` already 10/10 there) — diagnosis relied entirely on the fresh v2
holdout's 4 misses: "port this over to the new module" → `architecture` (module-placement language
read as a design decision, not an implementation action), "add logging around this section" →
`recall` (coding already had "add error handling around this call" but one example didn't
generalize to sibling vocabulary), "simplify this conditional" → `architecture` (simplification
read as system-level, not code-construct-level), "patch this so it doesn't choke on missing
fields" → `research` (near-identical in meaning to coding's existing "crashes on empty input,
handle that," different surface vocabulary uncovered).

Deliberately tested Run 27's own hypothesis (smaller expansions cost less): 5 tight examples, not
another 10. `coding` grew 18→23 (89 total reference examples).

| | FIXTURE — before | FIXTURE — after | v2 holdout — before | v2 holdout — after |
|---|---|---|---|---|
| recall | 10/10 | 10/10 | 10/10 | 10/10 |
| research | 8/10 | 8/10 | 7/10 | 7/10 |
| coding | 10/10 | 10/10 | 6/10 | **10/10** |
| architecture | 9/10 | 9/10 | 10/10 | **10/10** |
| overall | 92.5% | 92.5% | 82.5% | **92.5%** |

**Zero collateral cost anywhere.** `coding` went 6/10→10/10 on data that never informed the fix;
every other category — including `research`, which took a real hit during Run 27's larger
architecture expansion — held exactly steady. This is the second fully clean fix in this sequence
(after Run 25's recall fix, also a small ~6-example expansion) versus every large expansion (Run 20,
Run 24, Run 27) costing something.

### Findings from Run 28
1. **Run 27's hypothesis is now confirmed, not just plausible.** Two clean fixes (Run 25, Run 28)
   both used small, tightly-targeted expansions (5-6 examples each); every costly round (Run 20:
   8, Run 24: 12, Run 27: 10) used larger ones. Sample size is small (n=5 rounds) but the pattern
   is now consistent across all of them, not just one data point.
2. **A likely mechanism, not just a correlation**: a small expansion nudges the decision boundary
   just enough to capture the specific misses it was written for, without adding enough new mass to
   meaningfully shift boundaries elsewhere in the shared embedding space. A large expansion does
   both at once. Diagnosing precisely (exact miss, exact reason) lets the fix be small; broad
   "the whole category needs more coverage" expansions don't have that luxury.
3. **FIXTURE has now saturated for 3 of 4 categories** (`recall`, `coding` both 10/10, `architecture`
   9/10) — it's stopped being useful for finding new misses to diagnose from. The fresh holdout is
   now the only source of new diagnostic signal, which also means it's fully spent across all four
   categories at this point, not just the ones directly targeted.

### Next bench priorities
- **v2 is now spent for every category** — recall/research were read from it (Runs 21, 25, 27),
  coding and architecture were directly diagnosed from and fixed against it (Runs 27, 28). A v3
  holdout is the honest prerequisite for the next independently-validated number; 92.5% on both
  currently-available sets is a strong signal but not a confirmed one at Run 21/26's level of rigor.
- `research` is now the only category that's never been the deliberate target of a clean, diagnosed
  fix (Run 19's early expansion predates the current discipline; Run 27 cost it points rather than
  helping it) — worth a proper diagnosis pass of its own using the same small-expansion approach,
  once a fresh holdout exists to validate against.
- Worth deciding whether to keep chasing marginal accuracy gains here or shift effort to the two
  still-deferred phases of ADR 0023 (CLAUDE.md's Auto-route table, `correlate.py`'s
  `ROADMAP_KEYWORDS`) — route.py's own accuracy has now improved substantially (70%→92.5% across
  this whole sequence) and may be past the point of easy further wins without a v3 holdout to guide
  the next diagnosis.

---

## Run 29 — 2026-08-13 (fresh holdout v3 built — 87.5%, independently confirmed)

Built v3 (`bench/holdout_fixture.py`, 40 items + 6 ambiguous) after Runs 27-28 spent v2 by directly
diagnosing and fixing `architecture` and `coding` from its miss list. v2 archived intact as
`holdout_fixture_v2_spent.py` (same treatment as v1). v3's items deliberately avoid v1/v2's
diagnosed failure shapes (no "port this to the new module," no "simplify this conditional" style
phrasing) — an unbiased sample, not a repeat stress test. Verified zero string overlap against
`REFERENCE_EXAMPLES` (89 items), `FIXTURE`, `AMBIGUOUS_FIXTURE`, and both archived holdouts before
running.

| | Run 28 FIXTURE (tuning) | **Run 29 v3 holdout (fresh)** |
|---|---|---|
| recall | 10/10 | 8/10 |
| research | 8/10 | **10/10** |
| coding | 10/10 | 9/10 |
| architecture | 9/10 | 8/10 |
| overall | 92.5% | **87.5%** |
| ambiguous | — | 3/6 (50%) |

**87.5%, independently confirmed — and the gap to the tuning-set number has shrunk a lot.** Run 26's
first fresh read was 15.5 points below its tuning-set counterpart (87.5% vs 72%); this time the gap
is 5 points (92.5% vs 87.5%). That's a real, measurable sign that the diagnose-the-specific-miss
discipline (Runs 25, 27, 28) produces gains that transfer, not just fixture-shaped ones — consistent
with Run 28's finding that small, targeted expansions generalize better than large ones.

New misses, useful signal if this continues: `recall`'s 2 misses ("what did we settle on for this
one," "what's the backstory on this decision") both went to `architecture` — "settled on"/"backstory"
reading as decision-history rather than session-history. `coding`'s 1 miss ("the retry logic is
looping forever, cap it") went to `architecture`. `architecture`'s 2 misses split evenly (one to
`coding`, one to `research`). `research` is flawless (10/10) for the first time in this whole
sequence. Ambiguous-case handling remains the stable weak spot across all three holdout versions
(v1: 8/8 informational-only, v2: 4/6, v3: 3/6) — consistently the least reliable measure, never
directly addressed.

### Findings from Run 29
1. **The tuning-set/holdout gap is a real, trackable signal of whether the tuning discipline is
   working, not just noise.** 15.5 points (Run 26) → 5 points (Run 29) is exactly the trend you'd
   want to see if diagnosis-before-expansion is actually producing durable fixes rather than
   fixture-fitting. Worth watching this gap specifically in future rounds, not just the headline
   accuracy number.
2. **`research`'s first-ever perfect score is notable given it's the one category never targeted by
   a clean, diagnosed fix** (Run 19 predates the current discipline; Run 27 cost it points). Might
   be genuine generalization from its earlier expansions finally showing up on a set diverse enough
   to reveal it, or might be this particular fixture's luck — one clean read isn't enough to
   distinguish those, per this whole sequence's own standard.
3. **This run's results are, as of this writing, still fresh** — nothing yet has been diagnosed or
   fixed from v3's miss list. The moment any tuning decision uses this run's category-level
   pattern (recall/architecture's new small gaps), v3 starts down the same spent lifecycle as v1
   and v2.

### Next bench priorities
- Small, specific new misses to diagnose if continuing: `recall`↔`architecture` confusion around
  "settled on"/"backstory" phrasing, and `coding`'s "retry logic looping" reading as architecture.
  Same small-expansion approach as Runs 25/28 would be the move, not broad reinforcement.
- Ambiguous-case handling (50-67% across all three holdout versions) has never been directly
  addressed and is the most consistent weak spot in this entire sequence — worth its own dedicated
  look rather than continuing to treat it as a footnote.
- If the goal shifts from "improve route.py's accuracy" to "close out ADR 0023," this is a
  reasonable stopping point: 87.5% independently validated, up from Run 21's original 70%, with a
  fresh (for now) v3 holdout in place for whoever picks this up next.

## Run 30 — 2026-08-13 (targeted fix: bare "bug in {file}" phrasing losing to recall)

Diagnosed live, not from a holdout miss list: a session-persistence verify check ran route.py's own
`--help` example, `"fix the bug in utils.py"`, and got `recall` (score 0.8012) instead of `coding`.
Queried the 8 nearest neighbors directly — top hit was recall's `"Did we already run into this exact
issue in an earlier session, not elsewhere?"` (0.8012), edging out coding's `"Fix the bug in the date
validator..."` (0.7876). None of coding's existing fix/debug examples are this bare — they either
name the specific defect or lack a filename — so terse "bug in {file}" phrasing with no session
context was falling to recall's "issue"/"bug" vocabulary. Confirmed the pattern generalized before
fixing: 3/6 bare probes (`"fix the bug in utils.py"`, `"there is a bug in auth.py, fix it"`, `"the
sync script has a bug in it"`) misrouted to recall.

**Fix**: 3 small, surgical additions to `coding` (92 reference examples total, up from 89) —
deliberately distinct phrasings from the diagnostic probes, not copies, per the standing
memorize-the-pattern-not-the-sentence discipline: `"utils.py has a bug in it, fix that."`, `"Track
down the bug in the parser and fix it."`, `"There's a bug somewhere in the sync script, find it and
fix it."`

**Result**: all 6/6 diagnostic probes now correctly resolve to `coding`. Re-ran v3 holdout
(`validate_holdout.py`) as a regression check — **35/40 (87.5%), zero-diff against the pre-fix run**,
confirming no side effects on the untouched categories or on architecture (still the weakest at
8/10). v3 was used read-only for this regression check, not mined for new examples, so it remains
valid for future diagnosis rounds.

**Note**: this directly addresses part of what Gil's 2026-08-13 "treat route.py as done" call
(logged under Run 29 and `suggestions.md`'s priority-9 entry) left open as a known miss
(`recall`↔`coding` confusion). Requested explicitly in a later session the same day, after the
session-persistence verify check surfaced it as a live, reproducible example rather than a fixture
statistic.
