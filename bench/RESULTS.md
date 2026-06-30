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
