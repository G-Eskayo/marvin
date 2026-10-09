# ADR 0065: Local Model Visibility and Metrics

**Status:** Accepted  
**Date:** 2026-10-09  
**Context:** G-Eskayo/marvin#[ticket-number]

## Problem

MARVIN's use of local models (Ollama/MLX for paper-dive synthesis, intent routing, retrieval) lacks visibility into whether inference is actually using the GPU or falling back to CPU. This is a critical gap for:

1. **Development decisions:** Is Ollama on this Mac actually accelerated, or just CPU-bound?
2. **Model selection:** Should we prefer MLX (Apple Silicon native) over Ollama for certain tasks?
3. **Performance tuning:** Which models benefit from GPU, and which should stay small for CPU?
4. **Resource planning:** Are we thrashing between GPU and CPU fallback under concurrent load?

Without ground truth on GPU vs CPU split, we cannot reliably benchmark local inference or make data-driven decisions about model deployment.

## Context

- **Existing infrastructure:** `model_registry.py` already tracks each model's `runtime` (ollama/mlx) and `heavy` flag; `metrics_registry.py` (ADR 0048) provides per-machine JSON snapshots and cross-machine aggregation.
- **Prior duplication:** Six scripts (`logic_auditor.py`, `continuity_checker.py`, `argument_mapper.py`, `competing_ideas.py`, `intent_classify.py`, `retrieve.py`) each implemented their own `ollama_chat()` or `/api/embed` calls, preventing a single instrumentation point.
- **Benchmark harness:** `bench.py` already compares Ollama vs Claude profiles; MLX comparison is missing.
- **Model queue:** `model_queue.py` exists as a "one heavy model at a time" mechanism but is currently a non-blocking stub.

## Decision

Implement unified local model visibility by:

1. **Consolidate Ollama API calls** via a new `lib/ollama_client.py` module:
   - Wraps `/api/chat` and `/api/embed` with automatic GPU/CPU split tracking.
   - After each call, queries `/api/ps` to determine `size_vram` vs total `size`, computes CPU fallback fraction, and records to `metrics_registry` under `local-model-runs-{model_name}`.
   - Silent degradation: if Ollama unreachable or model already unloaded, recording is skipped but the call succeeds.
   - Fcntl-locked writes prevent concurrent corruption.

2. **Migrate existing scripts** to use the new client:
   - Four paper-dive synthesis tools (`logic_auditor.py`, `continuity_checker.py`, `argument_mapper.py`, `competing_ideas.py`)
   - Intent router (`intent_classify.py`)
   - Retrieval (`retrieve.py`)
   - All call sites replaced; duplication eliminated.

3. **Add MLX benchmarking** to `bench.py`:
   - New `run_once_mlx()` function (parallel to `run_once_ollama()`) using `mlx_lm.generate()` for open-ended text inference.
   - Supports ≥3 repeats per task for statistically reliable comparison.
   - Automatically records GPU/CPU split to `metrics_registry` via the unified client.

4. **Dashboard metrics display** (AC #2):
   - No new IPC plumbing; `metrics:subsystems` and `metrics:history` already expose this.
   - Add `MetricsPage.jsx` section rendering `local-model-runs-*` subsystems per machine.
   - Visual flag for any snapshot with `cpu_fallback.value === 1.0` (100% CPU, no GPU acceleration).

5. **Benchmark comparison** (AC #3):
   - Run both `qwen2.5:14b` and `qwen2.5:7b` under Ollama ≥3× per task.
   - Download and register MLX-quantized equivalents; run MLX side ≥3× per task.
   - Use isolated `judge_run()` (pinned to `clean` profile, zero tools) to grade semantic correctness.
   - Record metrics to shared `ollama-vs-mlx` subsystem per machine; `compare()` to generate verdict.

6. **Model queue evaluation** (AC #4):
   - Small measurement script tests overlap behavior under current non-blocking `model_queue.acquire()` stub.
   - Load heaviest model under candidate `keep_alive`/resident settings on both machines.
   - Observe real RAM headroom (not declared `size_gb` sum) and measure concurrent call contention.
   - Document findings (no ADR change unless stub behavior becomes a blocker).

## Consequences

### Positive

- **Ground truth on GPU usage:** Every local inference call is now tagged with actual GPU/CPU split, visible in the dashboard's metrics timeline.
- **Composability:** Six duplicate `ollama_chat()` implementations become one shared client. Future tools using Ollama automatically inherit metrics recording without additional work.
- **Data-driven model selection:** Benchmark results directly show Ollama vs MLX vs Claude tradeoffs (latency, correctness, GPU utilization) on real tasks.
- **Concurrent load testing:** AC #4's measurements reveal whether the non-blocking queue stub is sufficient or if real blocking/queueing is needed.
- **Maintainability:** Single instrumentation point reduces future debugging surface.

### Negative

- **MLX model downloads:** Requires pulling MLX-quantized builds (1.6–2 GB per model) if not already cached.
- **Ollama uptime dependency:** Metrics recording requires `/api/ps` reachable; if Ollama crashes mid-run, that call's GPU split is lost (but the call still succeeds).
- **Dashboard complexity:** New metrics subsystem adds a row to the metrics page. Complexity is small (reuses existing `MetricsScorecard.jsx`) but visible.

### Trade-offs

- **Simplicity vs Completeness:** Collecting GPU split on *every* call (not just benchmarks) means all production paper-dive runs contribute to the timeline. This is noisy but valuable for spotting unexpected fallbacks. Filtering to benchmark-only runs would require a flag per call site.
- **Local storage vs Cross-machine aggregation:** Metrics files are per-machine (`{subsystem}.{machine}.json`), mirroring `model_registry.py`'s convention. This prevents accidental merging of Mini and MacBook stats, but requires the dashboard to explicitly choose "show this machine only" or aggregate.

## Measurement Results

### Ollama vs MLX Benchmark (AC #3)

Run on [machine], [date]:

| Model | Runner | Avg Latency (s) | GPU Fraction | Correctness | Judge Pass |
|-------|--------|-----------------|--------------|------------|-----------|
| qwen2.5:14b | Ollama | [measured] | [measured] | [measured] | [measured] |
| qwen2.5:7b | Ollama | [measured] | [measured] | [measured] | [measured] |
| qwen2.5:14b-mlx | MLX | [measured] | [measured] | [measured] | [measured] |
| qwen2.5:7b-mlx | MLX | [measured] | [measured] | [measured] | [measured] |

**Verdict:** [Decision based on latency, correctness, GPU utilization tradeoffs]

### Model Queue Evaluation (AC #4)

[Measurement script results documenting whether current non-blocking stub is sufficient]

## Implementation Notes

- **No new API contracts:** `model_registry.py` and `metrics_registry.py` unchanged; `ollama_client.py` is a pure consumer.
- **Timeout handling:** `ollama_client` uses 60s for chat, 10s for embed (defensive against stale Ollama sessions).
- **Error resilience:** Recording failures are silent; benchmark scores are never affected by metrics failures.
- **Testing:** 15 unit tests cover edge cases: Ollama unreachable, model not in `/api/ps`, CPU fraction division by zero, concurrent writes, corrupted JSON, large history, and more.

## References

- Prior art: `bench.py`'s `run_once_ollama()` established the pattern for Ollama integration (Run 3–14).
- Related: ADR 0048 (`metrics_registry.py`), ADR 0006 (model capabilities), image-maker-general-2026-10-08.md (16 GB Mac GPU queue).
- Blocking: ADR 0052 (parallel ticket dispatch) — this work unblocks GPU visibility for that system's scheduling decisions.
