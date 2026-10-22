## North-star fit

**Reuses before adding anything new:**
- `lib/health_checks.py`'s check-registry pattern — `default_checks()` + `run_checks()`/`guarded()` (lib/health_checks.py:1420-1492, e.g. `check_github_budget` at :591) — instead of PR #359's `results.append(check_autonomous_share())` bolted directly into `run_all()`. That bypass is almost certainly *why* PR #359 was denied: `GATE_TESTS_FAILED` on `test_run_all_includes_autonomous_share_check` with a `JSONDecodeError` — the check's `usage_path` default (`session_usage.OUT_PATH`) is the **real** `~/.claude/logs/token-usage.json`, which no conftest fixture isolates today (unlike `marvin_launcher.LAUNCH_LOG`, `github_usage.*_PATH`, etc., which all have `_isolate_*` autouse fixtures in `lib/tests/conftest.py`). Read through `run_all()` directly, any exception there is fatal to the whole sweep; read through the registry, `guarded()` catches it and reports "unknown". Both the missing isolation and the missing registry entry need fixing — either alone leaves the suite fragile.
- `marvin_launcher.launch()`'s existing `ticket=` kwarg and `LAUNCH_LOG` (lib/marvin_launcher.py:119-166) for per-job attribution — no new instrumentation, just tagging the autonomous call sites that don't pass `ticket=` today.
- `lib/session_usage.py`'s `aggregate()`/`dailySeries` and `dashboard/src/lib/usage_view.js`'s `dailySeries`/`dayList`/`projectTable` patterns, and `UsageView.jsx`'s `DailyBars`/`Table`/`fmt` — new series functions and markup mirror these exactly rather than inventing a new charting approach.
- `usage_report.py` needs **no change** — it already forwards each machine's whole `tokens` dict (local file read, or peer's over ssh) verbatim, so new fields (`autonomous`, `by_job`) ride along for free.

**Why this is the simplest sufficient approach:** no new file, no new cron job, no new storage format — two additive fields on the JSON `session_usage.py` already writes hourly, one read-only health check reusing the existing guarded-registry mechanics, and dashboard code that's additive to the existing Usage view.

**Tokens:** spends a little (a bigger token-usage.json, a few more `ticket=` tags) to buy the visibility Gil explicitly asked for over capping ("show it first", 2026-10-09); saves tokens later by letting the real top spender get fixed instead of guessed at.

**Phone-OS direction:** neutral — a dashboard visibility feature, not a reachability/offline capability.

**User capability:** more capable, not more passive — pure visibility, no auto-pause/cap (explicitly out of scope per the decision), so it informs Gil's own judgment rather than taking a decision away from him.

No Decisions section needed: the one open design fork the ticket itself calls out (cap now vs. later) is already resolved in the issue body ("No cap yet… show it first"); everything else below is an ordinary, reversible implementation call, not something that needs Gil's button-press.

## Tests first

The ticket has no "How we'll try to break it" section, so these are derived from ADR 0063 / north-star guiding principles plus the concrete failure already recorded in the issue's comments (treated as a requirement, per the ticket agent's own note).

**Regression from the denial (top priority — this is what sank PR #359):**
1. `lib/tests/conftest.py`: new autouse fixture isolating `session_usage.OUT_PATH` to a tmp dir, so no test touches the real production file.
2. `check_autonomous_share` is reached through `default_checks()`/`guarded()`, not a bare `run_all()` append — assert it's present in `default_checks()`'s tuple list.
3. Feed `run_all()` a *deliberately malformed* usage file (two concatenated JSON docs / truncated JSON, reproducing "Extra data" / a bad read) and assert the sweep completes normally with that check reported as `"unknown"` severity, not an uncaught exception.

**`check_autonomous_share` itself (bad/empty/huge/malformed input, stale/missing state):**
4. usage file missing → green, "not yet run".
5. file exists, `rows: []` → green, "no usage rows".
6. rows present but none have a `day` field (malformed/old schema) → green.
7. total output is zero on the latest day (idle/all-cache-read day) → green.
8. share exactly 50% → green (boundary is exclusive).
9. share just above 50% → yellow.
10. 100% autonomous → yellow, never red.
11. multiple days present → only the latest day is used.
12. across every ratio tested, result never has a `pause` or `cap` field and severity is only ever green/yellow (never red) — this is the hard "visibility only" constraint from the issue.

**`session_usage.aggregate` — `autonomous` flag and `by_job` (dependency failing, repeats, malformed input, stale schema):**
13. autonomous classification depends only on `entrypoint`, independent of `kind`/`isSidechain` — interactive always False, headless always True, subagent inherits from its parent's entrypoint.
14. `by_job`: `LAUNCHES_LOG` missing → `[]` (dependency absent).
15. empty file → `[]`.
16. malformed (non-JSON) lines skipped, well-formed lines around them still counted.
17. non-dict JSON lines (e.g. a bare array) skipped.
18. null `output_tokens`/`cost_usd` treated as 0, never crashes.
19. entries older than `window_days` excluded.
20. `ticket: null` falls back to `kind` as the job label (two different launches, one tagged one not, must not merge).
21. same `(kind, ticket)` across multiple launch lines sums `output_tokens`/`cost_usd`/`runs` correctly — with three distinct-magnitude rows so an arithmetic mutation (swapped field, off-by-sign) can't slip through unnoticed (closing the mutation gap PR #359's own mutation-score report flagged: a changed-number mutation in the analogous `interactive_output` sum went uncaught).
22. sorted descending by `output_tokens`, truncated to `TOP_JOBS`.
23. the launches file unreadable (chmod 000 — wrong permissions) → `[]`, no crash; restore permissions in a `finally`.
24. two kinds sharing the same ticket name are kept as separate jobs (key is `(kind, ticket)`, not `ticket` alone).

**Dashboard JS — `autonomousSeries`/`weeklySeries`/`jobTable` (empty/huge/malformed, stale schema):**
25. a day with zero rows → all zeros, `share` is `0`, never `NaN`.
26. a day that's 100% one side → `share` exactly `1` or `0` (float-division edge).
27. weekly bucketing sums correctly across a week boundary, including a week with no rows at all.
28. `jobTable` merges the same `(kind, job)` across two machines, summing all three counters.
29. `jobTable` tolerates a machine object with `by_job` absent entirely (older scan format on one machine while the dashboard code is newer — a person's/rollout mistake).
30. `jobTable` sorts descending by `output_tokens`.

**Call-site tagging (a person's mistake — a new autonomous caller forgetting to tag itself):**
31. each of the 5-6 autonomous `marvin_launcher.launch(...)` call sites that currently omit `ticket=` is asserted, in its own existing test file, to now pass the expected literal `ticket=` string — locking in today's tag set so a future edit that silently drops it is caught.

## Task List

1. `lib/tests/conftest.py`: add an autouse fixture isolating `session_usage.OUT_PATH` to a tmp path (mirrors `_isolate_github_usage`).
2. `lib/session_usage.py`: add `_autonomous(d)` (entrypoint-based), add `"autonomous"` into each row's bucket key/output, add `LAUNCHES_LOG`/`TOP_JOBS` constants, and a `by_job` aggregation step inside `aggregate()` (new `launches_path` param, default `LAUNCHES_LOG`) with all the malformed/missing/permission/window-day handling from tests 14-24.
3. `lib/tests/test_session_usage.py`: write tests 13-24.
4. `lib/health_checks.py`: add `check_autonomous_share(usage_path=None, now=None)` next to `check_github_budget`, registered as an entry in `default_checks()` (never a raw `run_all()` append).
5. `lib/tests/test_health_checks.py`: write tests 2-12.
6. Tag the autonomous launch sites with `ticket=`: `skills/improve/scripts/daily_digest.py` (`"daily-digest"`), `skills/research-colony/scripts/research_digest.py` (`"research-colony"`), `skills/self-improve/scripts/background_review.py` (`"self-improve"`), `skills/architecture-review/scripts/background_architecture_review.py` (`"architecture-review"`), `lib/ticket_promotion.py`'s two call sites (`"ticket-promotion"`), `skills/improve/scripts/auto_fix.py` (`"auto-fix"`).
7. Extend each of those scripts' existing launcher-call tests to assert the new `ticket=` kwarg (test 31).
8. `dashboard/src/lib/usage_view.js`: add `autonomousSeries`, `weeklySeries` (single precomputed window-boundary list, not PR #359's per-row `indexOf` recomputation), `jobTable`.
9. `dashboard/test/usage_view.test.js`: write tests 25-30.
10. `dashboard/src/components/UsageView.jsx`: add the day/week autonomous-vs-interactive bars with dashed 30/40/50% reference lines, and the "Top autonomous spenders" table, built from the task-8 helpers.
11. Run the full pytest + vitest suites locally, rebased onto current `main` (not PR #359's stale/conflicting branch, which `gh pr view 359` shows as `DIRTY`/`CONFLICTING`), before raising the PR — specifically re-running `lib/tests/test_health_checks.py` and `lib/tests/test_session_usage.py` to catch the exact failure class that sank the previous attempt ahead of the merge gate.