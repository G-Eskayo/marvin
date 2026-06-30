# MARVIN Bench — Scorecard

> Last updated: 2026-06-30 (Runs 1–5, 7 tasks, 3 profiles)

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

### 4. QA task discriminator gap

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
| **LLM-judge grading** | Substring matching passes wrong answers that contain the expected string; fails correct answers that use a different method name. Semantic correctness is not assessed. | `[build]` H — LLM-judge grading |
| **Hard/ambiguous tasks** | All current coding tasks score 1.00 across all profiles. We can't show where MARVIN's skill routing *earns* its cost vs lean if the tasks are never hard enough to differentiate. | `[build]` H — Hard/ambiguous task design |
| **Isolated-memory QA** | Current QA tasks can all be answered by reading files on disk. A clean profile that reads the right file scores 1.00 with no memory at all. True discriminators need file access restricted for clean/lean. | `[build]` H — Isolated-memory QA task type |
| **Variance (repeat runs)** | All results are N=1. A ±15% variance on token count is plausible from sampling. Don't trust magnitudes until N≥5 per condition. | `[build]` H — Repeat runs + variance reporting |
| **Cross-model** | All runs use the same model. MARVIN's recall gains may shrink on smarter models that navigate well without memory. | `[build]` G — Cross-model bench extension |
| **Automatic profile routing** | Profile selection is currently manual friction. Solving this is the key to capturing the lean-vs-marvin savings without requiring the user to think about it. | `[decision]` H — Automatic profile routing |
