# Run MARVIN on the $20 plan, 2026-10-22

Design only (ticket #594, "Run MARVIN on the $20 plan: degrade to cheaper models at the usage limit, and measure ourselves on the north-star metrics again"). No production code in this PR. Owner: Gil (they/them).

Sources read: `docs/north-stars.md`, CONTEXT.md (the governor #327, "Triggers over polling" and polling guard #556), #81 (usage split), `skills/route/` (`route.py`, `auto_route_hook.py`), `lib/model_registry.py`, `config/models.json`, `bench/select_model.py`, `bench/SCORECARD.md`, `bench/RESULTS.md`, `lib/rate_limit_backoff.py`, `lib/failure_breaker.py`, `lib/session_usage.py`, `~/.claude/logs/token-usage.json`, `~/.claude/logs/launches.jsonl`, the Vitals plan (#577, `docs/plans/health-metrics-redo-2026-10-21.md` on `docs/health-redo-design`), and the memories on MARVIN self-reliance and the subscription sunset.

## 0. North-star fit

- **Reuses before adding:** `session_usage.py` (the transcript ledger), `launches.jsonl` (one row per headless launch), `rate_limit_backoff.py` and `failure_breaker.py` (limit handling already exists, in pieces), `route.py` and `intent_classify.py` (task classifier), `select_model.py` (cheapest-first sweep, locks in after 3 passes), `model_registry.py` (Ollama capability map), the #577 store. No new daemon, no new classifier, no new store.
- **Why simplest sufficient:** one decision function ("which tier may this task run on right now?") fed by two inputs (the task's measured minimum tier, the current limit state). Everything else is existing pieces wired by events.
- **Tokens:** this is north star 1 applied directly. A change counts only if quality holds (send-back rate, gate failures) at lower cost.
- **Phone-OS (north star 2):** the governor is a general "shed and keep flying" primitive, reachable from any entry point (chat, pipeline, phone), works with no subscription by falling to local Ollama. That is the Apollo image in north star 1.
- **Self-reliance (Gil, 2026-10-21):** the plan must still work when the subscription ends. So the governor's state lives in MARVIN's own store (`~/.agents/var/`, the #577 store), not `~/.claude`, and the bottom rung of the ladder is local. Two things today live in `~/.claude` (`rate-limit-backoff.json`, `token-usage.json`); Decision `state-home` asks whether to move them. Stated plainly: the *signals* (rate-limit events, transcripts) are Claude-specific by nature; the *policy and state* need not be.
- **More capable or more passive (north star 3):** neutral to positive. Gil sees where the allowance goes and chooses what gets shed; nothing is shed silently.

## 1. Today's measured usage

Source: `~/.claude/logs/token-usage.json`, produced by `lib/session_usage.py` from Claude Code transcripts. **This is the MacBook only** (`machine: macbook-pro-1`, 7,955 transcript files, 28 days with data in a 30-day window, generated 2026-10-22 05:35 UTC). The Mini's file is not read here (see 1.5).

### 1.1 Totals and by model

Output tokens are what matters for limits (cache reads are cheap, cache writes are not; the ledger keeps them apart).

| Model | Output tokens | Share of output | Cache write | Cache read | Messages |
|---|---|---|---|---|---|
| claude-sonnet-5 | 6.14 M | 45% | 24.1 M | 785.6 M | 6,258 |
| claude-opus-5-5 | 4.07 M | 30% | 36.3 M | 2,043.6 M | 6,973 |
| claude-haiku-4-5 | 3.49 M | 25% | 12.9 M | 451.1 M | 7,049 |
| other (sonnet-5-5, haiku-5-5) | 0.02 M | under 1% | 0.7 M | 0.7 M | 35 |
| **Total** | **13.71 M** | | **74.0 M** | **3,280.9 M** | **27,526** (7,211 more are `<synthetic>` zero-token aborted turns) |

Opus is 30% of output but **49% of cache writes and 62% of cache reads**: it is the big-context tier, so its share of the *allowance* is larger than its share of output suggests.

### 1.2 By run kind (who asked)

| Kind | Output | Notes |
|---|---|---|
| headless (pipeline, digests, judges, background) | 9.14 M (67%) | Sonnet 5.41 M, Haiku 3.49 M, Opus 0.23 M |
| interactive (Gil's chats) | 4.30 M (31%) | **Opus 3.75 M**, Sonnet 0.55 M |
| subagent (Agent tool from a chat) | 0.28 M (2%) | but **Opus 16.5 M cache write**: 2,089 Opus subagent messages carrying large contexts |

So the two levers are different. Interactive is almost all Opus (the session model). Subagents default to the session model, which is exactly the 2026-10-21 finding in the ticket: every agent ran on Opus.

### 1.3 By task type (what the work was)

Only headless launches carry a task type. `~/.claude/logs/launches.jsonl` (367 launches since 2026-10-08, with `kind` and `model`):

| Launch kind | Model | Launches | Output tokens | Reported cost | Non-zero exit |
|---|---|---|---|---|---|
| ticket-planner | sonnet-5 | 124 | 1.91 M | $82.2 | 49 |
| ticket-executor | haiku-4.5 | 115 | 1.29 M | $39.2 | 44 |
| judge | opus-5-5 | 33 | 0.10 M | $9.7 | 3 |
| background-analyst | default / sonnet / haiku | 30 | 0.06 M | $11.5 | 5 |
| judge | haiku | 44 | 0.02 M | $0.55 | 4 |
| utility-call | haiku / default | 21 | 0.02 M | $1.7 | 2 |

Reading it: the pipeline's planner (Sonnet) is the largest tracked spender; the executor already runs on Haiku; judges on Opus are cheap in tokens but each is an Opus call (33 of them, where 44 Haiku judges did the same job class). About 40% of planner and executor launches exit non-zero (49 of 124, 44 of 115), and that is wasted allowance whatever the cause. By ticket, the top five are marvin#94 (2.06 M output), #97 (0.70 M), clarity-captions#44 (0.50 M), marvin#217 (0.46 M) and #81 (0.39 M); #94 alone is 15% of 30-day output, the retry storm already fixed on 2026-10-01 per memory.

### 1.4 Shape over time

Mean 0.49 M output tokens per day over the 28 active days; the five biggest days were 0.83, 0.84, 1.33, 1.89 and **2.48 M**. Usage is spiky, driven by build days, not steady.

### 1.5 Rough projection against the plans

Honest framing first: Anthropic does not publish the plans' limits as token counts, and the limit is a rolling session window plus a weekly cap whose weighting by model is not visible to us. So there is **no token-count projection that can be exact**. What can be said:

- The $100 plan (Max 5x) is advertised as about 5x the $20 plan's usage. Gil has been hitting the $100 plan's session limit after productive runs (memory, 2026-10-09), so on a bad day that plan is *just* sufficient.
- If the $20 plan gives roughly one fifth of that, then holding today's mix we would need to cut average load by about 80% and the peak days (2.5 M output) by about 95%. That is an order-of-magnitude statement under an assumed ratio, not a measurement.
- What the cuts could be made of, from 1.1 to 1.3: (a) Opus subagents and Opus judges to Sonnet/Haiku; (b) the 49 + 44 failed planner/executor launches and 7,211 aborted turns; (c) classify/extract/judge work to local Ollama (the registry already maps four local capabilities); (d) shedding low-priority background work first at the limit. None of these is sized yet, which is what section 3's measurement does.

### 1.6 What cannot be measured yet

1. **Interactive task type.** Interactive and subagent rows have no task label. Only the project and the kind. Needs the per-message hint log (3.4).
2. **The Mini.** `session_usage.py` writes one file per machine; the MacBook's file does not include the Mini's pipeline work. The Mini is the primary automation host (PRD #109), so the real total is higher.
3. **Plan limits and model weighting.** Not observable except through the limit event itself. We can record *when* the limit hit and how much we had used by then, which builds the real number over time.
4. **Quality by tier.** No send-back or gate-failure rate is joined to model yet. `select_model.py` scores bench tasks, not real daily work.
5. **Cost.** `cost_usd` in `launches.jsonl` is API-priced; it is a relative weight, not what a subscription charges.
6. **Whether `usage-scan.log` is healthy.** It is empty (0 bytes) and `usage-scan-error.log` exists; the scan did produce today's file, so it ran, but its log says nothing. Not diagnosed here.
7. **Local Ollama usage.** Not logged at all, so "shifted to local" cannot yet be counted.

## 2. The usage governor

The governor already exists as a concept (CONTEXT, #327: an observer that sees busy sections, knows the limits, sets each section's dial). This plan fills in its **token budget** limit and its **model dial**. It does not add a second observer.

### 2.1 How MARVIN sees its burn and the limit (all event-driven)

| Signal | Where it comes from | Trigger |
|---|---|---|
| Limit state and reset time | `rate_limit_event` / `rate_limit_info` (`status`, `resetsAt`, `rateLimitType`) in every headless `claude -p --output-format stream-json` stream; `_check_quota()` in bench already parses it | Each headless launch ends: its own output is the event. No extra probe call |
| The hard wall | The literal "You've hit your session limit - resets 4:50pm" text (`rate_limit_backoff.is_rate_limit_text`), and `ModelRunFailed` in `run_ticket` | The failing launch |
| Burn so far | Row appended to `launches.jsonl` at launch end (exists); transcripts for interactive via a file watch on `~/.claude/projects` (the same pattern as the Electron main process watching `ticket-stages/`) | File change, debounced |
| Account-wide breaker | `failure_breaker` already pauses dispatch after 3 `model-unavailable` in a row | Existing |

No `setInterval`, no sleep in a loop, no TTL name: the polling guard (#556) stays green. The one place that wants time is the reset (2.4); see there.

**What can't be seen:** the remaining allowance *before* the wall, except what the stream's `rate_limit_info.status` reports (for example an "allowed_warning" style state, to be confirmed by capturing real events in P1). If it reports no early warning, the governor works from burn-versus-learned-limit (P1 records how much we had used at each wall hit).

### 2.2 The governor's decision

One pure function, easy to test adversarially:

`allowed_tier(task_priority, task_min_tier, limit_state) -> tier | defer`

- `limit_state` is one of `ok`, `tight` (warning seen, or burn above the learned fraction), `walled` (hard limit text, until `resetsAt`).
- `task_min_tier` comes from the routing map (section 3).
- A task runs on `max(task_min_tier, tier the state allows)` only if that tier is *capable* (at or above its minimum). If the state only allows tiers below the task's minimum, the task is **deferred**, never degraded into a wrong answer.

### 2.3 Shedding, by priority

Priority classes (to be confirmed, Decision `shed-order`), highest first:

1. **Live Gil chat.** Never shed. May be moved down a tier only with a visible notice.
2. **Work Gil is waiting on** (an approved ticket build, a merge in flight).
3. **Normal pipeline** (other ticket planners and executors).
4. **Background analysis** (self-improve review, architecture review, auto-fix reviewers, research colony).
5. **Digests and housekeeping** (daily digest, morning brief fetches, bench sweeps).

At `tight`: classes 5 then 4 are deferred and class 3 drops to the cheapest capable tier. At `walled`: only the local rung runs (and only for tasks with a local-capable minimum); everything else is queued with its reason. This is the Apollo behaviour from north star 1: shed low-priority, keep flying. The shed list is shown, never silent.

### 2.4 The fallback ladder and pause-and-resume

`Opus -> Sonnet -> Haiku -> local Ollama (qwen2.5:14b / :7b / :3b per the registry capabilities) -> defer`.

- The ladder is walked **per task**, starting at the task's minimum tier and going *up* only on failure (this is `select_model.py` logic), and going *down* only when the governor says the allowance is tight. A task whose minimum is Opus is deferred, not run on Haiku.
- **Pause:** on `walled`, the governor writes `{state: walled, resetsAt}` to its state. Dispatchers read it before launching (they already consult `rate_limit_backoff`; this generalizes it to per-tier state instead of one account-wide pause, because a wall on Opus may leave Haiku and Ollama open if the limit is per model; to be confirmed by P1's captured events).
- **Resume without polling:** the resume trigger is the first *event* after `resetsAt`: any new request, any dispatcher wake, any app launch re-reads the stored deadline and clears the wall. For work that should restart on its own at the reset, a **single one-shot wake at the stored deadline** (not a recurring timer; one launchd calendar entry or one `setTimeout` to a known instant) re-runs the dispatcher once. A one-shot to a known instant is a trigger, not polling, but the polling guard's allowlist needs one counted, reasoned entry for it; P2 includes that and its test.
- Notices go through the existing single proactive delivery path (ADR 0046): one push when the wall hits (what was shed, when it resumes), one when it clears.

### 2.5 Failure modes the tests must attack (ADR 0063)

Reset text in another timezone or format; a stream with no `rate_limit_event`; clock skew; two machines hitting the wall at different moments (state is per machine, shared view via the existing peer push); the stored deadline in the past or far future; corrupt or missing state file (fail to `ok`, not to `walled`, but log it); a wall that clears early; shedding the task Gil is waiting on; infinite degrade loops; deferred queue growing without bound (cap and surface it).

## 3. Routing per task

### 3.1 Principles

- **The main chat stays the orchestrator.** It talks to Gil, decides, and checks. It does not do bulk work itself when a cheaper tier can.
- **Route per task, not per session.** A topic switch mid-chat is just a new delegation.
- **Minimum capable tier, measured.** Cheapest-first, locked in after 3 straight passes (`select_model.py`), re-earned when a send-back happens.
- **Quality gates the saving.** A cheaper tier only keeps a task if its send-back and gate-failure rate does not rise (north star 1).

### 3.2 Proposed starting map (TO BE MEASURED; nothing here is proven)

Evidence column says what exists today. Anything with "none" is a guess from the task's shape.

| Task type | Starting tier | Evidence today |
|---|---|---|
| Classify, tag, label, extract fields, triage labels | local qwen2.5:7b/14b, else Haiku | Registry maps `local-classify-medium`; Run 12: 14B + RAG at parity on recall (semantic) |
| Recall / lookup in memory or docs | Haiku (local 14B + RAG when exact phrase doesn't matter) | Bench Runs 8, 12, 15: Haiku about equals Sonnet at about 60% cost |
| Summarise, digest, log cleanup, notification text | Haiku | Bench says Haiku suffices for synthesis; real tasks not swept |
| Judge / verify a result | Haiku first; Sonnet if it disagrees with the gate | 44 Haiku judges already run; 33 on Opus; no comparison |
| Ticket label/board housekeeping | Haiku | Interim rule from the ticket says Sonnet; Haiku not tested |
| Routine build from a well-scoped task list | Sonnet (Haiku for the mechanical executor, as today) | Executor is on Haiku in production, with 44 of 115 non-zero exits: **unknown whether Haiku or the task is the cause** |
| Ticket planner | Sonnet | In production on Sonnet; 49 of 124 non-zero exits, cause not split |
| Doc and design writing, grilling, ADRs | Opus | None; north star: wrong design is costlier than tokens |
| Hard debugging, architecture, judgment calls, security review | Opus | None; keep as the ticket's rule |
| Anything unclassified or low-confidence | The session's current tier (conservative default, as `route.py` does for "architecture") | `route.py` default |

### 3.3 Measurement plan: extend `select_model.py` to real daily tasks

`select_model.py` already does the right thing (ascending ladder, 3 consecutive passes, escalate on failure, abort on a rate-limit mid-sweep, preflight quota check). Today it sweeps one bench task directory. Extension, not a new tool:

1. **Task families.** Add bench tasks (same `task.json` format) for the daily types above: ticket label triage, digest summary, log cleanup, judge verdict, routine edit, doc-section draft. Seed each from a *real* past case (a closed ticket, a real log) with the expected result taken from what shipped, per the log-research-behind-decisions habit.
2. **Sweep all families.** A `--family` flag runs the sweep across a family's tasks and writes one row per (family, tier): passes, tokens, cost, latency. Output goes to the #577 store as metric rows, so the map is data, not a doc.
3. **Judge by the real gate where one exists.** For build tasks the pass condition is the repo's own tests plus the merge gate, not a judge's opinion (the judge bugs in Setback 8 are why).
4. **Map file.** A small `config/model_routes.json` (task type to locked-in tier, with the date, N passes and the evidence run). `route.py` reads it. This is the "measured map" the ticket's item 2 refers to. Starting values are 3.2, marked unmeasured until a sweep replaces them.
5. **Re-earn on regression.** A send-back, a gate failure or a failed check on a task type demotes its lock and re-sweeps it, so a lucky 3 passes does not stick.
6. **Cost of measuring.** A full sweep spends allowance. Run it in the Mini's idle time, class 5 priority, and only when `limit_state == ok`, so measuring never causes the wall.

### 3.4 How the main chat delegates, and the per-message hint

- **Delegation.** The Agent tool takes a `model` parameter (`sonnet`, `haiku`, `opus`, or inherit). The orchestrator passes the tier for the task from the map instead of inheriting Opus. For Ollama-capable work it calls a small local wrapper (the registry's capability lookup) rather than an agent. Interim rule from the ticket applies until the map is measured: routine builds, ticket and label work and log cleanups get `model: sonnet`.
- **Hint hook.** `auto_route_hook.py` is a `UserPromptSubmit` hook. Today it fires once per session (state file keyed by `session_id`, via `_already_fired`/`_mark_fired`) and stays silent on `architecture`. Change: fire on **every** message, embedding only, no model call. `route.resolve_intent(prompt, use_embed=True)` already calls `intent_classify` (Ollama `nomic-embed-text` over ChromaDB), so the cost is one local embedding of one short string, no allowance. It prints one line: `task-type: <type>, minimum tier: <tier>, limit: <ok|tight|walled>`, read from the map and the governor state. Silent when the type is unclear (same rule as today).
- **Why embedding-only works:** it never spends Claude tokens, so it cannot make the limit worse. Its weakness is accuracy: the classifier's 87.5% (ADR 0023) was validated on four intents, not on the twelve task types above, so P3 re-validates it on the new set and keeps the keyword fallback.
- **Orchestrator discipline.** The hint is advice. The orchestrator still decides, but P3 logs `(message hash, hinted type, tier actually used)` so we can see how often the hint was followed and whether not following it cost anything. This is also how interactive and subagent rows finally get a task type (1.6 item 1).
- **Failure modes to test:** Ollama down (silent, never blocks the prompt), empty or huge prompt, prompt that tries to inject instructions into the hint line, multi-topic message, the hook racing two sessions.

## 4. Metrics we measure ourselves on again

Computed from events, stored as metric rows in the #577 store (`~/.agents/var/`), shown in Vitals. In Vitals' drill-down map (Health, Machine, Area, Check), **Producers** is the area where each source reports its own outcome; **Energy** is not defined in the #577 plan text on `docs/health-redo-design`, so this plan proposes it as the region for resource-burn metrics (tokens, allowance, local compute) and asks for confirmation (Decision `energy-region`).

| Metric | Computation | Collected on | Region |
|---|---|---|---|
| Output tokens per day, by model and kind | Sum from the ledger (exists) | Transcript change, launch end | Energy |
| Share by tier (Opus/Sonnet/Haiku/local) | Tier output / total output | Same | Energy |
| Allowance used before each wall hit | Burn since the last reset at the moment of a `walled` event | Wall event | Energy |
| Time walled, per week | Sum of (clear time - wall time) | Wall and clear events | Energy |
| Tokens per merged PR, per ticket | Ledger by ticket (exists) divided by merged PRs | PR merge event | Energy |
| Wasted tokens | Output on launches with non-zero exit or `<synthetic>` turns | Launch end | Energy |
| Send-back rate by task type and tier | Send-backs / completed tasks | A send-back or completion event | Producers |
| Gate failure rate by tier | Failed merge-gate or CI runs attributable to a tier | Gate result event | Producers |
| Routing hit rate | Hints followed / hints given; of the ones overridden, how many went worse | Hint log | Producers |
| Shed count and deferral age | Deferred tasks, oldest age, by priority | Governor decision | Producers |
| Local share | Tasks run on Ollama / all tasks (needs Ollama logging, 1.6 item 7) | Local call end | Energy |
| North-star rollup | The ticket's "quality holds at equal or lower cost" test: per task type, did cost fall while send-back and gate-fail rates did not rise | Weekly report from the rows, on demand | Energy |

Each metric names the event that writes it; none is a timer. The only reads that scan are the transcript watch (debounced file events) and the on-demand rollup. Space and time: ledger rows are about 116 bytes each at ADR 0066's measured rate; at the scale in 1.4 (about 1,000 messages a day) that is about 120 KB a day before hourly rollup, and "last N hours of a metric" is an indexed query, not a re-read of transcripts (the #447 rule).

## 5. Phases

| Phase | What | Acceptance test | Size |
|---|---|---|---|
| P0 | **Measure first, no behaviour change.** Add task-type and tier labels to the ledger: tag subagent and interactive rows via the hint log, log Ollama calls, include the Mini's file in one view | A day's rows on both machines show output by (kind, task type, tier) and the totals equal `session_usage.py` within de-dup tolerance; a deliberately bad row does not crash the scan | S |
| P1 | **See the wall.** Capture real `rate_limit_event` samples; record burn at each wall hit; per-machine governor state in the store; `limit_state` function | Replayed real streams give `ok`/`tight`/`walled` and the right `resetsAt`; no event, malformed event, and past/future deadlines each behave per 2.5; polling guard test green | M |
| P2 | **Shed and degrade.** `allowed_tier`, the priority classes, the ladder with local rung, deferral queue (bounded), reset resume, the one allowlisted one-shot wake, one push on wall and on clear | In a simulated wall: class 5 and 4 deferred, class 3 drops a tier, Gil's chat unaffected, local-capable work runs on Ollama, deferred work resumes by itself after the reset, queue cap holds; adversarial cases of 2.5 pass | L |
| P3 | **Per-task routing.** Every-message embedding hint, `config/model_routes.json`, Agent `model` passed from the map, interim Sonnet rule replaced, classifier re-validated on the task types | Hint latency under 300 ms with Ollama up and silent with it down; classifier accuracy on a held-out set of real messages is reported and at least the existing 87.5%, else keyword fallback stays on; a delegation test shows the passed `model` matches the map | M |
| P4 | **Measure the map.** `select_model.py --family`, daily-task bench families, sweep results into the store, re-earn on regression | Every task type in 3.2 has either a locked tier (3 passes) or an explicit "stays at X, reason" row; a forced regression demotes and re-sweeps | L |
| P5 | **Vitals.** Energy and Producers regions show the section 4 rows, with freshness, from the store | Each metric shows a value and its last-event time in the real app (opened and checked per the verify-in-dashboard rule), with a screenshot in the PR; stale data reads as stale | M |
| P6 | **Dry run on the $20 plan.** A shadow week: governor decisions logged but not enforced, then enforced on one machine | Report: what would have been shed, deferred, downgraded; no class 1 or 2 task shed; Gil approves before enforcement | S |

Order follows compounding leverage: P0 and P1 feed everything; P3 can ship before P4 on the interim map; P5 can land alongside any phase.

## 6. Risks, stated plainly

- Haiku and Sonnet may be worse than the bench suggests on real work; the 40% non-zero exits in the pipeline are unexplained and could be a model-capability signal, not noise. P4 splits that before any tier is locked.
- The plan assumes the $20 plan's limit is about one fifth of the $100 plan's. If it is tighter, local Ollama carries more, and local quality on the MacBook is bounded by qwen2.5:14b.
- Per-model limits are assumed possible, not known. If the wall is account-wide, the ladder's "wall on Opus leaves Haiku open" branch never fires, and `walled` means local-only.
- The Energy region is a proposal; it does not exist in #577's text.

## Decisions
<!-- marvin:decisions -->
### state-home: Where does the governor's state and the usage ledger live?
- [ ] A: MARVIN-owned store (`~/.agents/var/`, the #577 store). Move `rate-limit-backoff.json` and `token-usage.json` there, keep a read shim for `~/.claude` paths during the move
- [ ] B: Leave them in `~/.claude` for now and make only the new governor state MARVIN-owned
- [ ] C: Leave everything where it is

### shed-order: Which priority order does the governor shed in? (class 1 chat is never shed)
- [ ] A: As proposed: waiting-on work, normal pipeline, background analysis, digests (shed digests first)
- [ ] B: Pipeline last: shed background analysis and digests, then pause the pipeline before touching Gil's chat tier
- [ ] C: Gil sets a number per job in the dashboard

### chat-degrade: May the live chat itself drop a tier at the limit?
- [ ] A: Yes, with a visible notice, and Gil can refuse
- [ ] B: No, the chat only stops and offers to continue on a lower tier when Gil says so
- [ ] C: Only after the wall, never at `tight`

### ladder-top: Where does Opus run once on the $20 plan?
- [ ] A: Design, hard debugging and judgment only, never subagents or judges
- [ ] B: Same, plus the main chat session stays on Opus
- [ ] C: Main chat on Sonnet by default, Opus only when Gil asks

### hint-scope: How often does the routing hint fire?
- [ ] A: Every message, embedding only (as proposed)
- [ ] B: Only when the topic changes from the previous message
- [ ] C: Only on delegations, not on chat messages

### sweep-spend: How much allowance may the measurement sweeps use?
- [ ] A: Only when `limit_state` is `ok`, on the Mini, idle time, uncapped
- [ ] B: Same, with a weekly cap of a fixed share of the allowance
- [ ] C: Only on local Ollama until the $20 plan starts

### energy-region: Where do the resource metrics show in Vitals?
- [ ] A: A new **Energy** region (as proposed here) beside Producers
- [ ] B: Inside Producers
- [ ] C: Wait for Gil's Vitals layout decision first

### start: Where do we start?
- [ ] A: P0 then P1 (measure and see the wall) before any behaviour change
- [ ] B: P3 now on the interim Sonnet map (fast saving), P0 and P1 in parallel
- [ ] C: Re-plan after the $100 plan's end date is set

### plan-end: When is the $100 plan actually ending? (text) (optional)
