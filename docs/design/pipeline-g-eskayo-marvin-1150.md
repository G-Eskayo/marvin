Good, that file doesn't assert on the reason text. I have everything needed to write the plan now.

## North-star fit

**Reuses before adding anything new:**
- `isRedTicket`/`FIX_TITLE` in `dashboard/webhook-server/merge_order.js:40-43` is the rule to port to Python; `prTicketRefs` in `dashboard/electron/main/ticket_refs.js:28` (already imported across the webhook-server/electron boundary by `merge.js`, `refusal_log.js`, etc. — that boundary is routinely crossed both ways) replaces a fourth hand-rolled "part of" regex for finding Part-of PRs in `mergeOrder`. `lib/pr_ticket_check.py`'s own `ticket_refs()` already dedupes a ticket named both ways to `"closes"` (lib/pr_ticket_check.py:55-69), which for free satisfies "no warning for the closed one, warning for the other." The live-GitHub-lookup-with-graceful-failure shape is `bin/gh`'s own `ui_evidence_refusal`/`_gh_json` pattern (`bin/gh:259-302`), reused verbatim for the new warning's `ask`.
- **Correction to the ticket's own text:** it says "Vitals' main/queue row." Per the 2026-11-09 decision (lexicon: "Workshop... reversing the earlier 'Vitals' placement"), pipeline/queue state now renders in Workshop's "Up next" section (`WorkshopTab.jsx:122`), not Vitals (which is machine CPU/disk/thermal only, `HealthDashboard.jsx`). Both Workshop and MR Review read the same `entry.reason` computed once in `mergeOrder`, so one change in `merge_order.js` reaches both surfaces — no separate "Vitals" work exists or is needed.
- **Simplest sufficient approach:** the queue-message change is a ~6-line edit to one existing branch in `mergeOrder` (merge_order.js:237-240), not a new code path. The PR-time warning is a new function in the module the ticket names (`lib/pr_ticket_check.py`) plus one new `ask=` wire in `bin/gh`, mirroring code that already exists one function below it.
- **Tokens:** spends a little (one extra `gh issue view` per "Part of" ref at PR-create/edit time, capped) to save a lot (15 minutes of a silently stalled merge queue, repeated indefinitely until someone notices by chance).
- **Leaves the user more capable, not more passive:** it tells Gil exactly what's blocking and why the moment it happens, rather than doing the work for him — he still decides whether to fix forward, reword the PR, or wait.

## Tests, written first

**A. `lib/pr_ticket_check.py` — the new PR-time warning** (new `lib/tests/test_pr_ticket_check.py` cases, fake `ask`):
1. "Part of #N" naming a red ticket (label `main-red`) → warns, names the ticket, suggests `Closes #N`.
2. "Closes #N" for the same red ticket → no warning.
3. **Attack — cross-repo form** `Part of owner/repo#N`: `ask` is called with `--repo owner/repo` (not the PR's own repo); warns.
4. **Attack — lower-case** `part of #N`: still warns (already handled by the existing case-insensitive regex; add a regression case to the shared fixture `dashboard/test/fixtures/pr_ticket_refs_cases.json` so JS and Python can't drift apart on it later).
5. **Attack — closes one red ticket, part-of a different red ticket:** warning only for the part-of one; `ask` is asserted called for both numbers.
6. **Attack — issue lookup fails** (`ask` raises, simulating a rate limit or 404): no warning, no crash, `gate()` still returns `None` (bin/gh proceeds to the real `gh` call).
7. **Attack — malformed GitHub response** (`ask` returns `{}`, or labels missing/not a list, or title missing): `is_red_ticket` doesn't raise, returns `False`.
8. **Attack — huge/malformed input:** a body naming 50 "Part of" tickets makes at most `MAX_PART_OF_LOOKUPS` (10) `ask` calls, not 50.
9. "Part of #N" for a ticket that is `bug`+`priority:p0`+titled "Main red" (the hand-filed form) → warns, same as the `main-red` label form.
10. "Part of #N" for a ticket that is NOT red (ordinary open ticket) → no warning, no `MARVIN_NO_TICKET`-style refusal either — this is a warning path only, PR creation must still succeed end-to-end (extend the existing `fake_gh`/`_bin_gh` end-to-end test).
11. No `ask` wired (existing callers/tests that don't pass it) → behaves exactly as today, no crash, no warning (default `ask=None`).

**B. `dashboard/webhook-server/merge_order.js` — the queue's reason text** (extend `dashboard/test/merge_order.test.js`, and matching line in `dashboard/test/merge_queue_dashboard.test.jsx`):
1. **Closes** (existing, unchanged): a fix PR open for the red ticket → reason stays `"main is red · waits for #<fix PR>"`.
2. **Part of only** (new): red ticket #978, no PR closes it, PR #985 says `Part of #978` → reason becomes `main is red; waiting for a PR that closes #978, and none does (#985 says "Part of #978" instead)`.
3. **No fix, no part-of** (update existing tests at `merge_order.test.js:79` and `:93`, and `merge_queue_dashboard.test.jsx:89`): reason text changes from `"main is red · waits for #978"` to `"main is red; waiting for a PR that closes #978, and none does"`.
4. **Two red tickets, one closed by a PR, one not** (new): confirms the existing fix-PR branch is untouched — when any red ticket has an open closing PR, the old `"waits for #<fix PR>"` message still wins, even though a second red ticket has neither a Closes nor a Part-of PR.
5. **The red ticket closed by hand, the hold lifts** (new, building on the existing `mainStateFrom` CLOSED-state test at line 102-105): once the ticket's state is `CLOSED`, `main.red` is `false` and the previously-waiting PR's entry has `reason: null, state: 'ready'` — no stale "none does"/Part-of mention lingers.
6. **Attack — cross-repo ticket with the same number** (existing test at line 91-94, extend): a `Part of other-org/other-repo#978` reference must NOT be treated as naming *this* repo's #978 — reason stays the generic "none does" with no PR named.
7. **Main-health-red only, no ticket at all** (existing test at line 96-100, unchanged): reason stays `"main is red · waits for a fix"` — never invents a ticket number.
8. **Attack — malformed PR body** (no body, `null` body) on a PR that would otherwise be in the "no fix" branch: `prTicketRefs(null, repo)` must not throw (existing `ticket_refs.js` behavior; add a direct assertion).

## Decisions

None. Every implementation choice here (wording of the new message, scoping the PR-time warning to onboarded repos via the PR's own target repo, capping lookups at 10, excluding the Recurrence check's probe from this fix) is a reversible, low-risk default consistent with existing patterns in this codebase, not a fork in direction that needs Gil's sign-off.

**One flag, not a Decision** (precedent: pipeline-g-eskayo-marvin-471/488/525's design docs all made the same call): the ticket's own `## Recurrence check` says "Probe: none yet... add one... as part of the fix," but per this task's instructions the authoritative scope is "What to build" + "Acceptance criteria," and no probe for "minutes the queue held on main-red with no closing PR" exists in `lib/purpose_metrics.PROBES` yet — building one needs its own design (where it reads the queue's held-time from; no such log currently records it) and isn't a bounded unit inside this fix. I'm not building it here; the PR should say so plainly and note the ticket's own outcome-check gate will warn until a probe is registered and the ticket's `## Recurrence check` section is updated to name it.

## Task List

1. `lib/pr_ticket_check.py`: add `FIX_TITLE` regex and `is_red_ticket(issue)` (Python mirror of `merge_order.js`'s `isRedTicket`), reading `labels`/`title` defensively (missing/malformed → `False`, never raises).
2. `lib/pr_ticket_check.py`: add `red_ticket_warning(body, repo, ask)` — iterates `ticket_refs(body, repo)` entries with relation `"part-of"` (capped at `MAX_PART_OF_LOOKUPS = 10`), looks up each via `ask(["issue", "view", str(number), "--repo", target, "--json", "labels,title"])`, returns a warning message naming the first red one found, or `None` on any failure (fails open) or if nothing's red.
3. `lib/pr_ticket_check.py`: wire it into `gate()` — new optional `ask=None` parameter; after the existing no-ticket `refusal()` check returns `None`, call `red_ticket_warning`, `say()` it and `log()` it if present, still `return None` either way (never blocks).
4. `bin/gh`: pass `ask=lambda a: _gh_json(real, a)` into the existing `pr_ticket_check.gate(...)` call (reusing `_gh_json`, already defined above it for `ui_evidence_refusal`).
5. `dashboard/test/fixtures/pr_ticket_refs_cases.json`: add one case for lower-case `"part of #N"` (shared by both parsers, closing the drift gap the Attacks list calls out).
6. `lib/tests/test_pr_ticket_check.py`: add the tests in section A above (fake `ask`, extend `run_gate`/`fake_gh` helpers to pass it through).
7. `dashboard/webhook-server/merge_order.js`: import `prTicketRefs` from `../electron/main/ticket_refs.js`; replace the `main.red && !isFix(p)` branch (lines 237-240) with the three-way split (fix PR exists / red ticket but no fix or part-of / no ticket at all), computing the Part-of lookup once per `mergeOrder` call (not per PR).
8. `dashboard/test/merge_order.test.js`: update the two existing assertions (lines 79, 93) to the new wording; add the Part-of-only, two-red-tickets, closed-by-hand, and null-body tests from section B.
9. `dashboard/test/merge_queue_dashboard.test.jsx`: update the assertion at line 89 to the new wording.
10. `docs/agents/issue-tracker.md`: add one line to the existing "A PR names its ticket" bullet noting the new warning (Part-of naming a red ticket prints a warning, not a refusal).
11. Run the full Python suite and the dashboard's JS/vitest suite (not a subset) before calling this done, per the repo's hand-merge rule.
12. In the PR description: flag the Recurrence-check probe gap from the Decisions section above, and link the merge-queue-stall incident (#1147/#1144) this closes.