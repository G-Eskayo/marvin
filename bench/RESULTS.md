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
