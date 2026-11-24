# Ticket 675: Ready for Manual Execution

**Status:** ✅ Implementation complete, decisions locked, all scaffolding in place

**Date:** 2026-11-23  
**Ticket:** G-Eskayo/marvin#675  
**Goal:** Tune qwen2.5:3b on paper-dive judgment using Claude-as-teacher spec search

---

## Decisions Locked (A, A, A)

1. **search-space (A):** Resident-only `qwen2.5:3b` — no re-downloading deleted models
2. **vendor (A):** Reimplement in-house, reusing bench.py patterns
3. **accept (A):** Accuracy bar = within ~3.2 points of Claude baseline

---

## Files Ready for Execution

### Core Scripts (Ready to run manually)

| File | Purpose | Command |
|------|---------|---------|
| `bench/benchmark_from_chroma.py` | Build frozen benchmark | `python bench/benchmark_from_chroma.py --sample-count 50` |
| `bench/spec_search.py` | Run optimization loop | `python bench/spec_search.py --benchmark benchmarks/*.json --max-rounds 10` |

**Expected runtimes:**
- Benchmark build: 5-15 min (depends on ChromaDB size, Claude API latency)
- Search: 5-20 min (depends on max_rounds)

### Tests (Ready to verify offline)

```bash
~/.agents/venv/bin/python -m pytest bench/tests/test_spec_search.py -v
```

✅ **All tests pass with zero real network calls** (fully mocked via chat_fn injection)

### Integration Points

- `skills/paper-dive/scripts/logic_auditor.py` — Updated to load `judgment_spec.json`
- `skills/paper-dive/config/judgment_spec.json` — Output file (creates if tuning succeeds)

### Documentation

| File | Contents |
|------|----------|
| `docs/design/675-spec-search-paper-dive-judgment.md` | Full design doc + test adversarial list |
| `SPEC_SEARCH_MANUAL_RUN.md` | Step-by-step execution guide |
| `IMPLEMENTATION_SUMMARY_675.md` | What's built, what's tested, what's left |
| `bench/RESULTS.md` | Added Run 33 template entry (fill in after execution) |

---

## Pre-Flight Checklist

Before manual execution, verify:

- [ ] Ollama running: `ollama serve` ✅
- [ ] Model pulled: `ollama list | grep qwen2.5:3b` ✅
- [ ] Claude available: `which claude` ✅
- [ ] Venv active: `. ~/.agents/venv/bin/activate` ✅
- [ ] Paper-knowledge has papers: ChromaDB query will show count ✅

---

## Execution Steps (Manual)

### Step 1: Build Frozen Benchmark

```bash
cd /path/to/this/worktree
~/.agents/venv/bin/python bench/benchmark_from_chroma.py \
    --sample-count 50 \
    --out bench/benchmarks/paper-dive-judgment-$(date +%Y%m%d-%H%M%S).json
```

**Verify output:**
- File created: `bench/benchmarks/paper-dive-judgment-*.json`
- Contains 50 samples (or fewer if paper-knowledge is smaller)
- Each sample has: slug, title, abstract, extraction, paper_type, claude_label, status

### Step 2: Run Spec Search

```bash
~/.agents/venv/bin/python bench/spec_search.py \
    --benchmark bench/benchmarks/paper-dive-judgment-*.json \
    --max-rounds 10 \
    --out bench/results/spec-search-results-$(date +%Y%m%d-%H%M%S).json
```

**Verify output:**
- File created: `bench/results/spec-search-results-*.json`
- Contains: baseline_accuracy, best_accuracy, edits_accepted, winning_edit

### Step 3: Analyze Results

```bash
cat bench/results/spec-search-results-*.json | jq .
```

**Decision point:**
- If `best_accuracy >= 0.82` (Decision A bar): **SUCCESS** → wire result
- If `best_accuracy < 0.82`: Document plainly, no escalation

### Step 4: Wire Result (If Successful)

**Option A: Prompt/Engine Params**
```bash
# Edit judgment_spec.json with winning prompt/params
nano skills/paper-dive/config/judgment_spec.json

# Verify logic_auditor.py loads it
python -c "from skills.paper_dive.scripts.logic_auditor import _load_judgment_spec; print(_load_judgment_spec())"
```

**Option B: Model Change (if needed)**
```bash
# Update config/models.json via model_registry
# (See ADR 0085 — capabilities table)
```

### Step 5: Report Results

Edit `bench/RESULTS.md` Run 33 entry:
- Fill in accuracy table
- Update verdict (SUCCESS / INSUFFICIENT)
- Recommend next jobs if successful

Mark benchmark "spent":
```bash
# In the benchmark JSON, set "spent": true
# Document which benchmark was used for which run
```

---

## Troubleshooting

| Error | Solution |
|-------|----------|
| "Ollama server not responding" | Start: `ollama serve` |
| "Model 'qwen2.5:3b' not found" | Pull: `ollama pull qwen2.5:3b` |
| "paper-knowledge collection is empty" | Ingest papers via paper-dive first |
| "claude: command not found" | Ensure Claude CLI is in PATH |
| Teacher timeout (90s) | Retry after a few minutes (API may be loaded) |
| Benchmark crash on extraction | Specific paper may break extraction logic (skip + continue) |

---

## Key Design Principles

✅ **Outside pytest:** Avoids whole-suite 1200s timeout (Oct 23 regression fixed)  
✅ **Resident-only:** No re-downloading deleted models (ADR constraints respected)  
✅ **Reused patterns:** bench.py subprocess, chat_fn injection, frozen benchmarks  
✅ **Zero network in tests:** All mocked, testable offline  
✅ **Additive wiring:** logic_auditor.py still works without spec file  
✅ **Transparent results:** No hidden escalation, honest reporting of bar clearance  

---

## Next: Post-Manual Run

After executing all 5 steps:

1. **If successful (best_accuracy ≥ 0.82):**
   - Winning edit is wired to judgment_spec.json or config/models.json
   - Run 33 entry in RESULTS.md filled in with SUCCESS verdict
   - Recommend next jobs: triage classification + daily digest
   - Create follow-up tickets for those jobs

2. **If unsuccessful (best_accuracy < 0.82):**
   - Gap documented plainly in Run 33
   - No forced escalation
   - Consider: larger model, different approach, or scope reduction

3. **Regardless:**
   - Mark frozen benchmark "spent" in Run 33
   - Close ticket 675 with spike result + findings
   - Design doc + tests become reference for future iterations

---

## Support

- **Full design:** `docs/design/675-spec-search-paper-dive-judgment.md`
- **Detailed instructions:** `SPEC_SEARCH_MANUAL_RUN.md`
- **What's implemented:** `IMPLEMENTATION_SUMMARY_675.md`
- **Code patterns:** See bench.py, logic_auditor.py, holdout_fixture.py
- **Prior art:** OpenJarvis paper (arXiv 2605.17172)

---

**Implementation by:** Claude (Haiku 4.5)  
**Ready since:** 2026-11-23 22:30 UTC  
**Status:** ✅ All systems go for manual execution
