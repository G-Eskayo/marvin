## North-star fit

**Reuses before adding anything new:**
- `lib/error_log.py`'s `_append()` (flock + size/age-bounded rewrite-in-place) — the exact "rotation, like other MARVIN logs" idiom the ticket asks for, and `lib/error_log.py`'s `_machine()` (→ `machine_profile.registry_id()`) for the row's machine field.
- `lib/history_store.py` / ADR 0066 / ADR 0080's **outbox** convention: `bin/gh`'s `_log()`/`_append()` already do "JSONL file under `~/.claude/logs/`, rewritten in place past 5 MB" for `gh-calls.jsonl`. The new log is a sibling outbox (`model-calls.jsonl`), not a new kind of store — avoids the exact "two databases with the same table" duplication ADR 0080 was written to prevent.
- `lib/tests/test_north_stars.py::test_no_north_star_text_is_hardcoded_in_any_script`'s rglob-and-grep pattern — reused verbatim in shape for the "every call site goes through the wrapper" coverage test.
- `config/models.json` / `model_registry.resolve_capability()`'s existing per-file `MODEL` constant idiom (e.g. `CLASSIFY_MODEL = _classify_model_list[0]`) — a `NUM_CTX` constant goes right beside it, same pattern, nothing new invented.
- Every existing caller's own `ollama_chat()`/`embed_text()`/`embed()` function **keeps its name and signature** — only its body changes to call the new wrapper. No call site (`chat_fn = chat_fn or (lambda messages: ollama_chat(...))`, existing `monkeypatch.setattr(la, "ollama_chat", ...)` tests) needs to change.

**Simplest sufficient approach:** one module, two functions (`chat`, `embed`), both requiring `caller` and `num_ctx` as mandatory keyword args (no default — a missing one is a bug, not a style choice), a pre-flight char-count estimate that raises before sending (prevents the actual silent-truncation bug) and a post-hoc flag computed from Ollama's real `prompt_eval_count` (the 90% telemetry signal). No auto-trimming machinery inside the wrapper — "trimmed on purpose" means the caller trims its own content before calling; the wrapper only ever does one thing (raise loud) when told a request would exceed its window.

**Where it saves/spends tokens:** spends a small one-time refactor cost (10 files) to stop guesswork on every future local-model/long-context decision (sparse attention, Qwen3.5, vLLM) — exactly the "measure before optimising" leverage north star 1 asks for. Logging and the summary are O(1) per call and O(rows) to read; no new daemon, no new store.

**Phone-OS / capability-tiers direction:** `chat()`/`embed()` take a `base_url` parameter (default `http://localhost:11434`), per the ticket's own note that this should become the `/v1`-style client ADR 0085's local tier and the vLLM/exo research plan want — a multi-host future doesn't require touching call sites again.

**More capable or more passive?** This is pure plumbing/observability for Gil and MARVIN's own model-tier decisions — no end-user-facing behavior change, so the "more capable, not more passive" test doesn't apply to a human; it does make MARVIN's own future tiering decisions evidence-based instead of guessed, which is the point.

No north star argues against this work.

---

## Design

**`lib/model_calls.py`** (new):
- `PromptTooLargeError(RuntimeError)`, `OllamaUnavailableError(RuntimeError)`.
- `chat(model, messages, *, caller, num_ctx, base_url="http://localhost:11434", timeout=120, **options) -> dict` and `embed(model, input_text, *, caller, num_ctx, base_url=..., timeout=30) -> dict`. Both:
  1. Validate `messages`/`input_text` (non-empty, right type) — raise `ValueError`/`TypeError` immediately, never serialize garbage into `requests`.
  2. Pre-flight: estimate tokens (`len(text)//4` heuristic, documented as approximate) against `num_ctx`; raise `PromptTooLargeError` (naming `caller`, estimated tokens, `num_ctx`) before any network call if it would be silently cut.
  3. POST to `{base_url}/api/chat` or `/api/embed` with `options={"num_ctx": num_ctx, ...}`. Catch timeout/connection/JSON errors → log a `status="error"/"timeout"` row, raise `OllamaUnavailableError`.
  4. On success, read `prompt_eval_count`/`eval_count` if present else the string `"unknown"` (never `0`); compute `possibly_truncated = prompt_tokens/num_ctx >= 0.9` only when `prompt_tokens` is a real int.
  5. Always log one row (success or failure) via an internal `_append()` that mirrors `error_log.py`'s flock + bounded-rewrite shape, to `~/.claude/logs/model-calls.jsonl`. Logging itself never raises and never blocks the caller from getting its real result/exception (mirrors `error_log.py`'s "writers never raise").
  6. Return `{"content"|"embedding", "prompt_tokens", "eval_count", "load_duration_ms", "prompt_eval_duration_ms", "eval_duration_ms", "possibly_truncated"}`.
- `summary(days=7, caller=None, model=None, path=None) -> list[dict]` — reads the JSONL directly (no `marvin.db` dependency, so it's accurate immediately, not lagged behind the 5-minute loader), groups by `(caller, model)`, reports p50/p95/max over rows with a real `prompt_tokens` int, plus counts of `unknown` and `possibly_truncated` rows. `main()` CLI: `model_calls.py summary [--days N] [--caller X] [--model Y] [--json]`.

**Every direct call site migrates its existing helper's body** (name/signature unchanged) to call `model_calls.chat()`/`model_calls.embed()`, adding a module-level `CALLER` string and `NUM_CTX` constant beside its existing `MODEL` constant:

| File | Function kept as-is | 
|---|---|
| `skills/paper-dive/scripts/argument_mapper.py` | `ollama_chat()` |
| `skills/paper-dive/scripts/competing_ideas.py` | `ollama_chat()` |
| `skills/paper-dive/scripts/continuity_checker.py` | `ollama_chat()` |
| `skills/paper-dive/scripts/logic_auditor.py` | `ollama_chat()` |
| `skills/paper-dive/scripts/paper_graph.py` | `_real_nomic_embed()` (also drops the legacy `/api/embeddings` shape for `/api/embed`) |
| `lib/intent_classify.py` | `embed_text()` |
| `skills/self-improve/scripts/retrieve.py` | `embed_query()` |
| `skills/self-improve/scripts/rebuild-embeddings.py` | `embed()` |
| `bench/bench.py` | `run_once_ollama()`'s internal POST |
| `bench/lib/memory_rag.py` | replace `OllamaEmbeddingFunction` with a tiny custom `EmbeddingFunction` wrapping `model_calls.embed()` |

(`setup.sh`'s `curl http://localhost:11434/` is a plain health probe, not a chat/embed call — out of scope.)

**Judgment calls made, not asked as Decisions** (none met the bar for a genuine owner choice — each resolves from the ticket text or an existing ADR):
- Log lives at `~/.claude/logs/model-calls.jsonl` as a bounded JSONL outbox (ADR 0066/0080 pattern), not inside `marvin.db` — wiring it into `history_store.py`'s `DEFAULT_STREAMS` is a cheap, reversible later step, not needed for these acceptance criteria.
- `on_truncate` is raise-only; a caller that wants to "trim on purpose" trims before calling, per the ticket's own wording.
- Scope is Ollama (`/api/chat`, `/api/embed`) only, per the ticket's "(Ollama today)" — mlx/hf/flux stay out.
- Bench/harness call sites are included — the acceptance criterion says "every local call site" with no carve-out.

---

## Tests (written first)

Against a fake Ollama server / monkeypatched `requests`, never a mock that would hide Ollama's real response shape:

1. `chat()`/`embed()` raise `PromptTooLargeError` *before* any network call when the estimated prompt tokens exceed `num_ctx` — the core correctness bug, never silently sent.
2. A prompt just under the estimate threshold succeeds normally; one just at/over the threshold is rejected (boundary).
3. Omitting `caller` or `num_ctx` raises (`TypeError`/`ValueError`) — enforced in code, not just convention.
4. Ollama down (connection refused) and Ollama slow (times out): both return/raise a named `OllamaUnavailableError` within the configured timeout, never hang; both log a `status` row.
5. A response missing `prompt_eval_count`/`eval_count` (older server) logs `"unknown"` for those fields, never `0`.
6. `prompt_eval_count` at/above 90% of `num_ctx` → `possibly_truncated=True`; below 90% → `False`; `"unknown"` prompt_tokens → never flagged either way.
7. Malformed/non-JSON response body from the server is caught and treated as `status="error"`, not an uncaught exception type.
8. Bad/empty/huge/malformed input: empty `messages`/`input_text`, `None`, wrong type (bytes/dict/int) — rejected with a clear exception, never serialized and sent.
9. Concurrent callers (threads/subprocesses) appending at once: N calls produce exactly N well-formed JSON lines, never interleaved/corrupted.
10. Rotation at the size cap: writing past the bound trims to the newest rows without corrupting any remaining line, concurrently with another appender (combines with #9).
11. A failing/unwritable log destination (missing dir, no permission) never raises out of `chat()`/`embed()` and never blocks returning the real result or exception — logging failures are swallowed, the model call's own outcome is not.
12. Repeats: calling twice with identical args appends two independent rows (no accidental dedup hiding a retry storm).
13. `summary()` over a window with zero rows for a caller, and a window where every row is `"unknown"`: reports "no data"/excludes them rather than crashing or reporting fake zeros.
14. Coverage test (reusing `test_north_stars.py`'s rglob approach): no file outside `lib/model_calls.py` and its own tests contains `/api/chat`, `/api/embed`, `/api/embeddings`, or a bare `localhost:11434`/`127.0.0.1:11434` string.
15. Each migrated caller's existing test suite (incl. `test_logic_auditor.py`'s `ollama_chat` monkeypatches) still passes unchanged — behavior-preserving refactor, not a rewrite.
16. A caller that currently catches "any failure → return `None`" (e.g. `embed_text`) still does so for `OllamaUnavailableError`, but a `PromptTooLargeError` is **not** swallowed into that same generic path — verified explicitly, since that would recreate the exact "silent" failure the ticket exists to kill.

---

## Task List

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