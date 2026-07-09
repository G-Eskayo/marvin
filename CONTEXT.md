# MARVIN — Context Glossary

Domain terms only. No implementation details — see `docs/adr/` for decisions and rationale.

## Intent-vs-reality audit agent (built 2026-07-09 as the `audit` skill)

- **Intent-vs-reality audit**: comparing documented intent (docstrings, ADRs, roadmap `[decision]`/
  `[research]` markers, memory) against actual current system state to find gaps nobody's reported
  yet — distinct from `diagnose`, which starts from a *known* symptom and root-causes it. Same
  underlying move already named in the roadmap's brain-map section (§L, "systematically surface
  where things should connect but don't"), applied to a new surface. Motivating case: the
  2026-07-09 quarantine investigation — `calibrate.py`'s own docstring said `record_label()`'s
  "intended caller" was "the quarantine review workflow, once built," and nothing had ever built
  it. That comparison is exactly this agent's job.
- **Trigger**: reactive, not scheduled or user-invoked-by-name. I (the main conversation agent)
  judge when a moment warrants it — a direct verification question I can't confidently answer, a
  noticed mismatch between something I just read (a docstring, an ADR) and observed system state,
  or Gil expressing suspicion something isn't working as documented.
- **Mechanism**: no new standalone infrastructure (not another `background_review.py`-style
  detached `claude -p` script) — dispatched via the existing `Agent` tool's `run_in_background`
  mode, which already provides backgrounding, its own safety/tool model, and a
  notify-when-complete mechanism. This is a new *skill* (trigger conditions + investigation prompt
  template), not new code.
- **Fix authority**: allowed to apply low-risk fixes, but reuses `auto_fix.py`'s existing
  safety-netted mechanism for that rather than inventing new fix-application logic — the agent's
  job is discovery and classification (is this fixable within `auto_fix.py`'s existing narrow
  safety boundaries, or does it need real judgment?), not new fixing infrastructure.
- **Output routing, by risk tier**: low-risk findings it fixes itself go through `auto_fix.py` and
  land in `auto-fix-log.md`, same as any other auto-fix. Findings needing real judgment (like
  2026-07-09's rubric/prompt fixes — genuine design decisions, not mechanical pattern-matching) go
  to `suggestions.md` for review, unimplemented — no new dedicated findings file, reusing the
  queue that already exists for exactly this purpose.

## Voice client (in design, not yet built)

- **Online mode**: the voice client has connectivity to the Agent SDK backend. Full MARVIN capability — real Claude model, existing skills, memory.
- **Offline mode**: the voice client has no connectivity of any kind (true off-grid — no local network, no cellular, nothing nearby to reach). Falls back to a small local/open-weight model running on-device. Degraded capability — no MARVIN skills, no memory read/write, conversational only.
- **Agent SDK backend**: the server-side process (Claude Agent SDK) that runs the real MARVIN agent loop — skills, memory, tools. Lives on a machine already in MARVIN's Tailscale network (desktop/laptop), not on the phone.
- **Voice client**: the native iOS app itself — the thing that captures speech, talks to the Agent SDK backend when reachable, and falls back to the local model when not.

## Task-dispatch (v1 built and tested; mode 2 built and applied to research-colony)

- **Task-dispatch**: a general primitive for location-transparent work execution across MARVIN's
  known devices — submit a unit of work without specifying which physical machine runs it; the
  system decides based on availability. Deliberately general, not cron-specific — MARVIN's own
  scheduled jobs (research-colony, daily-digest, cross-machine-merge) are the first real consumer
  that validates it, not the whole scope. This is the third leg of the "multiple computers, one
  computer for MARVIN" vision — distinct from data unification (`cross_machine_merge.py`) and
  single-model compute unification (`exo`, splits one model's layers across both machines
  simultaneously). Task-dispatch is about independent, separable units of work, not splitting one.
- **Work unit**: an arbitrary shell command — the maximally general choice. Both known consumers
  (running a cron script; an ad-hoc headless `claude -p` reasoning task, per the NetworkChuck/Terry
  precedent) reduce cleanly to a shell command, so the dispatcher doesn't need special-case
  knowledge of Python vs Claude invocations.
- **Machine selection**: auto-selects by liveness + current load by default, with an explicit
  target override always available (e.g. "run on mac-mini specifically because the model's already
  cached there," as happened during today's exo work).
- **Dispatch-state file**: a small local JSON file each machine maintains (`busy`, `task`,
  `started_at`), written by the dispatch-runner itself when a dispatched task starts/finishes. The
  remote dispatcher checks it over SSH before selecting a machine — precise about "is this machine
  running something *dispatched*," deliberately not raw OS-level CPU/memory load, which would need
  an arbitrary busy-threshold with no real data behind it and would flag unrelated normal use as
  "busy."
- **Three dispatch modes, only the first is v1 scope**: (1) **single-target dispatch** — pick one
  available machine, run there, get the result back; the foundation the other two need, and the
  only mode designed/built in this pass. (2) **fan-out + merge** — run the *same* task on *both*
  machines independently (diversity of results, not failover — two independent runs can surface
  different findings), collect once both finish, merge/dedupe/reprioritize by reusing
  `cross_machine_merge.py`'s existing LLM-merge logic directly. (3) **exo-scheduled dispatch** —
  for work needing genuine split compute (not just parallel independent runs), route through `exo`,
  with real scheduling/visibility so it can be monitored happening, not silently kicked off. Modes
  2 and 3 are logged as the immediate next extensions, deliberately not built now — single-target
  dispatch's interface should stay composable enough that they layer on without reworking it.
- **Result handling (single-target dispatch)**: supports both — fire-and-forget for cron-style
  replacement (the dispatched script writes its own output, e.g. research-feed, nothing needs to
  block waiting), and synchronous wait-and-capture for an interactive ask ("run this on whichever
  machine's free and tell me the result"). Caller picks per-call, not a global setting.
- **Failure handling**: fails loud, no automatic retry-elsewhere in v1 — if nothing's available, or
  the selected machine drops mid-task, the failure is reported clearly (matches the day's whole
  theme: hook-errors.log, cron-health.md, quarantine.md all exist because silent failure is the
  recurring real problem). No auto-retry because arbitrary shell commands aren't guaranteed
  idempotent — retrying blind risks double-running something that shouldn't run twice.
- **v1 build scope**: the dispatch primitive itself, proven against a real test task — not a
  rewiring of the existing cron jobs (research-colony, daily-digest, cross-machine-merge) to use
  it. Migrating live, currently-working production jobs onto a same-day, freshly-built mechanism is
  real risk for no immediate benefit; prove it solid first, migrate one job at a time later.

### Fan-out + merge (mode 2), first application: research-colony

research-colony already runs independently on both machines (two separate launchd triggers, 09:00
daily) — this is redundant *by design*, not a bug: Gil wants two independent runs specifically
because "having two different agents doing it each day could mean we get more valuable
information." `cross_machine_merge.py` already merges the resulting research-digest via an LLM
pass, but on a **fixed 30-minute buffer** (fires at 09:30, just hopes both machines finished by
then) — a real, current fragility, not a hypothetical one.

- **Orchestration shape, resolved 2026-07-08**: layer on top of the existing independent triggers,
  don't replace them with a single orchestrating dispatch point. A single orchestrator would be a
  new single point of failure for *triggering* — if it's asleep, work wouldn't start anywhere that
  day, which is worse than today's actual resilience (both machines already try independently
  regardless of the other's state).
- **Completion signal, resolved 2026-07-08**: event-driven, not polled. Each machine's research-
  colony run executes through task-dispatch's local self-targeting (gets busy/done tracking for
  free via the existing exit-trap mechanism, zero changes needed to `run_colony.py` itself). That
  same exit trap, on completion, checks the *other* machine's dispatch-state: if it's also done,
  trigger the merge right then — "last one out closes the door," no fixed wait, no polling loop. If
  the other isn't done yet, do nothing; its own completion-check will catch the both-done condition
  when *it* finishes.
- **Merge authority stays fixed**: the merge itself always runs on the stationary machine (Mac
  Mini), matching `cross_machine_merge.py`'s existing rule. If the MacBook Pro is the one that
  finishes second, it dispatches the merge *to* the Mac Mini via task-dispatch rather than running
  it locally.
- **Fallback safety net**: the existing 09:30 scheduled trigger stays, but becomes a backstop, not
  the primary mechanism — it checks whether today's merge already happened via the event-driven
  path (an existence check on the expected `{date}-merged.md` output file guards against double-
  triggering) and only acts if it hasn't, proceeding with whatever's available, same graceful-
  degradation behavior `cross_machine_merge.py` already has for a genuinely unreachable machine.

## Citation-graph knowledge base (in design, not yet built)

- **Seed paper**: the paper a citation-graph traversal starts from — all relevance scoring is
  similarity-to-seed, not similarity-to-parent-node.
- **Reference edge**: a backward link — a paper the current node cites. The primary-source
  backbone of the traversal.
- **Citation edge**: a forward link — a paper that cites the current node. Situational context
  (what got built on top of this), not primary substance.
- **Relevance floor**: the minimum embedding-similarity-to-seed a candidate paper must clear to be
  expanded at all. Shared across both edge types.
- **Result-intent bypass**: a citation Semantic Scholar tags as substantively engaging with the
  seed's findings (as opposed to a passing "background" mention) is pulled in regardless of its
  rank against the top-K cutoff — an imperfect but real safeguard against silently dropping
  rebuttals.
- **`paper-knowledge` collection**: the persistent ChromaDB collection storing every paper ever
  ingested via any citation-graph traversal, across all investigations — the visited-check that
  prevents re-fetching/re-embedding a paper already known queries this collection, not a
  per-traversal temporary set.
