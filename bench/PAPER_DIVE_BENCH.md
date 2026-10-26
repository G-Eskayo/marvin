# Paper-Dive Student Model Benchmark

## Overview

This benchmark evaluates and optimizes paper-dive's student model (`qwen2.5:3b`) performance on two key tasks:
1. **Layer 1: Judgment** — detecting argument validity issues in paper extractions
2. **Layer 2: Inference** — checking whether conclusions follow from premises

The optimization uses **spec-search**: iteratively propose prompt edits, score against a frozen benchmark, accept only edits that don't regress any sample.

## Architecture

### Components

- **`lib/benchmark_loader.py`** — Loads seed papers from `paper-knowledge` ChromaDB collection, filters out empty abstracts
- **`lib/spec_search.py`** — Generic spec-search engine: propose-score-accept loop with regression checking
- **`paper_dive_benchmark.py`** — Main driver orchestrating steps 1-3 (freezing, labeling, scoring)

### Data Flow

```
ChromaDB papers
    ↓
[Benchmark Loader]
    ↓
Frozen benchmark samples
    ↓
[Teacher (Claude) labels] → frozen_labels.json
    ↓
[Student (Ollama) scores] → student_scores.json
    ↓
[Spec-Search loop] → optimized prompts
    ↓
[Results in RESULTS.md]
```

## Running the Benchmark

### Step 1: Freeze the Benchmark

Generates teacher (Claude) gold labels for layer1 and layer2:

```bash
~/.agents/venv/bin/python bench/paper_dive_benchmark.py --freeze
```

This:
- Loads papers from `~/.claude/chroma/paper-knowledge` collection
- Classifies each paper's type (empirical/survey/benchmark/conceptual)
- Extracts structure (CLAIM/GROUNDS/WARRANT/etc per type)
- Judges extractions for validity issues
- Checks inference validity (deductive/inductive reasoning)
- Saves ground truth to `bench/benchmark_data/frozen_labels.json`

**Decision point:** `label-check`. Before running the optimization, Gil should spot-check a sample of the generated labels to ensure they're accurate. The labels become the ground truth for scoring, so bad labels → bad optimization.

### Step 2: Score Untuned Student

Scores `qwen2.5:3b` (the untuned baseline) against the frozen benchmark:

```bash
~/.agents/venv/bin/python bench/paper_dive_benchmark.py --score
```

This:
- Loads frozen labels from `frozen_labels.json`
- Scores student model on each sample (0.0–1.0 scale)
- Computes accuracy as mean score across all samples
- Saves baseline scores to `bench/benchmark_data/student_scores.json`

Output shows per-sample breakdown and overall accuracy.

### Step 3: Spec-Search (Optimization)

Run optimization on the frozen benchmark:

```bash
# (Implementation in progress — currently a placeholder)
# Once implemented, this will:
# 1. Load frozen labels
# 2. Load spec_search engine
# 3. Run teacher-proposes-edit / student-scores / accept-if-no-regression loop
# 4. Record each round in memory
# 5. Output final accuracy, Claude-call cost, and wall-clock time
```

## Test Coverage

All new modules have unit tests:

```bash
# Test benchmark loader
~/.agents/venv/bin/python -m pytest bench/lib/tests/test_benchmark_loader.py -v

# Test spec-search engine
~/.agents/venv/bin/python -m pytest bench/lib/tests/test_spec_search.py -v
```

Tests cover:
- **Loader:** missing files, empty collections, missing abstracts, metadata fallback
- **Spec-Search:** empty samples, failed callbacks, no-op termination, regression detection, repeated rejection

## Data Files

```
bench/benchmark_data/
  frozen_labels.json        # Ground truth: {slug: {paper_type, findings, layer2}}
  student_scores.json       # Baseline: {slug: score}
  student_optimized.json    # (future) After spec-search
```

## Decisions & Dependencies

### Decisions

1. **`label-check`**: Should Gil spot-check frozen labels before optimization?
   - [ ] A: Spot-check a sample before proceeding
   - [ ] B: Trust Claude's labels outright

2. **`repull`**: Re-pull deleted model sizes for historical baseline?
   - [ ] A: Re-pull qwen2.5:7b/14b (13.7 GB), measure, delete again
   - [ ] B: Skip — compare only Claude vs. untuned-3b vs. optimized-3b

### Dependencies

- **ChromaDB:** `~/.claude/chroma/paper-knowledge` collection must exist with abstracts
- **Ollama:** Local models `qwen2.5:3b`, `qwen2.5:7b`, `qwen2.5:14b` (or symbolic links via `config/models.json`)
- **Claude API:** For teacher labeling and proposal generation

## Results Recording

Results are appended to `RESULTS.md` as a new Run-N entry with:

| Variant | Accuracy | Claude Calls | Cost (USD) | Tokens | Wall Time (s) |
|---------|----------|--------------|-----------|--------|---------------|
| Claude baseline (current) | — | — | — | — | — |
| Untuned student | X% | 0 | $0 | 0 | — |
| Optimized student | Y% | N | $Z | K | T |
| Historical 7b baseline | — | 0 | $0 | 0 | — |
| Historical 14b baseline | — | 0 | $0 | 0 | — |

Plus:
- Spec-search round history (proposal, accepted, accuracy deltas, regressions)
- Recommendation: "Adopt" / "Don't adopt" / "Conditional" with rationale
- List of next optimization candidates (triage, daily digest)

## Known Limitations

1. **Scoring formula:** Currently counts finding-match + reasoning-match. Could be more sophisticated (e.g., semantic similarity, LLM judge).
2. **Teacher labels:** Ground truth only as good as Claude's accuracy on these tasks.
3. **Student model fixed:** Only optimizing prompts, not the model itself (per task spec).
4. **No cross-validation:** Frozen benchmark is fixed; all optimization is against the same set (potential overfitting to this snapshot).

## Future Work

1. **Separate holdout set** for true generalization measurement
2. **LLM judge** for more nuanced correctness scoring (current is binary/threshold)
3. **Spec-search on other tasks:** Triage classification, daily digest (mentioned in ticket)
4. **Threshold calibration:** `calibrate.py`-style learned thresholds instead of hand-picked
5. **Multi-axis search:** Edit model/tools/settings, not just prompts (deferred per task scope)
