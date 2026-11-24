# Manual Execution Guide: Paper-Dive Judgment Spec Search (Ticket 675)

This spike runs outside pytest to avoid the 1200s timeout that plagued prior attempts.

## Prerequisites

1. **Ollama running** with `qwen2.5:3b` pulled:
   ```bash
   ollama serve  # In one terminal
   ollama pull qwen2.5:3b  # Verify it's available
   ```

2. **Claude CLI available**:
   ```bash
   which claude  # Should exist and work
   claude --version
   ```

3. **ChromaDB with paper-knowledge collection**:
   - Requires at least some papers ingested via paper-dive
   - If empty, the benchmark build will warn and produce empty results

4. **Virtual environment active**:
   ```bash
   source ~/.agents/venv/bin/activate
   ```

## Step 1: Build the Frozen Benchmark

This pulls abstracts from `paper-knowledge`, classifies and extracts with qwen2.5:3b,
then labels with Claude (teacher). Writes a dated JSON file.

```bash
cd /path/to/this/worktree
~/.agents/venv/bin/python bench/benchmark_from_chroma.py \
    --sample-count 50 \
    --out bench/benchmarks/paper-dive-judgment-$(date +%Y%m%d-%H%M%S).json
```

**Expected output:**
- Benchmark JSON file: `bench/benchmarks/paper-dive-judgment-*.json`
- Each sample: `{slug, title, abstract, extraction, paper_type, claude_label, status}`
- cost_estimate: Total teacher cost (~$0.50 for 50 samples)
- Takes ~5-15 min (one Claude call per sample)

**What to verify:**
- sample_count matches expected number of papers
- Each sample has status="ok" (or ERROR/TIMEOUT for failures)
- claude_labels are valid JSON objects

## Step 2: Run the Spec Search

Measures baseline accuracy, proposes one edit per round, re-measures, keeps only
non-regressions. Stops on max_rounds or N consecutive non-improving rounds.

```bash
~/.agents/venv/bin/python bench/spec_search.py \
    --benchmark bench/benchmarks/paper-dive-judgment-*.json \
    --max-rounds 10 \
    --out bench/results/spec-search-results-$(date +%Y%m%d-%H%M%S).json
```

**Expected output:**
- Results JSON: baseline_accuracy, best_accuracy, edits_proposed, edits_accepted
- Logs to stderr showing each round

**Decision bar (from ticket):**
- If `best_accuracy >= 0.82` (within ~3.2 points of Claude): SUCCESS
- If lower: document the gap and don't force escalation

## Step 3: Analyze Results

```bash
cat bench/results/spec-search-results-*.json | jq .
```

Key metrics:
- `baseline_accuracy`: Starting point with qwen2.5:3b
- `best_accuracy`: After spec search tuning
- `edits_accepted`: How many edits helped
- `best_edit`: Description of the winning edit

## Step 4: If Successful, Wire the Result

If accuracy clears the bar, integrate the winning edit:

### Option A: Prompt/Engine Params
Write `skills/paper-dive/config/judgment_spec.json`:
```json
{
  "judge_extraction_prompt_override": "...",
  "judge_extraction_params": {"temperature": 0.5, "num_ctx": 2048}
}
```

Modify `logic_auditor.py` to load it (small additive change):
```python
def _load_judgment_spec():
    spec_path = Path(__file__).parent / "config" / "judgment_spec.json"
    if spec_path.exists():
        return json.loads(spec_path.read_text())
    return {}

# In judge_extraction():
spec = _load_judgment_spec()
if "judge_extraction_prompt_override" in spec:
    _JUDGMENT_PROMPTS[paper_type] = spec["judge_extraction_prompt_override"]
```

### Option B: Model Change
If the winning edit is to swap models, update `config/models.json` via model_registry:
```python
model_registry.register(
    name="new-model:latest",
    location="~/.ollama/models",
    size_gb=X,
    used_by="paper-dive",
    reason="spec search tuning (ticket 675)",
)
# Then update "local-judge-medium" capability to use it
```

## Step 5: Report Results

Append a new "Run N" entry to `bench/RESULTS.md`:

```markdown
## Run 33 — 2026-11-23 (ticket #675: spec search tuning)

Paper-dive judgment: tune qwen2.5:3b with Claude-as-teacher spec search.

### Setup
- Frozen benchmark: 50 samples from paper-knowledge
- Student: qwen2.5:3b (resident, no re-download)
- Teacher: Claude (one-time labeling, ~$0.50)
- Search: prompt tweaks + engine params, max 10 rounds

### Results

| Metric | Value |
|--------|-------|
| Baseline accuracy | 0.80 |
| Best accuracy | 0.84 |
| Edits proposed | 10 |
| Edits accepted | 3 |
| Winning edit | "simplify warrant check" |
| Local cost | $0.00 (ongoing) |
| Teacher cost | ~$0.50 (one-time) |

**Conclusion:** Accuracy cleared the ~3.2-point bar. Local setup works for paper-dive
judgment without ongoing Claude costs.

**Spent benchmarks:** paper-dive-judgment-20261123-*.json
(Do not use for tuning again; rebuild if further iterations needed.)

### Recommended next jobs
- Triage classification: classify papers by use case (architecture, security, ML, etc.)
- Daily digest: auto-summarize new papers using same spec-search approach

---
```

## Troubleshooting

**"Ollama server not responding"**
- Start ollama: `ollama serve`
- Verify model: `ollama list | grep qwen2.5:3b`

**"claude: command not found"**
- Claude CLI must be in PATH
- Check: `which claude`

**"paper-knowledge collection is empty"**
- Ingest papers first via paper-dive skill
- Or reduce sample_count to match available papers

**"Teacher call timed out"**
- Claude session may be overloaded
- Retry after a few minutes

**Benchmark measurements crash**
- Check error logs for specific judge_extraction failures
- May indicate a paper that breaks the extraction logic

---

## Notes

- **No real network calls in tests**: test_spec_search.py mocks all Claude/Ollama calls
- **Search runs outside pytest**: avoids whole-suite timeout
- **Frozen benchmarks are "spent"**: mark as spent after tuning uses them (don't reuse)
- **Cost is front-loaded**: teacher labels are one-time; student evaluation is free
