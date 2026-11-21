# ADR 0086: Unified wrapper for local Ollama model calls

**Status:** Accepted (2026-11-18)

**Context:**

Every call to Ollama's `/api/chat` and `/api/embed` endpoints was previously made directly by individual caller modules (paper-dive tools, intent classifier, embeddings rebuilder, bench harness). This pattern caused four problems:

1. **Silent truncation:** Callers made no estimate of prompt token count before sending, so Ollama would silently truncate at context-window boundaries without signaling that the prompt exceeded the available space. This produced silent correctness failures (ADR 0066 and 0085 track the broader impact).

2. **No observability:** Every call was made independently with no unified logging or telemetry. Understanding which callers hit context limits, which models were used, and overall call patterns required reading code or instrumenting each call site.

3. **Inconsistent error handling:** Network failures (timeouts, connection refused) were handled differently per caller — some returned `None`, some raised, some silently failed and printed a warning.

4. **Duplicate token-counting heuristics:** Multiple files independently guessed token counts; no shared infrastructure for the common task of "estimate whether this text fits in the context window."

**Decision:**

Introduce `lib/model_calls.py` as a single point of entry for all local Ollama model calls:

1. **Two functions:** `chat(model, messages, *, caller, num_ctx, ...)` and `embed(model, input_text, *, caller, num_ctx, ...)`.
   - Both require explicit `caller` and `num_ctx` keyword arguments (no defaults; a missing one is a bug).
   - Both apply a pre-flight token-count estimate before any network call.
   - If estimated tokens would exceed 90% of `num_ctx`, raise `PromptTooLargeError` immediately (never silently truncate).

2. **Outbox logging:** Every call—success or failure—logs one JSON line to `~/.claude/logs/model-calls.jsonl`, following ADR 0066/0080's bounded outbox pattern:
   - Flock-protected append for concurrent safety.
   - Rotation at 2000 lines × 1.25 boundary to keep the file bounded.
   - Logging failures are swallowed; the caller's result or exception is never blocked.
   - Logged fields: `timestamp`, `machine`, `caller`, `model`, `prompt_tokens`, `eval_count`, `possibly_truncated` (True if prompt was ≥90% of `num_ctx`), `status` (success/error/timeout).

3. **Post-hoc truncation flag:** Ollama's real `prompt_eval_count` (if present) is logged and compared against `num_ctx`. If `prompt_tokens / num_ctx >= 0.9`, the row's `possibly_truncated` flag is set to `True` for auditing (the actual truncation detection, not an estimate).

4. **Future-proofing via `base_url`:** Both functions accept a `base_url` parameter (default `http://localhost:11434`), enabling future migration to multi-host setups (vLLM, exo, or cloud inference) without touching call sites. This unblocks the Phone-OS capability-tier direction (ADR 0085's local tier).

**Migration:**

All direct Ollama calls were migrated to use the wrapper:
- **Paper-dive tools:** `logic_auditor.py`, `argument_mapper.py`, `continuity_checker.py`, `competing_ideas.py`, and `paper_graph.py` all updated. Existing `ollama_chat()` function names preserved; only bodies changed.
- **Embedding callers:** `intent_classify.py` (`embed_text()`), `retrieve.py` (`embed_query()`), `rebuild-embeddings.py` (`embed()`), and `bench/lib/memory_rag.py` (custom `EmbeddingFunction` for ChromaDB).
- **Bench harness:** `bench/bench.py`'s `run_once_ollama()` refactored to use `model_calls.chat()`.

Each caller's existing test suite passes unchanged—this is a behavior-preserving refactor of the network call, not a rewrite of the caller's logic.

Each migrated module added two constants:
- `CALLER`: string identifier for the calling module (e.g., "logic_auditor", "retrieve").
- `NUM_CTX`: integer context size in tokens, sized for the caller's prompt templates + expected output length, rounded up to Ollama's supported context window (4096, 8192, 32768, etc.).

**Rationale:**

- **Pre-flight guard prevents the silent failure.** ADR 0085 required "measure before optimizing"; this provides the measurement.
- **Outbox pattern reuses existing infrastructure** (ADR 0066, 0080) instead of inventing a new log store.
- **Explicit `num_ctx` per caller** forces accurate sizing decisions upfront, eliminating guesswork and enabling evidence-based tiering decisions.
- **Mandatory keyword args** (`caller`, `num_ctx`) catch missing configuration at the call site, not via later assertion failure.
- **Custom embedding function in `memory_rag.py`** decouples from ChromaDB's built-in `OllamaEmbeddingFunction`, which had its own disconnected Ollama setup.

**Consequences:**

- Every local model call now logs to the unified `~/.claude/logs/model-calls.jsonl` outbox.
- The `model_calls.summary()` CLI tool and function (see `lib/model_calls.py main()`) can report p50/p95/max prompt tokens, error counts, and truncation flags per caller+model pair.
- Future work (ADR 0087+) can consume this log for observability (dashboard widgets, alerts, model-tier routing decisions).
- `PromptTooLargeError` is never silently swallowed by callers that return `None` on unavailability—it propagates distinctly (enforced by test #16 in `lib/tests/test_model_calls.py`), so the distinction between "Ollama is down" and "your prompt doesn't fit" is preserved.

**Related ADRs:**

- ADR 0066: Outbox pattern for bounded JSON logs (error_log.py).
- ADR 0080: History store and outbox convention (generalizes 0066 beyond errors).
- ADR 0085: Local-tier capability classification for Phone-OS (future work; this unblocks it via `base_url` param).
- ADR 0023: Routing threshold calibration (uses evidence from this log for future threshold decisions).

**Testing:**

- `lib/tests/test_model_calls.py`: 34 tests covering pre-flight guard, timeout handling, bad input validation, logging, concurrency, non-dict response handling, embeddings validation, and duration field extraction.
- `lib/tests/test_model_calls_summary.py`: 6 tests for the summary() function.
- `lib/tests/test_model_calls_coverage.py`: Repo-wide grep test ensuring no call sites contain bare `/api/chat`, `/api/embed`, or `localhost:11434` strings outside the wrapper.
- Existing test suites for migrated modules (e.g., `test_logic_auditor.py`, `test_intent_classify.py`) pass unchanged.
