1. Rebase `ticket/1037-overhead-design` onto current `main` (single new-file commit, no conflicts expected) and force-push, so PR #1125 is mergeable again as the doc-only PR it already claims to be. No content change.
2. New branch off `main` (e.g. `fix/1037-routing-levers`), linked from PR #1125:
   - [ ] `skills/route/scripts/route.py`: set `INTENTS["recall"]["model"]` to `None`, update its `why`/`savings` text to the decided reasoning.
   - [ ] `lib/tests/test_route.py`: add tests 1–3.
   - [ ] `bench/cost_validation.sh`: fix the stale comment (test 8, review-only).
   - [ ] `bench/bench.py`: replace per-run `tempfile.mkdtemp()` with a deterministic, reused folder keyed by `(task_id, profile, model-or-"default")`, emptied at the start of each `run_once()` call instead of deleted after.
   - [ ] `bench/tests/test_cost_validation.py`: rewrite the fresh-folder test and add tests 4–7.
   - [ ] `skills/route/scripts/route.py`: add `--model-for-launch "<text>"`, printing the resolved model id or an empty line, reusing `resolve_intent()`.
   - [ ] `dashboard/mobile-backend/session_runner.js`: accept an optional `model` and append `--model` to the spawn args when set.
   - [ ] `dashboard/mobile-backend/chat_api.js`: when `currentSessionId` is falsy, resolve a model via the new route.py flag (injectable `exec`, fail-open on any error/timeout) and pass it to `runSession`.
   - [ ] `dashboard/test/`: add tests 9–15 (JS) and a Python test for `--model-for-launch`.
3. Post the PR #1125 reply (`<!-- marvin:decisions-addressed -->`): name the commits for bench-folders/routing/recall-model; say rerun is still gated on the task set (unchanged); say claude-md stays as-is and answer "why not MARVIN" directly (CLAUDE.md is cache-*read*, not rewritten — trimming it only shaved ~1% of a trivial session, so it isn't where MARVIN's lever is; that's the skill listing, which is why the real work is on MARVIN's side); explain why skill-listing wasn't guessed; say no UI changed so no screenshots; attach the three new Decisions above.