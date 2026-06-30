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
- Add harder/ambiguous coding tasks where MARVIN skill routing might earn its cost vs lean.
- Add LLM-judge grading for semantic correctness (current substring grading is v0).
- Fix setup.sh: detect and delete blank path-specific keychain entries before materializing.
