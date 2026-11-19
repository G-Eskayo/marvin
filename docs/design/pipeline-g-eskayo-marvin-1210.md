## North-star fit

**Reuses before adding anything new:**
- `lib/error_log.py:_append` — the flock + `"a+"` + read + conditional trim + truncate + rewrite pattern (marvin#422, "errors are never silent") is the closest existing precedent for "a log that can't grow without bound" under concurrent writers. I'll mirror its structure (`MAX_LINES`/`MAX_AGE_DAYS` dual bound, lock held across the whole read-trim-rewrite) instead of `bin/gh`'s lockless half-truncate (`_log`/`_append` in `bin/gh:203-224`), which isn't safe against the concurrency case this ticket explicitly tests.
- `lib/error_log.py:_machine()` (and `lib/history_store.py`'s identical inline pattern) for the "machine" field — `machine_profile.registry_id()` with a `socket.gethostname()` fallback, duplicated inline per existing convention rather than introducing a shared helper for a 3-line snippet.
- `lib/tests/test_health_merge_service.py`'s `webhook` fixture (real `http.server.HTTPServer` on `127.0.0.1:0`, threaded, `daemon=True`) — the existing "fake server, not a mock, because a mock could hide the real collaborator's rules" pattern. Reused directly for the Ollama-down/slow/malformed-response tests instead of just monkeypatching `requests.post` (which the current `intent_classify.py` tests do, but that doesn't exercise real socket/timeout behavior).
- `skills/self-improve/scripts/rebuild-embeddings.py`'s already-documented fact that `nomic-embed-text`'s context is ~2048 tokens ≈ 4000 chars — reused as the embed-call `num_ctx` default and as the basis for the wrapper's cheap token estimator (chars ÷ 1.953), rather than inventing a new ratio or pulling in a tokenizer dependency.
- The four paper-dive scripts' existing `chat_fn=None` dependency-injection seam (`argument_mapper.py`, `continuity_checker.py`, `competing_ideas.py`, `logic_auditor.py`) — each already isolates its one `ollama_chat()` call behind a seam every test already injects around. Swapping each file's private `ollama_chat()` body to delegate to the new wrapper needs zero test changes in 3 of the 4 files' suites (`test_logic_auditor.py` patches `la.ollama_chat` wholesale, which still works).
- `lib/tests/conftest.py`'s `_isolate_error_log`/`_isolate_github_usage` autouse-fixture convention — adding a sibling `_isolate_model_calls_log` fixture rather than a bespoke isolation mechanism.

**Why this is the simplest sufficient approach:** one new module (`lib/model_calls.py`) that every existing local caller routes through, built entirely from patterns already in the repo. No new dependency (no tokenizer library, no numpy for percentiles — plain `sorted()` indexing, matching how the rest of `lib/` avoids heavy deps for small jobs).

**Tokens/resources:** this is pure plumbing — it doesn't call any paid model. It spends a little local compute per call (one `len()`-based estimate, one JSON-line append under an flock) in exchange for removing today's silent-truncation correctness bug and giving every future context-window decision (sparse attention, Qwen3.5, vLLM) real data instead of guesswork — directly serves north star 1.

**Phone-OS direction:** neutral/positive — makes every local-model caller observable and uniform, which any future caller (including a Mobile-reachable one) can rely on without re-deriving Ollama error handling.

**More capable or more passive:** more capable — nothing here replaces human judgment; it removes a hazard (silent truncation) and produces the measurement Gil needs to decide the long-context question himself in 7 days, per the ticket's own "Decide from the data" section.

**Machine:** library code, runs wherever the caller runs (Mini or laptop) — the module reads `machine_profile.registry_id()` per call so one shared log format works on both.

---

## Scope found by reading every call site

Caller sites making raw Ollama HTTP calls today (all other `ollama`-mentioning files only reference it in comments/disk accounting, not calls):

| File | Call | Endpoint |
|---|---|---|
| `lib/intent_classify.py:260` `embed_text()` | `requests.post` | `/api/embed` |
| `skills/self-improve/scripts/retrieve.py:51` `embed_query()` | `requests.post` | `/api/embed` |
| `skills/self-improve/scripts/rebuild-embeddings.py:52` `embed()` | `requests.post` | `/api/embed` |
| `skills/paper-dive/scripts/paper_graph.py:209` `_real_nomic_embed()` | `requests.post` | `/api/embeddings` (deprecated singular form; migrating folds it into `/api/embed`) |
| `skills/paper-dive/scripts/logic_auditor.py:42` `ollama_chat()` | `urllib.request` | `/api/chat` |
| `skills/paper-dive/scripts/argument_mapper.py:48` `ollama_chat()` | `urllib.request` | `/api/chat` |
| `skills/paper-dive/scripts/continuity_checker.py:34` `ollama_chat()` | `urllib.request` | `/api/chat` |
| `skills/paper-dive/scripts/competing_ideas.py:42` `ollama_chat()` | `urllib.request` | `/api/chat` |

`bench/bench.py`, `bench/select_model.py`, `bench/lib/memory_rag.py` also call Ollama directly, but as a **benchmark harness measuring raw model behavior** (including, in `bench.py`'s `profile=marvin, context_mode=full` path, prompts deliberately sized near Ollama's default 4096-token window) — routing them through an enforcing wrapper would change what they measure. Flagged as a Decision below rather than silently excluded.

No prior PR exists for marvin#1210 (`gh pr list` found nothing) and the one issue comment is a generic "verification failed after 3 iterations" retry note with no specific must-fix detail recoverable — there's nothing from a prior attempt to incorporate beyond building this carefully the first time.

## Decisions
<!-- marvin:decisions -->
### bench-scope: Should bench/'s raw Ollama calls stay outside the wrapper's coverage guarantee?
- [ ] A: Exclude `bench/` (bench.py, select_model.py, lib/memory_rag.py) from the wrapper and from the "every call site" grep test's allowlist — it's deliberately unwrapped to measure real model behavior near/at default context limits, which is itself useful data for this ticket's "decide from the data" question.
- [ ] B: Include `bench/` too — lose the raw-baseline measurement and gain full consistency (every local call logged and bounded the same way, no exceptions to reason about).

---

## Tests to write first

From the ticket's "How we'll try to break it" plus the misuse categories the ticket's list didn't cover (bad/empty/huge/malformed input, dependency failure modes beyond "down", wrong-order/stale-state, a person's mistakes):

1. **Ollama down** — `chat()`/`embed()` against a closed port (reuse `closed_port()` helper from `test_health_merge_service.py`) times out within the given timeout and raises a clear `ModelCallError`, and the call never hangs past the timeout.
2. **Ollama slow** — fake HTTPServer that sleeps past the configured timeout; same as above, never hangs the caller.
3. **Response missing token counts** (older server) — fake server returns `{"message": {...}}` with no `prompt_eval_count`/`eval_count`/duration fields; the logged row records `"unknown"` for those fields, never `0`.
4. **Concurrent callers writing the log** — N threads (and, separately, N subprocesses) calling `model_calls.chat`/`embed` against a fake server simultaneously; afterward every row is present, every line is valid JSON (no interleaved/corrupted lines), and the count matches N.
5. **Prompt longer than `num_ctx`, `on_overflow="raise"`** — fake server asserts it receives **zero** requests; caller gets a clear `PromptTooLong` exception naming the estimated size and the limit.
6. **Prompt longer than `num_ctx`, `on_overflow="trim"`** — fake server receives a request whose content was trimmed to fit, and the logged row is flagged (not a silent cut).
7. **`num_ctx` always sent explicitly** — fake server inspects the request body and asserts `options.num_ctx` matches what was passed, even when the caller didn't think about it (i.e., there is no path that omits it).
8. **"Possibly truncated" flag at the 90% boundary** — fake server returns `prompt_eval_count` at exactly 90%, just under, and just over `num_ctx`; row is flagged only at/above 90%.
9. **Every local call site goes through the wrapper** — a test that greps the repo (outside `lib/model_calls.py` itself, and outside whatever the bench-scope decision excludes) for `11434`, `/api/chat`, `/api/embed`, `/api/embeddings`, `/api/generate` and asserts no matches remain, run against the *post-migration* tree, not just a specification of intended behavior.
10. **Rotation / unbounded growth** — write past the line/age bound and assert the file shrinks to the newer rows and stays valid JSONL (mirrors `lib/tests/test_error_log.py`'s pattern for `error_log.py`'s identical bound, if that test file exists — check and mirror its structure).
11. **Summary percentiles** — seed a fake log with known `prompt_tokens` values per (caller, model) and assert `summary()`'s p50/p95/max match a hand-computed answer; separately, an empty/missing log returns empty stats rather than crashing.
12. **Malformed server response** — fake server returns non-JSON / truncated body; wrapper raises a clear error (not a raw `JSONDecodeError` bubbling up) and still logs an "error" row with `"unknown"` tokens.
13. **Empty / huge / malformed input** — empty `messages` list, empty string prompt, a single-message prompt in the megabytes (estimator and JSON-encoding don't choke or silently wrap), and a `caller` string containing a newline/quote (log line stays one valid JSON line — reuses `history_store.py`'s own documented guarantee that `json.dumps` escapes newlines).
14. **A person's mistakes** — missing/blank `caller` argument raises `ValueError` before any network call; `num_ctx<=0` or non-int raises before any network call.
15. **Stale lock file** — a `.lock` file left over from a killed process doesn't deadlock a fresh call (flock is released by the OS when the holder dies; assert the call still completes within a bound).
16. **Logging failure never breaks the real call** — log directory not writable; `chat()`/`embed()` still returns the real result to the caller (matches `error_log.py`'s "writers never raise" guarantee), with the failure itself surfaced via `error_log.record()` rather than silently swallowed twice.
17. **Migration regression guards** — existing suites for `test_intent_classify.py` (embed tests), `test_logic_auditor.py`, and any `retrieve.py`/`rebuild-embeddings.py`/other paper-dive test files all stay green after the swap, with the three `ic.requests.post`-patching tests rewritten against the new seam.

## Task List

1. Decide the `bench-scope` question above (blocks whether the coverage test's allowlist includes `bench/`).
2. Write `lib/model_calls.py`: `estimate_tokens()`, `PromptTooLong`/`ModelCallError` exceptions, `chat()`, `embed()`, the error_log-style `_append()`/rotation (`MAX_LINES`, `MAX_AGE_DAYS`), `_machine()`, and `summary()` + CLI (`model_calls.py summary [--days N] [--caller X] [--model X] [--json]`).
3. Add `lib/tests/test_model_calls.py` covering tests 1–16 above, using a real `http.server.HTTPServer` fixture (mirroring `test_health_merge_service.py`'s `webhook` fixture) for the network-facing cases.
4. Add `_isolate_model_calls_log` autouse fixture to `lib/tests/conftest.py` (mirrors `_isolate_error_log`), monkeypatching `model_calls.LOG_PATH` to a tmp path.
5. Migrate `lib/intent_classify.py`'s `embed_text()` to call `model_calls.embed(..., num_ctx=2048, caller="intent_classify")`; update the 3 tests in `lib/tests/test_intent_classify.py` that currently monkeypatch `ic.requests.post` directly.
6. Migrate `skills/self-improve/scripts/retrieve.py`'s `embed_query()` and `rebuild-embeddings.py`'s `embed()` to `model_calls.embed(..., num_ctx=2048, caller=<script name>)`.
7. Migrate `skills/paper-dive/scripts/paper_graph.py`'s `_real_nomic_embed()` to `model_calls.embed(...)`, dropping the deprecated `/api/embeddings` singular endpoint and its `"embedding"` response key in favor of the wrapper's normalized return shape.
8. Migrate the four paper-dive scripts' private `ollama_chat()` bodies (`logic_auditor.py`, `argument_mapper.py`, `continuity_checker.py`, `competing_ideas.py`) to delegate to `model_calls.chat(..., num_ctx=4096, caller=<script name>)`, keeping each file's existing `ollama_chat(model, messages, timeout=60)` signature unchanged so the `chat_fn` injection seams in their tests keep working untouched.
9. If decision `bench-scope` = A: add the three `bench/` files to the coverage test's explicit allowlist with a one-line comment pointing at this ticket. If B: migrate them too and drop the allowlist.
10. Run every test in `lib/tests/` and the touched `skills/*/scripts/tests/` directories; fix any regression before considering this done (per the "full suites before a hand-merge" rule).
11. `marvin-show` the final `lib/model_calls.py` and the diff for Gil's review.