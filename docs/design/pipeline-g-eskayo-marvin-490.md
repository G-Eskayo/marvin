## North-star fit

- **Reuses before adding:** No new mechanism — this edits one paragraph and one table row in `skills/route/SKILL.md`, in the same two sections it already has (the prose block in the "in-session auto-routing" paragraph at line 34, and the existing `## Evidence base` table at line 63-73 whose `| Finding | Source |` format is reused as-is). The citation style itself is reused from `skills/route/scripts/route.py`'s own `--keyword` help text (line 353-357: "ADR 0023 default since 2026-08-13, bench/RESULTS.md Run 21: 70% held-out accuracy vs. keyword's 25%") rather than inventing new phrasing.
- **Simplest sufficient approach:** A pure prose/table correction, zero code changes, zero new files — matches the ticket's own "Docs-only: exempt" note.
- **Token/cost:** Spends a small, one-time editing cost now; saves tokens repeatedly afterward, since every future session/agent that reads this SKILL.md to debug an odd routing decision stops starting from the wrong (keyword-only) mental model.
- **North star stated vs. checked:** The ticket claims north star 4 ("tool for tools: the skill's doc matches its code"). Checked against the north-stars doc: north star 4 is about work that makes MARVIN *better at building tools in general*, not about one skill's doc staying in sync with its code — this one-off correction doesn't generalize that way. The better fit is north star 2's reliability clause ("nothing may break silently") and the "Verified, not assumed" guiding principle: a stale doc is a silent-mismatch risk for whoever (human or agent) debugs a routing decision next. Noting this correction rather than silently keeping the ticket's stated fit.
- **User benefit:** Leaves whoever next debugs an odd routing suggestion (Gil or an agent) starting from the real mechanism instead of a superseded one — more capable, not more passive.

## Current state read (before editing)

- `skills/route/SKILL.md:34` still says auto-routing triggers on "≥2 keyword matches from the routing table" with no mention of the embedding classifier, `--keyword`, or ADR 0023.
- `skills/route/scripts/auto_route_hook.py:_resolve_intent()` (lines 129-142): real order is (1) `route.classify()` keyword pass, used when `hits >= route.MIN_HITS` (2); (2) else `route.intent_classify.classify_fast()` with `EMBED_TIMEOUT=1.5`s; (3) `status == "no_cache"` → spawn a background vector build and stay silent; any exception or non-"ok" result falls to `route.DEFAULT_INTENT` ("architecture", silent by `ROUTED = ("coding", "research")`, line 46).
- `route.py:117-118,160-170,353-358,380-381`: `DEFAULT_INTENT = "architecture"`, `MIN_HITS = 2`; CLI defaults to the embedding classifier, `--keyword` opts out (`_use_embed` returns `not args.keyword`).
- `bench/RESULTS.md` Run 21 (line 600-604): held-out keyword 25% vs. embedding 70% (tuning-set keyword was 30%, matching the ticket's "~25-30%"). Run 29 (line 1082-1105): fresh v3 holdout, embedding **87.5%**, independently confirmed, up from Run 21's 70%.
- `~/.agents-pipeline-worktrees/.../CLAUDE.md` (project root) has no routing-keyword content to touch — ADR 0023's "Phase 2" already deleted that line; acceptance criteria only target `SKILL.md`.
- No open design question: the mechanism, the flag, and the numbers are all already fixed facts in the code/ADR/bench log. **No Decisions section needed.**

## Tests

**How we'll try to break it: "Docs-only: exempt."** No code changes, so no test file is added or run. The only verification is accuracy of the new prose/table against the files just read above:
- Re-read `auto_route_hook.py:_resolve_intent()` after editing and confirm the new paragraph's 3-step order (keyword → embed-with-timeout → no-cache-build-silent → exception-falls-to-default) matches it line-for-line, not just directionally.
- Re-read `route.py`'s `--keyword` help string and confirm the new Evidence base row's numbers (70% held-out / 25-30% keyword / 87.5% current) match it and `bench/RESULTS.md` Run 21/29 exactly, not rounded differently.
- Grep the edited file afterward for the literal string "≥2 keyword matches" to confirm it no longer describes that as the whole rule.
This satisfies "verify fails when code changes without a test changing" vacuously here — no code changes, so no test is expected to change; the check above is the doc-accuracy equivalent for a docs-only ticket.

## Task List

1. Edit `skills/route/SKILL.md`'s "in-session auto-routing" paragraph (line 34) to replace "≥2 keyword matches from the routing table" with the real 3-step order: keyword pass first (`route.classify()`, ≥`MIN_HITS`=2 hits), else the embedding classifier (`intent_classify.classify_fast()`, short timeout), else — on a first run with no vector cache — a silent background build; any failure also falls silent to the default intent. Keep the existing "fires once per session, silent on architecture/no-match" framing, since that's still accurate.
2. Add one line to the `## CLI usage` section noting `route --keyword` / `route.py --keyword` as the explicit opt-out from the now-default embedding classifier.
3. Add one row to the `## Evidence base` table citing ADR 0023 and bench Run 21 (70% held-out vs. keyword's 25-30%) plus the current validated figure (87.5%, Run 29), phrased in the same citation style `route.py`'s own `--keyword` help text uses.
4. Re-read the edited `SKILL.md` against `auto_route_hook.py`, `route.py`, and the ADR/bench lines cited above to confirm every claim matches current code exactly (the doc-accuracy check standing in for tests on this docs-only ticket).
5. Confirm all three acceptance criteria are met: no more "≥2 keyword matches" as the whole rule; keyword-then-embedding order and `--keyword` flag both named; Evidence base row's numbers match the ADR.