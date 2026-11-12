## North-star fit

Reuses, before adding anything: `route.py`'s existing `INTENTS` table and `resolve_intent()` (ADR 0023 embedding classifier) for all model-routing decisions — no new classification logic; `marvin_launcher.py`'s existing `model=` parameter and `KINDS` table (ADR 0059) for launch-time context; the `disable-model-invocation: true` frontmatter flag already used by `zoom-out`/`setup-matt-pocock-skills` for skill-listing control; `dashboard_api.js`'s `opts.exec ?? execFileP` injectable-exec pattern for calling out from the Node mobile-backend to Python; and `docs/agents/decisions-format.md` / `lib/owner_decisions.py`'s existing Decisions mechanism for anything that still needs Gil's input. North star 3 check: routing decisions happen silently at launch, so Gil never has to remember a command (directly answers his "I don't want to move it to needing slash commands" worry) — more capable, not more passive. Spends a small amount: one extra short subprocess call on the *first* message of a new phone Thread only (never mid-session, so no cache-busting model switch). Saves: the actual chosen levers (recall off Haiku, research-at-launch routing, a bench that measures the real lever instead of an artifact).

The ticket's own fit claim ("the doc is `docs/design/1037-session-overhead.md`; this PR adds only that file") is now stale for *this* ticket: #1140 isn't about that doc, it's about carrying out code-level decisions made on top of it. I checked — doing that correctly means going beyond doc-only changes.

**Key finding from reading the branch first:** `ticket/1037-overhead-design` is 166 commits behind `main` (based on `e0afc18e`, before dozens of later deletions/renames — e.g. `lib/site_deploy.py`, `lib/model_cache.py`, `docs/adr/0083-*` didn't exist at its base). `git diff main...branch` shows ~5,100 deleted lines that are just drift, not PR content; the actual PR diff (`gh pr diff 1125`) is one new file, `docs/design/1037-session-overhead.md` (131 lines). Carrying out the decisions as real code on that stale branch would be reviewing against a 166-commit-old tree — too risky. Plan: rebase that branch onto current `main` (trivial — single new-file commit, no conflicts) so PR #1125 is mergeable again as a doc-only PR exactly as it already claims, and put all actual code changes in a **new** PR linked from it, per the ticket's own instruction ("if the work belongs in a new PR, link PR #1125 from it").

## What's actually decided vs. not

| Decision | Chosen | Action |
|---|---|---|
| bench-folders | stable folder per (task,cell), emptied between runs | **build** |
| rerun | not until #1037 task set exists, then once (+ owner wants recurring) | **no bench run now**; cadence is a new, unanswered question |
| skill-listing | *(no boxes ticked — only a note)* | **can't guess**: the note asks for usage-based auto-routing of skills into the listing, not a manual pick from the offered list, and explicitly rejects slash-command-only. That's a different, bigger design than the one offered. Say so in the reply; raise a new Decision instead of silently building something he didn't ask for. |
| claude-md | No, leave CLAUDE.md as is | **no code change** — just answer his question in the reply |
| routing | A: route at launch | **build** |
| recall-model | keep recall on session model | **build** |

## Tests to write first

Per the issue's break-it bullets, applied to each real code change (plus misuse the section didn't name):

**`route.py` recall-model change**
1. `route.INTENTS["recall"]["model"] is None` (session model, not Haiku).
2. `_launch_cmd("recall")` no longer contains `--model`.
3. `resolve_intent()` on a recall-shaped prompt still returns intent `"recall"` (classifier unaffected) but `print_routing` shows `model: default`.

**Bench folder stability (`bench/bench.py`)**
4. Two successive `run_once()` calls for the same `(task_id, profile, model-or-default)` get the **same** folder path.
5. A file left over from a previous run in that folder is gone before the next run starts (emptied, not just cleaned after — must survive a crash that skipped end-of-run cleanup: empty *at the start*, not only at the end).
6. Two different cells (different profile, or same profile different `--model`) never collide on the same folder, even run concurrently.
7. Non-`fs`/non-`tmp` tasks (fixed `cwd`) are unaffected — rewrite, don't drop, the existing `test_qa_task_with_tmp_cwd_runs_in_a_fresh_folder_outside_home` (its "deleted after" assertion must change to "reused and emptied").
8. `cost_validation.sh`'s comment is corrected (research only, not recall+research) — not independently testable, verified by review.

**Routing at launch (mobile Thread, `dashboard/mobile-backend`)**
9. New session (`currentSessionId` falsy) + a research-shaped message → `runSession` is called with `--model <haiku>`.
10. Resumed session (`currentSessionId` present) → routing is **never** consulted, even for the same message text (no mid-session switch — ADR: "Delegate, never switch").
11. Classify dependency throws / times out / exits non-zero → fail open: session proceeds with no `--model` override (same philosophy as `auto_route_hook.py`'s "any failure exits silently").
12. Empty message → still rejected with the existing 400 (unchanged regression check).
13. Very large message (megabyte-scale) → classify call doesn't hang the chat response (bounded timeout, then fail open).
14. Two concurrent new-Thread POST /chat calls → independent, stateless classify calls, no shared-state corruption.
15. `route.py --model-for-launch` (new flag): bad/garbled text → empty output (session default), not a crash.

## Decisions
<!-- marvin:decisions -->
### skill-listing-scope: The owner's note asks for usage-based routing of skills into the per-session listing, not a manual pick from the offered list, and rules out slash-command-only. No telemetry source for "what's used and how" exists yet (closest: the parked tool-invocation-metrics idea). How should this be scoped?
- [ ] A new #1037 sub-ticket: build skill-usage telemetry first, then an auto-listing mechanism on top of it
- [ ] Fold it into whichever refactor he meant (engine/instance split, ADR 0071) — needs him to name which one
- [ ] Keep it manual for now (re-offer the original checklist) until usage data exists

### rerun-cadence: He wants `cost_validation.sh` running semi-regularly once the task set exists, not just once. What should trigger a re-run?
- [ ] A weekly launchd job (same pattern as `research-colony`'s install.sh/plist)
- [ ] After every N merged PRs that touch session-overhead-relevant files (route.py, marvin_launcher.py, skills manifest)
- [ ] Manual only, for now — revisit once the one-time re-run happens

### haiku-audit: His note questions whether Haiku is still the best model to pay for, given Run 31's 0/3 recall miss. Want a dedicated bench task for that now, or fold it into the semi-regular re-run above?
- [ ] A separate small bench task now (model-choice only, not the full cost_validation sweep)
- [ ] Fold into the semi-regular re-run once its cadence is decided above
- [ ] Not now

## Task List

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