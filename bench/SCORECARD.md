# MARVIN Bench — Scorecard

> Last updated: 2026-06-30 (Runs 1–12, 11 tasks, 3 profiles, 2 API models + Ollama 7B/14B)

The honest summary of what the bench has actually proven. Gains and setbacks carry equal weight here — both matter.

---

## Verdict

MARVIN wins on **knowledge and navigation**. It loses (token cost, no quality gain) on **mechanical coding**. One optimization (caveman mode) actively backfired and was removed. Profile routing — using a stripped-down "lean" config for coding and the full MARVIN config for recall/research — recovers most of the downside.

---

## GAINS

### 1. Recall — MARVIN knows things the others don't

| Profile | Correct |
|---------|---------|
| clean   | **0.00** — answered incorrectly |
| lean    | **0.00** — answered incorrectly |
| marvin  | **1.00** — answered correctly |

Task: *"What specifically goes wrong when MARVIN scripts run under system Python instead of the venv interpreter?"*

Only MARVIN could answer this because the answer (`tag matching` — its own term for the silent degradation) exists only in memory, not in any file on disk. Base Claude Code has no access to session history or the injected memory index. **Cost difference: near zero** (18,418 vs 18,998 tokens total).

**What this means:** MARVIN's memory layer provides answers that clean Claude Code literally cannot produce — at essentially no extra cost on recall tasks.

---

### 1b. MARVIN advantage grows on weaker models (Haiku cross-model run)

Run 8 repeated the three recall discriminator tasks with `--model claude-haiku-4-5-20251001`.

| Task | Profile | Sonnet result | Haiku result |
|------|---------|---------------|--------------|
| task-002 | clean | 0.00 | 0.00 |
| task-002 | marvin | **1.00** | **1.00** |
| task-007 | clean | 1.00 (slow) | **0.00 FAIL** — didn't search at all |
| task-007 | marvin | 1.00 | **1.00** |
| task-011 | clean | 0.00 | 0.00 |
| task-011 | marvin | **1.00** | **1.00** |

**Memory wins hold on Haiku** — task-002 and task-011 show the same clean gap at near-zero overhead.

**Navigational gap grows on Haiku** — on Sonnet, clean navigated slowly but correctly on task-007. On Haiku, clean didn't search at all (1 turn, 0 tool calls, FAIL). MARVIN still retrieved the answer correctly (2 turns, 1 tool call, PASS).

**Cost is ~60% lower** — Haiku recall tasks cost ~$0.02 vs ~$0.05 on Sonnet, with the same MARVIN advantage.

**Strategic implication:** MARVIN is *more* valuable on cheaper, weaker models than on Sonnet. The optimal routing for recall tasks is MARVIN + Haiku: full capability at ~60% of the Sonnet cost. MARVIN + Sonnet is only needed for tasks requiring complex reasoning alongside recall.

---

### 1c. Local model context injection — works for facts, fails for jargon (Run 9)

Run 9 added `--runner ollama` to bench.py and tested `qwen2.5:7b` (4.7 GB, local, $0.00 per run) against the two memory discriminator tasks. Profile=marvin injects the full MEMORY.md + all linked memory files as a system message.

| Task | Profile | Result | Judge | What happened |
|------|---------|--------|-------|---------------|
| task-011 (cosine threshold = 1.1) | clean | 0.00 | FAIL | fabricated numbers (45, 18, 40%, 0.8) |
| task-011 (cosine threshold = 1.1) | **marvin** | **1.00** | **pass** | found and reported 1.1 from injected context |
| task-002 ("tag matching") | clean | 0.00 | FAIL | generic "import errors / missing deps" answer |
| task-002 ("tag matching") | **marvin** | **0.00** | **FAIL** | still gave generic Python venv answer — context ignored |

**Why task-011 works:** the answer is a specific number (1.1) that the model can't plausibly hallucinate. There's no training knowledge to compete — it either finds it in context or makes something up. Context wins.

**Why task-002 fails:** the answer requires using the project-specific term "tag matching." The model's training knowledge about Python venv issues (import errors, missing dependencies) is strong and plausible. When asked "what goes wrong?", it applies its training knowledge and completely ignores the injected context's project-specific terminology.

**The pattern:**
- Specific facts (numbers, thresholds, dates) → context injection works → local model viable at $0.00
- Project-specific jargon that competes with training knowledge → context injection fails → Haiku remains cheapest viable option

**Savings realised:** task-011-class tasks (factual recall) can move to local qwen2.5:7b at $0.00 instead of Haiku at ~$0.02. That's a 100% cost reduction for that subset.

**Updated by Runs 10–12 below — the gap was closed by 14B + RAG.**

---

### 1d. 14B + RAG closes the jargon gap — semantic parity at zero cost (Runs 10–12)

Runs 10–12 crossed `--context {full,rag}` with `qwen2.5:7b` and `qwen2.5:14b`. The benchmark's substring scorer and LLM judge are treated as separate signals (they diverge for local models — see below).

**Complete matrix for the two discriminator tasks:**

| Model | Context | task-002 substr | task-002 judge | task-011 substr | task-011 judge |
|-------|---------|-----------------|----------------|-----------------|----------------|
| 7B | clean | 0.00 | FAIL | 0.00 | FAIL |
| 7B | full | 0.00 | FAIL | 1.00 | FAIL† |
| 7B | rag | 0.00 | FAIL | 1.00 | FAIL† |
| 14B | clean | 0.00 | FAIL | 0.00 | FAIL |
| 14B | full | 0.00 | FAIL | 1.00 | FAIL† |
| **14B** | **rag** | **0.00** | **PASS ✅** | **1.00** | **PASS ✅** |
| claude-haiku + marvin | — | 1.00 | PASS | 1.00 | FAIL† |
| claude-sonnet + marvin | — | 1.00 | PASS | 1.00 | PASS |

†Systematic judge error: the LLM judge incorrectly calls "1.1" implausible because it confuses cosine distance (0–2 range) with cosine similarity (0–1 range). Substring score of 1.00 is the reliable signal for task-011.

**Why 14B + RAG passes where 7B + full fails (task-002):**

- Full injection (4177 tokens, 15 files) → model applies training knowledge about Python venv (import errors, missing deps) and ignores injected context
- RAG injection (2071 tokens, 3 targeted files) → `marvin-venv-interpreter.md` is the #1 semantic hit at 0.86 similarity; it lands at the top of the system message with no competing noise
- 7B + RAG: model reads the context but reproduces the term as "tag-**keyword** matching" (slightly wrong)  
- 14B + RAG: model reads the context and says "silently degrade... fall back to less effective **tag-keyword** matching" — judge passes (semantically correct), substring fails (exact phrase differs by one word)

**Why the judge score matters more than substring for local models:**
Claude (the judge) evaluates meaning. If the answer conveys the correct project-specific concept — that MARVIN scripts silently degrade to a simpler matching strategy when run under system Python — the judge passes. The substring scorer requires the exact phrase "tag matching" without interpolation.

**Practical verdict: 14B + RAG = zero-cost semantic parity with Haiku**

For actual user interaction (asking a question, getting an answer), 14B + RAG returns a semantically correct, contextually grounded response at $0.00. The one-word phrase difference ("tag-keyword matching" vs "tag matching") is invisible to a human reader. For applications requiring exact phrase reproduction (log parsing, templated output), Haiku is still needed.

**Cost comparison for recall tasks:**

| Option | Cost per recall task | Quality |
|--------|---------------------|---------|
| qwen2.5:14b + RAG (local) | **$0.00** | Semantic parity (judge pass) |
| claude-haiku + marvin | ~$0.02 | Exact phrase (substr pass) |
| claude-sonnet + marvin | ~$0.05 | Full (substr + judge pass) |

---

### 2. Navigation efficiency — MARVIN finds the answer 3× cheaper

All three profiles eventually answered the same question correctly (caveman mode token counts from Run 1). But the path they took was wildly different:

| Profile | Tokens    | Tool calls | Correct |
|---------|-----------|------------|---------|
| clean   | **95,682** | **6**      | 1.00    |
| lean    | **66,762** | **4**      | 1.00    |
| marvin  | **45,905** | **2**      | 1.00    |

MARVIN used **52% fewer tokens** and **3× fewer tool calls** than clean — because it knew where to look immediately. Clean had to explore.

**What this means:** On navigational tasks (where is X, what happened in Y, what did the bench find), MARVIN's memory doesn't just prevent wrong answers — it dramatically cuts search cost even when all profiles eventually get it right. The ROI is real whether correctness differs or not.

---

### 3. Profile routing — recovers the coding overhead

Adding a `lean` profile (13-line CLAUDE.md, no memory, no skill routing) confirmed that most of MARVIN's token tax on coding is avoidable. Run lean on coding tasks, MARVIN on recall/research:

| Profile | task-001-bugfix tokens | task-003-refactor tokens |
|---------|------------------------|--------------------------|
| clean   | 51,662                 | 107,064                  |
| lean    | 52,685 (+2%)           | 109,799 (+3%)            |
| marvin  | 56,073 (+9%)           | 116,630 (+9%)            |

Lean sits only 2–3% above clean (residual = the 13-line overhead). MARVIN sits 9–10% above clean on coding. **Routing to lean on coding tasks saves ~7–9% vs always using MARVIN.**

---

## SETBACKS

### 1. Coding tasks — MARVIN adds ~10% overhead with zero quality gain

On every coding task run so far, all three profiles produce the same correct answer. MARVIN just costs more to get there.

| Task | clean tokens | marvin tokens | Δ | Quality difference |
|------|-------------|---------------|---|--------------------|
| task-001-bugfix | 51,662 | 56,073 | **+9%** | None — both correct |
| task-003-refactor | 107,064 | 116,630 | **+9%** | None — both correct |
| task-005-date-validator | 59,548 | 63,525 | **+7%** | None — both correct |
| task-006-email-lookup | 59,685 | 64,352 | **+8%** | None — both correct |

The overhead is the always-loaded CLAUDE.md + skill routing table + memory index. It fires on every task whether or not it's relevant. **If you never do recall or research work, MARVIN is a pure cost with no benefit.**

---

### 2. Caveman mode backfired — removed

The "caveman mode: always active" instruction in CLAUDE.md was supposed to reduce output verbosity. The bench showed it did the opposite:

| Profile | Output tokens (task-004) |
|---------|--------------------------|
| clean   | **176**                  |
| marvin  | **215** (+22%)           |

MARVIN produced 22% *more* output than base Claude Code on an identical question. Anti-correlated with its stated goal. **Caveman mode has been removed from CLAUDE.md.**

---

### 3. The always-on overhead has no off switch for coding

Even on tasks where MARVIN's memory, skills, and hooks are entirely irrelevant (a self-contained bugfix in an isolated temp directory), MARVIN loads and processes the full CLAUDE.md, routing table, lexicon, and memory index on every turn. There is no routing logic that prevents this — the overhead is structural.

Partial mitigation: the lean profile. But lean requires the user to explicitly choose the right profile for each task, which is friction.

---

### 4. Hard coding tasks — all profiles still tie at 1.00

Three hard tasks were specifically designed to split profiles: a hidden semantic bug (`discard` removes all occurrences, not one), an LRU zero-hit-rate via unstable timestamp key, and a TOCTOU oversell race. All three profiles passed all three tasks with LLM judge grading.

| Task | clean | lean | marvin | Winner |
|------|-------|------|--------|--------|
| 008 SortedList discard bug | 1.00 pass, 117k tok | 1.00 pass, 97k tok | 1.00 pass, 102k tok | **lean** (efficiency) |
| 009 LRU cache key | pass (judge), 90k tok | pass (judge), 115k tok | pass (judge), 98k tok | **clean** (efficiency) |
| 010 TOCTOU race | 1.00 pass, 72k tok | 1.00 pass, 75k tok | 1.00 pass, 78k tok | **clean** (efficiency) |

These bugs are textbook patterns in Claude's training data. Modern Claude knows TOCTOU, unstable cache keys, and list-mutation semantics cold — no skill invocation or memory needed. MARVIN's TDD and diagnose discriminators loaded context but produced no correctness gain. **Clean is cheapest on all three.**

**What this means:** MARVIN's skill routing does not improve outcomes on well-known bug patterns. Its advantage remains strictly in recall (task-002) and navigation (task-007). Designing tasks that genuinely require MARVIN's capabilities requires out-of-distribution knowledge — not just harder bugs.

---

### 5. QA task discriminator gap

Most "does memory help?" QA tasks turned out to be answerable by file-reading too. If the answer is in any file the model can read, all profiles score 1.00 — so the task proves nothing about memory. Only task-002 (answer is in a session-injected memory index, never written to disk) is a true discriminator so far.

Example failure: the original task-007 asked about a WeasyPrint issue documented in `render_pdf.py`. All three profiles read the file and scored 1.00. The task was redesigned.

**Gap:** most real-world knowledge MARVIN accumulates is also derivable from files. Designing tasks that isolate memory-only answers is harder than it looks.

---

## Task Suite

| Task | Type | Tests | Current finding |
|------|------|-------|-----------------|
| **001-bugfix** | fs / code | Off-by-one + mutation bug | All correct. MARVIN: +9% tokens, no quality gain |
| **002-recall** | qa / memory | Answer exists only in session memory | **MARVIN wins: 1.00 vs 0.00 for clean + lean** |
| **003-refactor** | fs / code | Multi-file shared-module extraction | All correct. MARVIN: +9% tokens, no quality gain |
| **004-caveman** | qa / behavioral | Does caveman mode reduce output? | **MARVIN loses: 215 vs 176 output tokens (+22%)** |
| **005-date-validator** | fs / code | Semantic bug (impossible calendar dates) | All correct. MARVIN: +7% tokens, no quality gain |
| **006-email-lookup** | fs / code | Shared helper with opposite caller semantics | All correct. MARVIN: +8% tokens, no quality gain |
| **007-dyld-recall** | qa / navigational | Bench self-knowledge (file-findable) | All correct. **MARVIN: 52% fewer tokens, 3× fewer tool calls** |
| **011-qa-recall** | qa / memory | Answer in MEMORY.md only — research colony first-run stats | **MARVIN wins: 1.00 vs 0.00 for clean + lean. Delta: +627 tokens. Zero tool calls all profiles.** |
| **008-sorted-list** | fs / code | Hidden semantic bug (discard removes all, not first) | All correct (LLM judge). Lean cheapest: 97k. MARVIN: 102k (+5% vs lean). TDD discriminator **did not split profiles** |
| **009-cache-key** | fs / code | LRU cache zero hit rate (unstable timestamp key) | All correct (LLM judge). **Clean cheapest: 90k**. MARVIN: 98k (+9%). Diagnose skill loaded extra context with no correctness gain |
| **010-inventory-race** | fs / code | TOCTOU oversell race (SELECT then UPDATE) | All correct (LLM judge). Clean: 72k, lean: 75k, MARVIN: 78k (+9%). TOCTOU is in training distribution — no discriminator gap |

---

## Profiles

| Profile | Config | Use for |
|---------|--------|---------|
| `clean` | Base Claude Code. No CLAUDE.md, no skills, no memory. Auth only. | Control baseline |
| `lean` | 13-line CLAUDE.md. TDD + grill defaults. No memory, no routing overhead. | Mechanical coding tasks |
| `marvin` | Full `~/.claude` setup. CLAUDE.md + skills + memory hooks + lexicon. | Recall, research, architecture, navigation |

---

## How to run

```bash
cd ~/marvin-bench          # or ~/.agents/bench/

# build the clean profile from keychain (first time only)
profiles/setup.sh

# run the full suite (all 3 profiles)
python3 bench.py tasks/*

# run one task
python3 bench.py tasks/task-002-recall

# run specific profiles only
python3 bench.py tasks/* --profiles clean,marvin
```

Results print a comparison table and save to `results/<task>-<timestamp>.json`. Full run history with findings is in [`RESULTS.md`](RESULTS.md).

---

## What's not measured yet (all tracked in roadmap section H)

These are known gaps in what the bench currently proves. Results so far are directional, not definitive, until these are addressed.

| Gap | Why it matters | Roadmap item |
|-----|----------------|--------------|
| **LLM-judge grading** | ✅ Shipped (Run 6). `--judge` flag available. | `[done]` H |
| **Hard/ambiguous tasks** | ⚠️ 3 designed + run (008/009/010) — all profiles tied 1.00. Textbook bugs are insufficient. True discriminator requires out-of-distribution knowledge. | `[build]` H — harder OOD tasks needed |
| **Isolated-memory QA** | ✅ Shipped (Run 7). task-011: MEMORY.md one-liner loaded at session start, "do NOT search files", 0 tool calls all profiles. clean 0.00, lean 0.00, marvin 1.00 at +627 token cost. | `[done]` H |
| **Variance (repeat runs)** | ✅ Shipped (Run 5). `--repeat N` available. Not yet applied to hard tasks. | `[done]` H |
| **Cross-model** | ✅ Shipped (Run 8). `--model` flag added. Haiku run: memory wins hold, navigational gap *grows* on weaker models, ~60% cost reduction. MARVIN is MORE valuable on Haiku, not less. | `[done]` G |
| **Automatic profile routing** | ✅ Shipped. `route` script + shell aliases (claude-recall/code/arch/research) + CLAUDE.md session-start step 7 auto-suggests optimal profile on first message. | `[done]` H |
