Now I have a complete picture. Here's the plan.

## North-star fit

**Reuses:** the flock-protected, bounded-growth JSONL append pattern from `lib/error_log.py:_append` (open `"a+"`, `fcntl.flock(LOCK_EX)`, write, re-read, trim by count+age) — this is the exact "rotation, like other MARVIN logs" the ticket asks for, so it's copied in shape, not reinvented. `machine_profile.registry_id()` (already imported by `error_log.py`) supplies the `machine` field. The real-HTTP-server test pattern from `lib/tests/test_health_merge_service.py` (`http.server.HTTPServer` + `BaseHTTPRequestHandler`, "a real fake server, not a mocked flag") becomes the fake Ollama server for the overflow/timeout/missing-token-count tests. `statistics.quantiles` (stdlib) computes p50/p95, instead of writing new percentile math — no existing shared percentile helper exists in the repo (checked `lib/sandbox_orchestration.py`, `lib/seal_beta_ingest.py` — neither is general-purpose). The four duplicated `ollama_chat(model, messages, timeout=60)` functions (`logic_auditor.py`, `continuity_checker.py`, `argument_mapper.py`, `competing_ideas.py`) keep their exact signature as thin shims delegating to the new wrapper, so the existing `monkeypatch.setattr(la, "ollama_chat", fake_ollama_chat)` tests in `test_logic_auditor.py` etc. need no changes.

**Simplest sufficient approach:** one new module, `lib/model_calls.py`, exposing `chat()` and `embed()`. No new runtime, no `/v1` client yet (the vLLM/exo plan recommends that as a *later* step once this wrapper exists — building it now would be scope creep against an unvalidated need). No per-model tokenizer dependency: a `chars // 4` pre-flight estimate is cheap and dependency-free; the authoritative truncation signal is Ollama's own `prompt_eval_count`, which is exact, so the heuristic only needs to be good enough to stop a request *before* it's sent, not exact.

**Tokens:** mostly spent once, not repeatedly — the wrapper is write-once, and callers get smaller (duplicated HTTP/retry logic collapses into 2–3 line shims). The CLI `summary` command answers a question MARVIN would otherwise require ad hoc log-reading to answer, each time.

**More capable, not more passive:** this directly serves "decide from the data" — right now that decision (close the long-context track, or fix windows first) is a guess; after this ships it's measured. It also stops a real, silent correctness bug (prompts truncated at 4k with no signal).

**Machine:** no machine-specific code; runs identically on the Mini and the laptop (log path is per-machine under `~/.claude/logs/`, matching `errors.jsonl`/`gh-calls.jsonl`).

## Decisions

Two real forks worth the owner's call; everything else (num_ctx sizes, heuristic choice, log path) is a defensible engineering default, not posed as a question.

<!-- marvin:decisions -->
### bench_in_percentiles: Should bench.py's synthetic benchmark calls count toward the real-traffic p50/p95 that the 7-day "close the track or fix windows" decision is made from?
- [ ] A: Tag bench.py's rows `source: "bench"` and exclude them from `summary` by default (a flag opts them back in). Keeps the decision data clean of synthetic fixture runs.
- [ ] B: Log everything into one stream, no separate tagging. Simpler, but a large bench run right before the 7-day check could skew the real-prompt distribution.

### overflow_default: Default behavior when a prompt would exceed the num_ctx a caller set (no per-call override)
- [ ] A: Fail loudly by default (`on_overflow="error"`) everywhere; a caller opts into `"trim"` explicitly. Matches "never cut silently" as the safe default; a paper-dive call on an unusually long abstract stops that one paper instead of guessing.
- [ ] B: Trim by default for the paper-dive classify/extract/judge callers (short-answer tasks, truncating the abstract tail is low-risk) and error by default elsewhere (embeddings, bench). Keeps paper-dive jobs running end-to-end without a person unblocking them.
<!-- /marvin:decisions -->

I'll implement with A/A (fail-loud default everywhere, bench rows tagged and excluded) unless told otherwise, since that's the safer default in both cases and nothing blocks starting the build.

## Tests first (one file: `lib/tests/test_model_calls.py`, plus small test diffs in existing paper-dive/self-improve test files for the shim rename)

From "How we'll try to break it":
1. **Ollama down:** fake server never started / connection refused → `chat()`/`embed()` raise a clear, typed error within the given `timeout`, and a log row is still written with `error` set (never just an unhandled hang — assert wall-clock stays near the timeout, not far past it).
2. **Ollama slow:** fake server sleeps past `timeout` → raises inside `timeout + small margin`, never hangs; logged.
3. **Response without token counts** (simulate an older server: JSON with no `prompt_eval_count`/`eval_count`) → logged row has `prompt_tokens: "unknown"` / `eval_tokens: "unknown"`, never `0`.
4. **Concurrent callers writing the log at once:** reuse the `threading` pattern from `test_error_log.py::test_concurrent_writers_never_corrupt_lines` — N threads × M calls each, assert every line in the resulting file parses as valid JSON and the count matches N×M.

From acceptance criteria:
5. **Grep test:** a test walks all tracked `*.py` files (excluding `lib/model_calls.py` and its own test file) and asserts none contain the literal substrings `/api/chat`, `/api/embed`, `/api/embeddings`. Run it first against the *current* tree to confirm it currently fails (proves the test is real), then make it pass by migrating every call site.
6. **Prompt longer than num_ctx is never sent silently:** against the fake server, a message several times larger than `num_ctx` with `on_overflow="error"` raises before the fake server receives a body that reflects an un-trimmed send (assert the handler recorded either zero calls or a trimmed one); with `on_overflow="trim"`, the fake server's recorded request body is confirmed shorter than the original and the returned `ChatResult` is marked `trimmed=True`, logged as such.
7. **90% truncation flag:** fake server returns `prompt_eval_count = num_ctx * 0.95` → logged row has `possibly_truncated: true`; at `0.5 * num_ctx` → `false`.
8. **`summary` percentiles:** feed a synthetic JSONL fixture with known prompt-token values across two (caller, model) pairs and two days; assert `summary(days=N)` returns the right p50/p95/max per (caller, model), and that rows older than N days are excluded, and that `"unknown"` rows are excluded from the percentile math but counted separately (not silently dropped — the test checks an `unknown_count` field).
9. **Log can't grow without bound:** mirror `test_error_log.py::test_log_stays_bounded_under_an_error_storm` — hundreds of rows against a tiny `MAX_LINES`, assert the file stays bounded and keeps the newest rows.
10. **Misuse / malformed input:** `messages=[]`, `model=""`, huge single-message content (MB-scale string) — none of these crash the logger itself (the HTTP/overflow path may legitimately raise, but the *log write* must not throw); a non-serializable value slipping into `options` is caught and logged with a fallback rather than crashing the caller's job.
11. **Wrong permissions / stale state:** log directory not writable (`chmod` a temp dir, or point `path=` at a non-existent parent) → `chat()`/`embed()` still return/raise their normal result; logging failure never masks or replaces the real error (mirrors `test_error_log.py::test_record_never_raises_even_when_the_log_cannot_be_written`, but here the *call itself* must still succeed/fail on its own merits even if the log write fails).
12. **A person's mistake:** calling `chat()`/`embed()` without a `caller` or without `num_ctx` is a loud `TypeError` at call time (no silent default caller string), since an uninstrumented call site would otherwise defeat the whole ticket invisibly.

Existing-test preservation (no new test, but verified while implementing): `test_logic_auditor.py`, `test_continuity_checker.py`, `test_competing_ideas.py`, `test_argument_mapper.py`, `test_paper_graph.py` keep passing unmodified, since each module's local `ollama_chat`/`embed` shim keeps its current name and signature.

## Task List

1. `lib/model_calls.py`: `ChatResult`/`EmbedResult` dataclasses; `_estimate_tokens()` (chars // 4); `_append_row()` (flock-based JSONL append + bounded rotation, copied in shape from `lib/error_log.py:_append`, using `machine_profile.registry_id()`); `chat(model, messages, *, caller, num_ctx, timeout=60, base_url=None, on_overflow="error", options=None, source="prod")`; `embed(input, model, *, caller, num_ctx=2048, timeout=30, base_url=None, task="query", on_overflow="error", source="prod")`; both always log (success, overflow-rejected, or error) and never swallow the real outcome if logging fails.
2. `summary(days=7, *, path=None, include_bench=False) -> dict`: group by `(caller, model)`, p50/p95/max via `statistics.quantiles`, `unknown_count`; CLI entry (`argparse`, subcommand `summary --days N [--json] [--include-bench]`).
3. `lib/tests/test_model_calls.py`: all 12 tests above, including the fake-Ollama `http.server` fixture (reused across the file).
4. Migrate `/api/chat` call sites to thin shims calling `model_calls.chat(...)`, each with its own `caller` string and `num_ctx=4096`: `skills/paper-dive/scripts/logic_auditor.py`, `continuity_checker.py`, `argument_mapper.py`, `competing_ideas.py`.
5. Migrate `/api/embed(dings)` call sites to `model_calls.embed(...)`, `num_ctx=2048`: `lib/intent_classify.py:embed_text`, `skills/self-improve/scripts/retrieve.py:embed_query`, `skills/self-improve/scripts/rebuild-embeddings.py:embed`, `skills/paper-dive/scripts/paper_graph.py:_real_nomic_embed` (also switches it from the deprecated `/api/embeddings` to `/api/embed`, normalizing the response-shape difference).
6. Migrate `bench/bench.py:run_once_ollama` to call `model_calls.chat(..., caller="bench.run_once_ollama", num_ctx=8192, source="bench")`, replacing its manual `urllib`/JSON parsing with `ChatResult` fields; keep its existing `spawn_error` return shape on exception.
7. Run the grep test (task list item 3) against the full tree and fix any remaining direct-call site it turns up that wasn't in the inventory above.
8. Run the full existing paper-dive / self-improve / bench / lib test suites to confirm no regressions from the shim rewiring.
9. Open the PR with the Decisions block above, naming this ticket (`Closes #1210`).