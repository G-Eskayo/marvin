1. [ ] `lib/tests/test_model_calls.py` — wrapper tests #1–12 above, against a fake server.
2. [ ] `lib/tests/test_model_calls_summary.py` — tests #13 plus normal percentile output.
3. [ ] `lib/tests/test_model_calls_coverage.py` — the repo-wide grep test (#14).
4. [ ] Build `lib/model_calls.py`: exceptions, `chat()`, `embed()`, the flock+rotate JSONL logger, pre-flight guard, post-hoc flag, `summary()` + CLI.
5. [ ] Migrate the four paper-dive `ollama_chat()` bodies to call `model_calls.chat()`; add `CALLER`/`NUM_CTX` constants; confirm `test_logic_auditor.py` unchanged.
6. [ ] Migrate `paper_graph.py`'s `_real_nomic_embed()` to `model_calls.embed()`, dropping the legacy `/api/embeddings` shape.
7. [ ] Migrate `intent_classify.py`'s `embed_text()`, `retrieve.py`'s `embed_query()`, `rebuild-embeddings.py`'s `embed()` — preserve each function's `None`-on-unavailable contract, let `PromptTooLargeError` propagate distinctly (test #16).
8. [ ] Migrate `bench/bench.py`'s `run_once_ollama()` to call `model_calls.chat()`, keeping its own token-count-based scoring fields.
9. [ ] Replace `bench/lib/memory_rag.py`'s `OllamaEmbeddingFunction` with a small custom `EmbeddingFunction` calling `model_calls.embed()`.
10. [ ] Size and set each file's new `NUM_CTX` constant from its real prompt template + expected output length, rounded up to an Ollama-supported context size.
11. [ ] Run every touched file's full existing test suite — no regression, main stays green.
12. [ ] Write ADR 0086 (one wrapper for local model calls: explicit `num_ctx`, no silent truncation, `model-calls.jsonl` outbox), linking ADR 0066, 0080, 0085.
13. [ ] Open the PR naming #1210, `marvin-show` the `model_calls.py summary` output.