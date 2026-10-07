# MARVIN — Context Glossary

Domain terms only. No implementation details — see `docs/adr/` for decisions and rationale.

## Session continuity (in design, 2026-07-12)

- **Session bridge**: every Claude Code session's transcript includes a `bridge-session` entry
  (`bridgeSessionId`, matching the `claude.ai/code/session_...` URL format) — real, but confirmed
  by direct test to be a one-way link for the web/mobile monitoring view only. It is **not** a
  mechanism the CLI itself uses to resume a session cross-machine: `claude --resume <id>` and
  `claude agents --json` were both tested from MacBook Pro against a session that only exists on
  Mac Mini — both came back empty/not-found, purely local-file/local-process lookups. Ruled out as
  a shortcut; genuine custom automation is needed for cross-machine continuity.
- **Session transcript**: the local, per-session `.jsonl` file under
  `~/.claude/projects/<slugified-cwd>/<session-id>.jsonl` — deliberately excluded from `~/.claude`
  code sync (90MB+ of raw, private, per-session history; see [[0022]]'s `.gitignore` scope).
  Distinct from a **handoff doc** (`~/.claude/handoffs/*.md`), a hand-authored summary + resume
  prompt, which *is* synced.

## Code sync (built 2026-07-09/12 — distinct from cross_machine_merge.py's data sync)

- **Code sync**: keeping a git repo identical across MARVIN's known machines via git
  commit/push/pull, run through `code_sync.py` — distinct from **data sync**
  (`cross_machine_merge.py`), which unifies *runtime output* (qa-knowledge, research-feed,
  digests) via SSH/ChromaDB transfer, not git. The two solve structurally different problems
  (one machine's code should be everyone's code; one machine's *findings* should be everyone's
  findings, but by union/merge, not overwrite) and are not meant to share a mechanism. Two repos
  use it: `~/.agents` (GitHub remote) and `~/.claude` (a curated, allow-listed subset — memory,
  CLAUDE.md, commands, handoffs, shared backlogs — self-hosted remote, see below).
- **Bidirectional**: either machine can commit and push — no single "authoritative" machine for
  code, unlike data sync's fixed merge authority (always the stationary machine). Chosen because
  the actual goal is "work on either machine, it doesn't matter which" (the "one computer, two
  machines" vision), not because work is currently split evenly — as of today nearly everything
  happens on the Mac Mini, but the design shouldn't assume that stays true.
- **Scoped commit exception**: an explicit, narrow carve-out from the standing "never commit
  without being asked" rule (`CLAUDE.md`'s Git Safety Protocol) — automatic commit+push is
  permitted, but *only* for the two synced repos, in service of not having to manually remember
  to push after every session. Not a general loosening of the rule elsewhere.
- **Sync-log transparency**: every auto-commit, auto-push, and auto-pull writes to
  `~/.claude/sync-log.md`, checked at session start — mirrors the existing `auto-fix-log.md`
  pattern (autonomous action, no approval gate, but nothing happens silently).
- **Self-hosted sync** (`~/.claude` specifically): no third-party remote — Gil's direction was
  unambiguous ("always go with the more secure approach when it comes to sensitive information").
  A bare git repo on Mac Mini (`~/.claude-sync.git`), reached over Tailscale/SSH like git worked
  before hosted services existed. `~/.agents` keeps its GitHub remote (skill code, lower
  sensitivity); `~/.claude` holds personal memory and would otherwise put `.claude.json`-adjacent
  content at third-party risk.
- **Conflict-marker guard**: `push()` scans every changed file for literal `<<<<<<<`/`=======`/
  `>>>>>>>` lines before committing, and refuses (logs + notifies, commits nothing) if any are
  found. Exists because a stash-pop conflict can leave markers sitting in a working-tree file, and
  without this check the *next* automated push — including an unattended daily cron — would
  commit and propagate that corruption with nobody watching. See [[0022]] for the real incident
  that motivated this.

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

## MARVIN Mobile (in design, not yet built)

- **MARVIN Mobile**: the project and naming-convention name for MARVIN's native iPhone app — used
  for the repo, docs, tickets and code identifiers. Not what the user sees: the installed app's
  display name is just **MARVIN**. One app, not several — it supersedes the separately-scoped
  "voice client" from July 2026 and the roadmap's WhatsApp/Telegram companion idea.
- **Surface**: one of MARVIN Mobile's three top-level ways in — **Voice**, **Chat**, **Dashboard**.
  All surfaces talk to the same mobile backend; a surface is a view onto MARVIN, not a separate agent.
- **Voice**: the spoken surface — speech in, speech out. What July's ADRs 0001–0005 called the
  "voice client" is now this surface, not a standalone app.
- **Chat**: the typed conversational surface — what the WhatsApp/Telegram companion idea was
  reaching for, delivered natively instead of through a third-party messenger.
- **Dashboard**: the phone's view of what the desktop dashboard shows. Same data, phone-shaped
  layout — not a pixel copy of the Electron app.
- **Mobile backend**: the process on a machine in MARVIN's Tailscale network (not on the phone)
  that the app connects to for full MARVIN — real Claude model, skills, memory, dashboard data.
- **Thread**: the single continuous MARVIN conversation on the phone, shared by Chat and Voice
  (a spoken exchange shows up as text in the same Thread). Proactive messages from MARVIN land
  here too. There is one Thread, not a list of conversations.
- **Session** (in the MARVIN Mobile sense): one underlying Claude Code session behind a stretch of
  the Thread. The backend rotates to a fresh Session on topic shift or length, carrying a short
  summary forward; Gil sees one Thread, never the rotations. Every Session is a normal Claude
  Code session, resumable from a terminal. Thread ≠ Session: one Thread, many Sessions over time.
- **Proactive delivery**: the one path by which MARVIN reaches Gil unprompted — into the Thread,
  with a push. Owns quiet hours, batching and the acted-on/ignored record. Every proactive message
  goes through it regardless of what caused it.
- **Trigger**: a thing that hands a message to proactive delivery. Event triggers (PR ready,
  ticket needs an answer, health issue, digests ready) and the calendar-gap trigger (a lull in
  Gil's schedule) are both triggers; neither is a delivery mechanism of its own.
- **Quiet hours**: sunset to sunrise at the phone's current location. Non-urgent messages are held
  and batched until sunrise.
- **Urgent**: a message allowed through quiet hours — health failures that would otherwise leave
  MARVIN (or the phone's connection to it) broken overnight. Everything else is non-urgent.
- **Online mode**: the app can reach the mobile backend. Full MARVIN capability.
- **Offline mode**: no connectivity of any kind (true off-grid). Falls back to a small
  local/open-weight model on the phone. Degraded — no skills, no memory read/write, conversational only.

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
- **Primary automation host** ([[0032]], 2026-09-01): `ticket-pipeline`'s own scanning cron moved to
  mac-mini (always-on) rather than macbook-pro (sleeps/closes between naps) — `select_machine()`
  itself needed no changes, since it was already machine-agnostic. `dashboard-webhook` runs on both
  machines until G-Eskayo/marvin#112 (env-aware webhook URLs) ships and makes consolidating it onto
  mac-mini actually safe.

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

## MR pipeline (in design, 2026-08-19)

- **MR pipeline**: the mechanism by which MARVIN's own autonomous/background-initiated work (self-
  improve sweeps, daily-digest/research-colony findings, anything that currently lands in
  `suggestions.md`/`quarantine.md`) gets carried through requirements → design → tasks → sandboxed
  implementation → a pull request, so Gil's review step becomes "approve/adjust/deny a real diff"
  instead of "approve/adjust/deny a prose suggestion." Explicitly does **not** cover live,
  interactive coding sessions — those stay direct-to-working-tree, since Gil is already hands-on by
  definition whenever he's driving the conversation.
- **Ticket backbone**: the MR pipeline's ticket layer is built on the existing, already-wired-but-
  never-turned-on GitHub Issues system on the `~/.agents` repo (`G-Eskayo/marvin`), using the
  `to-prd`/`to-issues`/`triage` skills as-is rather than a new bespoke store — `to-prd`'s User
  Stories section, `to-issues`'s HITL/AFK tracer-bullet breakdown, and `triage`'s state machine
  already cover most of what this pipeline needs; it extends rather than replaces them.
- **Sandbox isolation** (tentative default, not explicitly re-confirmed after the conversation moved
  to metrics — revisit if this turns out wrong): git worktree isolation (`EnterWorktree`/
  `ExitWorktree`), not a full VM/container per run. Protects code; does NOT automatically protect
  shared local state (ChromaDB collections, `settings.json`, launchd/cron) — a given ticket's
  verification step is responsible for copying/stubbing whatever shared state it actually touches.
- **Verification / trust mechanism**: before an MR is ever raised, the agent runs inside the sandbox
  in a tune-and-compare loop against **per-subsystem living metrics files** (formalizing the
  `bench/RESULTS.md` pattern route.py's classifier work already uses — baseline, change, re-measure,
  iterate until it's actually better, not just different), indexed from one lightweight central
  pointer file. This comparison is what makes the MR trustworthy regardless of which model produced
  the diff — trust lives in the verification step, not in the model tier.
- **Execution model tier**: flagship Claude models (Sonnet/Opus) handle planning (ticket → PRD →
  design → tasks); execution of the tasks themselves defaults to **Haiku** for now (same harness,
  ~60% cheaper, already wired via `route.py`'s routing table) — true local/Ollama-driven execution
  is deliberately deferred to a v2 effort, since no tool-using harness exists yet that can drive an
  arbitrary local model through file edits/tests/git (this is the same still-open
  "model-adaptive harness" `[decision]` already sitting in `marvin-roadmap.md` §D). Not folding that
  build into this pipeline's critical path.
- **MR-ready notification**: uses the existing `PushNotification` tool (Remote-Control-connected →
  pushes to Gil's phone) rather than a new dedicated bot — confirmed by Gil to already fire
  correctly from cron-triggered background jobs, not just live interactive sessions. No Telegram/
  WhatsApp bot needed unless this stops being sufficient later.
- **Approve action**: the MR-approval dashboard is a trigger, not a queue — clicking approve fires
  an n8n webhook that runs `gh pr merge` directly, no live Claude session required for the merge
  itself. "Deny"/"adjust" are different in kind (judgment calls, not mechanical actions) and still
  need their own resolution.
- **PR evidence schema**: every MR-pipeline PR — whether autonomously raised by `mr_raiser.py` or
  manually raised via a live ticket-pickup session — follows one fixed, structured body format
  (metrics comparison, test results, dev-environment evidence, links back to the originating
  ticket's requirements/design rather than duplicating them into the PR itself), so the dashboard's
  MR-review detail view has exactly one shape to parse regardless of how a PR came to exist. v1
  requires every section present on every PR. A later iteration is expected to make section
  requirements *adaptive per-ticket* — e.g. a future n8n classifier node deciding a pure backend
  ticket doesn't need dev-environment evidence — but that's explicitly deferred, not designed now:
  build the fixed structure first, make it adaptive later.
- **Dashboard hosting, revised**: not Claude Artifacts (cloud-hosted) after all — Gil's direction is
  a **natively-run app on both machines** (Mac Mini + MacBook Pro), since the metrics data is
  already local; no reason to round-trip it through the cloud. The MR-review dashboard and the
  metrics scorecard are converging toward **one app with multiple tabs**, explicitly expected to
  grow a third tab for MARVIN activity/log detail and evolve into a general MARVIN health-check
  monitor over time — purely functional (checking on what MARVIN is doing, legible to a lay person).
  Distinct in purpose from `brain-map` (giving MARVIN a sense of life/growth to watch over time as a
  companion visualization) — neither replaces the other, but they're allowed to converge or relate
  as part of the same larger story of MARVIN over time, not walled off from each other by default.
  The anticipated third tab is now in progress as the "Activity" board (G-Eskayo/marvin#109's PRD)
  — the GUI itself still runs on both machines as originally decided here; only its webhook/refresh
  data-source URLs become device-aware ([[0032]]), not the app's own location.
- **Dashboard tech stack**: Electron + React, matching [[project-finance-os]] (Gil's other native
  app) — chosen specifically for cross-platform portability as more machines join MARVIN's known
  devices, e.g. [[project-third-node-kali-hackintosh]]'s deferred Linux node. Portability applies to
  the UI shell; the data layer underneath (launchd vs. a Linux scheduler, OS-specific paths) would
  still need real per-OS handling whenever a non-macOS node actually comes online — not solved by
  the framework choice alone.
- **Ticket trigger**: `suggestions.md`/`quarantine.md` stay exactly as they are today — the cheap,
  lightweight pre-ticket triage stage for every raw finding from `self-improve`/`daily_digest`/
  `research-colony`. Promotion into a real GitHub ticket (which kicks off the full requirements →
  design → sandbox → MR pipeline) reuses their **existing** priority sort and `tau` calibration as
  the automated threshold — no new scoring mechanism to build, and no manual per-item "make this a
  ticket" step, per Gil's direction to automate start-to-finish. Gil's real checkpoint stays the
  MR-approval dashboard, not a pre-promotion gate.
- **Build-type ticket**: a ticket implementing something that didn't exist before (a new feature,
  tab, flag) — there is no prior baseline to improve on. Distinct from a **tunable-subsystem
  ticket** (e.g. improving route.py's classifier accuracy), where a real before/after metrics
  comparison is the natural verification. A build-type ticket's "passing" gate is mechanical
  (tests pass, build is clean, nothing else regressed) rather than a metrics-improvement
  comparison — resolved 2026-08-28 to keep `metrics_registry.compare()`'s single interface
  (verdict must be "improved" to pass) usable for both cases without forking it, by feeding it a
  trivial pass/fail-shaped metric for build-type tickets rather than adding a second code path.
- **MARVIN quality/usage tracking** (separate open thread, not part of the MR pipeline): ambient
  tracking of how well MARVIN performs and how much it's actually used across *every* Claude Code
  session — not just headless ticket runs. Explicitly distinct from a build-type ticket's
  passing gate (one PR's tests vs. MARVIN's overall behavior). Nothing collects this data today.
  See [[project-marvin-tool-invocation-metrics]] (memory) — the same idea, raised independently
  during an earlier Instagram-triage session the same day. Deserves its own dedicated design pass,
  not a tangent inside the MR pipeline's build.
- **MARVIN version**: one combined semver identity for the whole `~/.agents` repo (not per
  component — the dashboard app's own `package.json` version is separate, not yet reconciled with
  this), read from a root `VERSION` file. Bump type comes from the merged ticket's labels
  (`enhancement` → MINOR, `breaking-change` → MAJOR, neither → PATCH), not from a human decision at
  merge time — resolved 2026-08-28 specifically because Gil wants something a human recognizes as
  a version, not a raw commit SHA. A `CHANGELOG.md` entry (title + PR link, human-readable) is
  generated alongside every bump.
- **Ticket design doc / task list**: the planning artifact a ticket's execution phase produces
  before writing any code — grounded in the current state of the files it expects to touch (read
  fresh, not guessed), covering the ticket's "What to build" and every acceptance criterion. A
  task list is derived from it, and execution works from that task list rather than a raw prose
  plan. Both are committed as files inside the ticket's own worktree/branch — part of the PR diff,
  reviewed by the same merge-time gates as the code (see [[0029]]) — not written direct to
  `CONTEXT.md`/`docs/adr/` the way a live grilling session does it. Resolves issue #69's question
  ("design the designing"), scoped specifically to `ready-for-agent` tickets.
- **Guiding framing**: the whole pipeline is explicitly meant to work like the scientific method —
  suggestion/quarantine finding = hypothesis, sandboxed execution = controlled experiment,
  metrics-comparison (see Verification/trust mechanism above) = measurement, the MR = the write-up,
  Gil's approve/deny = peer review. Not just a metaphor — it's the actual justification for why the
  sandbox and the metrics-comparison step both exist as hard requirements, not nice-to-haves.

## Dashboard app — Files tab (in design, 2026-08-27)

- **Files tab**: a read-only viewer tab in the MARVIN dashboard (`~/.agents/dashboard`, alongside
  the already-shipped Metrics and MR Review tabs) for browsing files MARVIN produces as
  deliverables. Not a general filesystem browser and not an editor — those were both explicitly
  ruled out early. Kept as its own tab rather than folding into the planned "MARVIN activity/log"
  progress view (G-Eskayo/marvin#82) — the two serve different jobs: the Files tab shows *what
  MARVIN produced*, the activity tab (not yet built) shows *what MARVIN is doing*.

## Health monitoring (in design, 2026-10-01)

- **Check**: a single, named assertion about one piece of MARVIN's own infrastructure (a token
  file, a ChromaDB collection, a dispatch lock, a cron job) that resolves to a severity plus a
  human-readable detail message. The atomic unit of the whole system — everything else (coverage,
  the dashboard tab, the anomaly layer) is built out of a growing list of these.
- **Severity**: a check's result, one of five states. 🔴 **red** — actively broken right now.
  🟡 **yellow** — degraded or stale-by-design (e.g. a documented fallback is in use), not broken.
  🟢 **green** — verified healthy as of the last run. ⚫ **unmonitored** — a real, discovered piece
  of infrastructure with no check registered for it at all; distinct from grey, since it isn't a
  staleness problem, it's a coverage gap. Grey is not a fifth discrete severity — see Staleness
  gradient.
- **Staleness gradient**: a visual dimension layered on top of a check's last-known severity, not
  a severity itself — as `now - last_checked` grows past that check's own declared tolerance, its
  color desaturates toward grey. A check that has never run at all renders as pure grey with no
  color underneath. Each check declares its own tolerance (a daily cron check tolerates a day; a
  storm-detection check should grey out within ~30 minutes) — decoupled from how often the
  scanner itself runs.
- **Coverage**: the fraction of MARVIN's actually-existing infrastructure (every real launchd job,
  every registered machine, every synced repo) that has a matching check registered, computed by
  enumerating those sources directly rather than against a hand-maintained list — the existing
  `cron_health.py`'s `JOBS` dict is the cautionary example: 5 hand-listed jobs against 14 real
  ones, silently missing `ticket-pipeline` the entire time it was spiraling. Coverage closes gaps
  in *named, enumerable* things; it cannot discover a category of failure nobody has instrumented
  at all (the unmonitored marker only fires for things the system can see exist).
- **Numeric-anomaly check**: a check that emits a tracked number (not just a severity) — a
  comment-posting rate, a log-growth rate, a process count — recorded as a time series via
  `metrics_registry.py`'s existing baseline/current/compare primitive (previously used only for
  ticket code-quality metrics). Flags a sharp deviation from the metric's own rolling baseline
  generically, without anyone having pre-written a rule naming the specific failure shape — how a
  ticket retry storm's comment-velocity spike would be caught without a "storm detector" ever
  having been written.

## Dashboard app — Docs tab (built 2026-10-01)

- **Docs tab**: a read-only, cross-project viewer onto `CONTEXT.md` + `docs/adr/*.md` + `README.md`,
  rendered as formatted markdown, for every repo across the whole GitHub account that actually has a
  `CONTEXT.md` at its root — auto-discovered the same way Health tab coverage is (an enumerated
  inventory, not a hand-maintained list), not just MARVIN's own docs. Distinct from the Files tab
  (which shows MARVIN's own generated *deliverables* in `~/.claude/outbox/`) — this shows each
  project's *design history*, sourced live from GitHub rather than the local filesystem so it reads
  identically regardless of which machine happens to have which repo cloned locally. v1 is markdown
  only; Jupyter notebook rendering is deliberately deferred until a real project actually produces
  one, and when it lands it's meant to be full-fidelity (rendered plot/image output), not a
  text-only reduction.

## Dashboard app — Activity tab: backlog + queue (in design, 2026-10-01)

- **Activity tab scope**: the single place for the whole ticket-pipeline picture — the backlog, the
  live queue order, what each device is doing now, and per-ticket stage timelines/cost. Supersedes
  the standalone scope of #115 (per-device columns), #117 (unclaimed backlog), #118 (MR-origin
  device); all three were reopened 2026-10-01 after being closed in error (only #113/#114/#116 had
  actually shipped).
- **Queue order**: the order `ticket_pipeline.py` would actually dispatch tickets — today oldest
  `createdAt` first among `ready-for-agent` tickets with no `claimed:*` label. **Decided: read-only
  for v1, but the data shape carries an explicit per-ticket `position`/`priority` field now**, so
  adding steering (reorder/pin from the dashboard, with the scanner honoring it) later is purely
  additive. Deliberately not building steering before the queue has been seen and judged worth
  steering. The read-only view must be derived from the same selection logic the scanner uses
  (one source of truth), not a second hand-written sort that can drift from real dispatch.

- **Backlog sections** (decided 2026-10-01): four labeled sections, in dispatch order — **Running now**
  (claimed + in flight), **Queue** (eligible: `ready-for-agent`, no claim, in the order the scanner
  would pick), **Parked** (failure-capped or awaiting a human, each with its reason and failure
  count), **Not ready** (open but not yet `ready-for-agent`). Parked work must be visible: today's
  12 parked tickets were only discoverable by reading raw issue comments, the same silent-failure
  shape as PR #119 before the MR-Review fix.
- **Multi-project tickets (known gap, planned next version)**: each project should have its own
  ticketing, but the pipeline is single-repo today — `ticket_pipeline.py`/`run_ticket.py` hardcode
  `REPO = "G-Eskayo/marvin"`, so e.g. killer-sudoku's open issues never dispatch. v1 of this tab
  stays single-project but every ticket record carries its `repo`/project key from the start, so
  grouping by project is additive, not a rewrite (same reasoning as the steering-ready `position`
  field above).

- **Ticket source** (decided 2026-10-01): each project declares where its tickets live — GitHub Issues
  (MARVIN, killer-sudoku, clarity-captions) or a persisted markdown task list (finance-os, local-only
  by design because it holds real financial data). The Activity tab reads every source through one
  interface and renders them identically. **finance-os is a first-class source, not excluded.** v1
  builds only the GitHub reader; the interface exists from day one.
- **Portfolio orchestration (new design thread, not Activity-tab v1)**: Gil runs several large
  projects and many small ones concurrently, and wants the orchestrator to allocate machine/token
  capacity across *all* of them so progress is made everywhere, not one-at-a-time (see memory
  `feedback-parallel-progress-not-strict-sequencing`). **Due dates become a first-class concept** in
  the system — until now nothing in a ticket record expresses time. Ticket records carry an optional
  `due` field from v1 (same additive reasoning as `position` and `repo`); what a due date *means*
  to scheduling (hard vs. soft, per ticket vs. per project/milestone) is still open — to be grilled
  separately, not decided here.

- **Due dates** (decided 2026-10-01): a due date carries a `hard`/`soft` flag, chosen per item,
  defaulting to **soft** so nothing becomes urgent by accident. *Hard* = fixed date (e.g. the
  captioning app, 2026-10-25): the orchestrator works backward from it, warns loudly when at risk,
  and shifts capacity toward it. *Soft* = raises priority as the date nears but never pre-empts
  other work. **A date can sit on a project or on a ticket** (the hard/soft flag stays per item, not
  tied to level -- small projects have no project/ticket split, and a hard date can belong to a
  one-off item). A ticket's **effective due date** is the earlier of its own date and the date
  inherited from its project, and it inherits that date's hardness -- the orchestrator needs per-ticket
  urgency worked backward from a project date, so a date stored only on the project would give it
  nothing to prioritize tickets with. Hard-on-project / soft-on-ticket is the default *emphasis* in
  the UI, not a rule. Decided 2026-10-01; milestone-level dates deferred.

## Dashboard app — Project boards (Jira-style, decided 2026-10-03)

Gil's ask: when MARVIN starts working on any project it creates a board for it, and every ticket
its ticketing system creates shows up there with drill-down status. Boards live in the Activity tab
(the per-project board is the main view; the old flat pipeline list stays as a "Pipeline log" view).

- **Board = registry entry + derived view, never stored tickets.** `~/.claude/boards/registry.json`
  (per-machine: `~/.claude` syncs on a default-deny allow-list and this file is NOT on it, so each
  machine's discovery builds its own; decisions like due dates live in the shared catalog overrides) lists `{repo, name, addedAt, due?, dueHard?}`. Tickets are always
  read live from the project's tracker (GitHub Issues + PRs today; source interface for the finance-os
  task list later), so a board can't drift from the real tickets. `lib/board_registry.py:ensure_board()`
  is idempotent; `ticket_pipeline` calls it on claim and `to-issues` calls it after filing, so "MARVIN
  starts working on a project" creates the board by construction. Seeded: marvin, clarity-captions,
  killer-sudoku.
- **Columns (derived by one pure function, `dashboard/electron/main/board.js`, first match wins):**
  1. **Done** — issue closed.
  2. **In review / testing** — an open PR closes the ticket (PR body `Closes #n`), or the last
     pipeline stage is verifying/gate/merging. Card shows the PR link and whether the PR carries
     Dev Environment Evidence; clicking the PR opens it in the MR Review tab.
  3. **Blocked** — label `blocked`; or `Blocked by #n` in the body with #n still open; or the
     pipeline's last stage failed and nothing is running. Card always states the reason.
  4. **In progress** — `claimed:*` label or a live dispatch, **and** some sign of life: a live dispatch, a
     pipeline stage, or a touch on the ticket within 24h. A claim with none of those is a stale claim and
     sits in Blocked ("Claimed by X but no activity for N days"): a claim label is a statement, not
     evidence (found 2026-10-05: 14 stale claims were showing as "in progress" and also stopping the
     pipeline from dispatching, since it only picks unclaimed tickets).
  5. **Ready** — `ready-for-agent` / `ready-for-human`, unclaimed (badge shows which).
  6. **Backlog** — everything else open (`needs-triage`, `needs-info`, unlabelled).
- **Drill-down**: reason for the column, labels, body, linked PRs, and the per-stage timeline (only
  MARVIN-repo tickets have stage events today; stage storage is keyed by number, so other repos get
  GitHub-derived status only until stage keys carry the repo — additive, noted not built).
- **Open tickets are never crowded out**: open issues are fetched on their own (limit 1000) and only the
  100 most recent closed ones, because a single newest-200 query silently drops the oldest open ticket
  once a repo passes 200 issues. A repo gets a board if it has *any* issue, not only the pipeline label.
- **Titles always travel with numbers** (never a bare `#n`).
- **Nothing here is invoked by hand (decided 2026-10-03, Gil: "the idea is automation").**
  Boards *appear* via `board_registry.discover()` (hourly, inside the `ticket-pipeline` run: any
  non-archived repo of the owner that has the `ready-for-agent` label gets a board) plus the claim and
  `to-issues` hooks. Board *contents* poll GitHub every 60s while the tab is open. The *app itself* is
  rebuilt and relaunched by the 30-min code-sync cycle (`dashboard_rebuild.py`): a change settles for
  15 min, and a running app is rebuilt once it is >=1h behind (was 2h / 24h, which made a new feature
  take up to a day to show). Trade-off accepted: the relaunch drops unsaved in-tab edits (Portfolio).

### Triggers over polling (decided 2026-10-03)

Principle: **trigger at the place state is stored, not at the places it's written** (writers are
unbounded: any chat, either machine, raw `gh`, the GitHub UI). Polling stays only as a backstop.
- **Local state** (`ticket-stages/`, `dispatch-state.json`, `boards/registry.json`): the Electron main
  process watches the files and emits a debounced `activity` trigger to the renderer. Catches Python
  and Node writers alike.
- **GitHub state** (issues, labels, PRs, comments): the webhook-server's change-detector
  (`webhook-server/gh_watch.js`) sends one conditional request per registered board repo every ~20s
  against its most-recently-updated issue (304 = free against the rate limit) and, on change, pings the
  app's `/refresh` port with topics. Real GitHub webhooks were rejected: they need a public URL and the
  one static ngrok domain belongs to Marlin. The events feed was rejected: it lags by minutes.
- **Coverage guard**: the 60s backstop poll compares what it fetched with what it last showed; a change
  no trigger announced is appended to `~/.claude/logs/trigger-misses.jsonl` and surfaces as the
  `triggers:missed` Health check, so a gap identifies itself instead of waiting to be noticed.
- **Not built, deliberately**: a rebuild-on-pull trigger (the sync cycle already rebuilds right after it
  pulls; only the cycle gap + 15-min settle remain) and a Docs-tab trigger (Docs still refreshes by hand).

## Project catalog and the master "Where things are" doc (decided 2026-10-05)

Problem found 2026-10-05: the Docs tab listed 4 projects because it only counted GitHub repos with a
root `CONTEXT.md`; Gil has 18 repos, ~6 non-GitHub project folders, and 17 portfolio-site projects, and
nothing connected them. "Where things are" was only the tidy agent's file-filing report (counts per
`~/Documents` folder), not an index. Related stores that did exist but did not know each other:
`findit` (file name/text search), the memory index, `manifest.json` (skills only), qa-knowledge.

- **One record per project**, generated by `lib/project_catalog.py` from four discoverers: GitHub repos
  (`gh repo list`), local project folders (`~/Documents/Projects`, `~/Developer`, `~/.agents`; the
  children of `experiments/` count as projects), the portfolio manifest
  (`portfolio-website-updater/deploy/other-projects/manifest.json`), and memory notes that mention the
  project. A portfolio entry with no repo (mancala, bug bounty...) is a project in its own right
  (`kind: portfolio-only`), never dropped.
- **Record**: `id, name, kind (repo|local|portfolio-only), repo, visibility, description, localPaths
  (newest clone first), docs{context,readme,adrCount}, tags, status, lastActivity, portfolio{url,title,
  category}, board, memory[] (pointer to memory notes), summary_md (the project card)`. Status is derived
  from last activity (active <=30d, recent <=180d, dormant older, archived from GitHub), never typed.
- **Generated vs decided**: discovery output is per-machine (`~/.claude/catalog/projects.<device>.json`,
  not synced, because local paths differ per machine). Human/MARVIN *decisions* live in the shared
  `~/.claude/catalog/overrides.json` (name, tags, status, ignore, portfolio link, due/dueHard, notes) and
  are merged on read; discovery never writes it. Portfolio entries are matched to repos by slug-token
  overlap (one-to-one, best first); `overrides.portfolio` fixes any wrong match.
- **The master doc**: `_WHERE-THINGS-ARE.md` keeps its filing sections and gains a generated Projects
  section (grouped by status, each with repo, folder, docs, portfolio page, tags) plus pointers to memory.
  The tidy agent asks `project_catalog.py render` for that section when it writes the file.
- **Autonomy**: the catalog refreshes daily with the tidy agent (03:00), hourly inside the
  `ticket-pipeline` run, and on demand (`project_catalog.py refresh`, Docs tab refresh). Health check
  `catalog:fresh` goes amber if this machine's catalog is stale, so silent failure is visible.
- **File search folded in (2026-10-05)**: the Docs search box also runs `findit`'s Spotlight search
  ("Files on this Mac": name matches, then text-inside-file matches) beneath the doc results. One
  implementation: `~/.claude/organize/find_file.py` is now importable (`search()`, `--json`) and the
  dashboard calls it; each file is attributed to the catalog project whose folder contains it (longest
  folder prefix wins), and a click reveals it in Finder (only inside the searched folders). Spotlight
  is per machine and not synced. `~/Developer` was added to its roots (the live clarity-captions clone
  lives there and `findit` never saw it).
- **Docs tab**: lists every catalog project, not just doc-first repos. Each gets a "Project card" page;
  projects with a `CONTEXT.md`/`README.md` show those too (local first, GitHub fallback). The master doc
  appears as its own entry. Cards and the master are searchable.

### Cross-links by project, and Background work (decided 2026-10-05)

- **The project id is the shared key.** Docs (catalog), Activity boards (board registry) and MR Review
  each had their own project list; they now link by the catalog project id (`projectIdOf(repo)` in JS
  matches `slug()` in `project_catalog.py`). Links: project card shows its board counts + "Open board",
  board header "Docs →", MR detail "Docs →" / "Board →", a PR chip on a board card opens that PR in MR
  Review. Navigation is one `nav` object in `App.jsx` that the target tab reads once per navigation.
- **Relationships are derived from text, not stored (decided 2026-10-05, Gil: "connect them relationally,
  not another button")**: `electron/main/relations.js` reads every ticket and PR body, every doc, and each
  PR's changed files, and derives edges: ticket->ticket (blocked by / mentions), ticket->doc ("ADR 0033"
  resolves to that project's `docs/adr/0033-*.md`, also `CONTEXT.md`/`README.md` and explicit paths),
  PR->ticket (closes / mentions), PR->doc (changes / mentions), doc->ticket (`#12`, `owner/repo#12`),
  doc->doc. Edit a doc or a ticket and its relations change with it; nothing to sync. Code fences and
  inline code are ignored. Surfaces: `#12` and `ADR 0033` inside a doc or ticket body are clickable
  (linkify, `dash://` links that stay in the app); a **Related** panel on every doc, ticket and MR lists
  what it points at and what points at it, with each ticket's board column and each PR's state; clicking
  goes to it (doc -> Docs, ticket -> its drill-down, PR -> MR Review). The `to-issues` template has a
  `## Docs` section so links are deliberate. The index is cached 60s and dropped on the activity/docs
  triggers. Not built: section-level links (a ticket naming a heading inside CONTEXT.md), links from
  memory notes.
- **More boards, archive, tags (2026-10-05)**: every active or recent catalog project gets a board even
  before its first ticket (`board_registry.discover(extra_repos=...)`, hourly in the ticket-pipeline run);
  boards of dormant/archived projects sit under a "Dormant boards" menu, kept not deleted. Done shows the
  last 14 days; older closed tickets collapse into an Archive under it. Cards show every label as a tag
  (typed: type / state / claim / priority / other), blockers, age and PRs, and a tag bar filters the board.
- **MR Review spans projects, the merge gate does not.** It lists every registered repo's open PRs (keys
  are `repo#number`; old bare numbers in the seen-file are read as marvin's). Approve/Deny are refused in
  the main process for any non-marvin PR (derived from the PR url, not a renderer flag) because the gate
  rebases in marvin's checkout and runs marvin's pytest/vitest. Other projects show "Review on GitHub"
  until each has its own merge profile (open work: a per-project merge profile; clarity-captions is Swift).
  Found on first run: 4 finance-os PRs (#7-#10) had been invisible because only marvin was listed.
- **Where things live (decided 2026-10-05, Gil's call)**: the **Activity** tab is the project boards and
  nothing else. A ticket's pipeline history (stage by stage, machine, cost) is the drill-down you click into
  on its card; the old standalone "Pipeline log" list is retired. Everything about the *machinery* lives in
  the **Health** tab, in three views: Checks, **Autonomous agents**, **Tool & skill usage**.
- **Autonomous agents** (Health): every launchd agent on the machine (schedule, running now/pid, last exit)
  joined with what it reports about itself. `lib/job_events.py` is the run log for non-ticket jobs (the sibling
  of `ticket_stages`): `@job_events.reported(name)` on a script's entry point records start, steps
  (`job_events.step(...)` from anywhere) and outcome, rewritten after every step, last 20 runs per job in
  `~/.claude/logs/jobs/<job>.json` (per machine, not synced). The job is named from launchd's
  `XPC_SERVICE_NAME`, so a shared script run under two schedules (daily-digest / research-colony) gets two
  logs. Best-effort: recording can never break the job; a clean `sys.exit(0)` is a pass; a run "in progress"
  for >30 min is shown as crashed. All 12 scheduled agents are decorated; the 3 always-on services
  (dashboard-webhook, desktoplive, ngrok) show running/stopped from launchd. Agents that haven't run since
  being instrumented show "not reporting steps yet" rather than looking healthy by omission. Run logs with no
  launchd agent of their own (project-catalog, dashboard-rebuild, tool-usage) appear as sub-jobs.
- **Tool & skill usage** (Health): `lib/tool_usage.py` reads the Claude Code session transcripts
  (`~/.claude/projects/**/*.jsonl`, the same source as the usage-accounting work) and reports, per tool, skill,
  MCP server and subagent type: calls, outcome (ok / error / declined / interrupted / **invalid call** = wrong
  parameters, schema not loaded, unknown skill), last used, a 30-day sparkline, and the interactive /
  headless / subagent split. A MARVIN skill counts as used when loaded via the Skill tool **or** by reading its
  `SKILL.md` (CLAUDE.md's routing table invokes most that way; counting only the Skill tool wrongly said 23 of
  27 never fired, the truth was 10). Rescanned on demand when older than 10 min (~1.5s). **Not measured:**
  whether the *right* skill fired for a request (that needs intent classification against the routing table;
  candidate next step using `route.py`'s classifier). Bash "errors" are non-zero exits and are often expected.

### Ticket agents and the completed record (decided 2026-10-05)

- **Completed work is reference, not clutter (Gil: "how will we know where we are going if we don't remember
  where we have been")**: every project's board has a **Completed** view next to the board: all closed
  tickets (up to 1000, not just two weeks), newest first, grouped by month, searchable and filterable by tag,
  with how long each took and the merged PR that closed it (from its `Closes #n`). Clicking one opens the
  same drill-down (docs it referenced, tickets it relates to). The Done column's Archive is only a
  convenience; this is the record.
- **Four ticket agents** (`lib/ticket_agents.py`, rules in pure `lib/ticket_policy.py`), run inside the
  hourly ticket-pipeline scan across every board repo. They change only **labels and comments**, write every
  change to `~/.claude/logs/ticket-agent-actions.jsonl` with the ticket's labels before (so it is
  reversible), cap at 30 changes per pass, and never touch a `pinned` ticket:
  1. **prioritize** - `priority:p0..p3` from what the ticket unblocks (leverage), project due dates (hard
     outranks soft), bug/breaking, age (capped). Leaves a priority a person set; updates one it set itself.
  2. **triage** - untriaged tickets to `ready-for-agent` / `ready-for-human` / `needs-info` plus bug or
     enhancement, deterministically (sections + acceptance criteria present; no model, no tokens). Skips
     PRDs and claimed tickets. Comments carry the triage AI disclaimer.
  3. **stale_claims** - releases `claimed:*` untouched for 2 days when no PR/branch/rescue ref is in flight
     for it; `held` protects.
  4. **refeed** - a denied or gate-failed ticket (`needs-reengagement`, which nothing used to read) goes back
     to `ready-for-agent` with a note; after 2 re-queues it goes to `ready-for-human`. The planner prompt now
     also reads the ticket comments (`gh issue view --comments`), which is where the denial feedback lives.
- **Modes** (`config/ticket_agents.json`): `auto` = propose until `act_after` (2026-10-12), then act. In
  propose mode an agent lists what it would change and changes nothing; the review screen is Health ->
  Autonomous agents -> Ticket agents. **stale_claims and refeed are pinned to propose** until a person edits
  the config: releasing a claim can re-queue a ticket that was deliberately held (e.g. #115/#117 are
  effectively done by the Activity-tab work and want closing, not releasing), and refeed would open a second
  PR beside the denied one.
- **Dispatcher** (`ticket_pipeline._unclaimed_ready_tickets`): now skips tickets with an open blocker and
  `pinned` ones, and orders by priority then age (unscored counts as middle). It still only EXECUTES marvin's
  tickets: the executor works in marvin's checkout with marvin's test suites. Ready work in other projects is
  counted and shown in the run log ("Other projects ... no execution profile yet") instead of hidden. A
  per-project execution profile (clone path, test command, dev-env) is the open piece for clarity-captions.

### Per-project execution profiles (decided 2026-10-05)

The ticket executor (`sandbox_orchestration` + `run_ticket`) was written for marvin: marvin's checkout,
pytest + vitest, a dashboard screenshot as evidence. A **profile** (`config/projects/<repo>.json`, versioned
in this repo) tells it how to do the same job for another project, so a ready clarity-captions ticket can
flow ticket -> worktree -> implement -> verify -> PR like a marvin one. marvin keeps its built-in path
untouched (it is the "legacy profile"); only repos with a profile file use the profile path.

- **Profile fields**: `repo`, `base_branch`, `clone_hints` (the real clone is found through the project
  catalog's newest local path first), `machines` (eligible device ids), `dispatch` (`"off"` | `"on"`; **starts
  off**: a profile does nothing until a person turns it on), `env` (e.g. `DEVELOPER_DIR` = the first existing
  Xcode, so `swift test` works without `sudo xcode-select`), `executor` (extra allowed tools and context notes
  for the headless model), `verify` (tiers), `evidence`.
- **Verify tiers**: each has `command`, `cwd`, `requires` (capabilities such as `swift`, `xcode`, `xcodegen`),
  a `parser` (`swift-test`, `xcodebuild`, `exit-code`), and `required`. A required tier whose tools are missing
  on the executing machine is an **environment problem, not a ticket failure**: the claim is released, no
  strike is counted and the failure breaker is not fed. An optional tier that cannot run is skipped and said so
  in the PR ("not verified: ...") - verification is never silently weaker than it looks.
- **clarity-captions** (measured on mac-mini 2026-10-05): required tier = `swift test` in
  `Packages/CaptionCore` (XCTest, needs full Xcode via `DEVELOPER_DIR`; 61 tests, ~31s warm / ~83s cold).
  Optional tier = Spike app build, which needs `xcodegen`, the 241MB speaker model
  (`scripts/fetch-diarizer-models.sh`) and a signing team, so it is off until those exist. The project's own
  rule (ADR 0010, ticket #17: "the at-the-bottom decision is pure logic with unit tests") puts decisions in
  `CaptionCore`, which is what makes `swift test` a meaningful gate. Evidence: dev-environment screenshot is
  `N/A` (no simulator capture yet).
- **Verified 2026-10-05 on mac-mini against the real clone**: `project_profile.py selftest
  G-Eskayo/clarity-captions` makes a real worktree from `origin/main`, runs the real baseline (`swift test`,
  60 passed + 1 skipped, 0 failed, ~31s) and prints the PR body the pipeline would raise (Metrics Comparison,
  Test Results with a "not verified: Spike app build" note, Dev Evidence N/A), then removes the worktree and
  branch. No model call, no GitHub write. The pipeline's own token has push access to the repo.
- **Found while building it**: `gh issue view owner/repo#17` is rejected ("invalid issue format"); the planner
  prompt now gives the working `gh issue view 17 --repo owner/repo` (marvin's planner had been recovering from
  that error on its own). The failure breaker is now scoped per project (one project's broken toolchain pauses
  only that project's dispatch; a success or a manual clear resets accordingly).
- **Turning it on**: set `"dispatch": "on"` in `config/projects/clarity-captions.json`. From the next hourly
  scan the best ready clarity-captions ticket competes with marvin's by priority then age, is claimed, and runs
  on a machine in `machines` (mac-mini-1) as `run_ticket.py G-Eskayo/clarity-captions#N`. Nothing else changes.
- **Profiles for killer-sudoku and finance-os (2026-10-05)**, both `dispatch: off`, both
  `merge_from_dashboard: true`, both `clone_mode: "pipeline"`. New profile capabilities they needed:
  `clone_mode: "pipeline"` = a dedicated clone under `~/.agents-pipeline-clones/<name>` made with `gh repo clone`
  (cloning killer-sudoku from GitHub took 0.7s; the same repo from the iCloud-synced `~/Documents` copy hung for
  minutes, and a person's working copy should not be the pipeline's base anyway); `setup` steps (run once per
  fresh worktree, skipped when their `creates` path exists; a failed step is an error, a missing tool is
  EnvMissing); a `vitest` parser; `executor.denied_tools` (finance-os forbids reading
  `~/Library/Application Support/FinanceOS` and `~/Documents/Money-and-Admin`). killer-sudoku: `swift test` at the
  repo root (102 tests, Swift Testing, 13s). finance-os: SETUP.md's two-step install (`npm install
  --ignore-scripts`, then Electron's binary, then `@electron/rebuild -f -w better-sqlite3`, because Node 25/26
  cannot build better-sqlite3), plus a fallback that unzips the cached Electron by hand because Electron's own
  installer silently fails to unpack under Node 26; then `npm test` (20 vitest tests, ~10s). finance-os `main`
  has no `test` script yet (it arrives with PRs #7-#10), so verification works on the PR branches
  (`selftest G-Eskayo/finance-os feature/bills-ipc`). killer-sudoku's 8 open tickets were all implemented on
  main by commits that said "(issue #N)" but never closed the tickets; closed 2026-10-05 with the commit named
  in each comment. finance-os's tickets are NOT stale (4 real open PRs, stacked).
- **Turning dispatch on**: Health -> Autonomous agents -> "Projects MARVIN can work on by itself": per project a
  Turn on / Turn off button (a native confirmation when turning on) and a "Test setup" button that runs the whole
  path short of the model and GitHub. It edits only the `"dispatch"` value in `config/projects/<name>.json`.
- **Header working indicator**: was invisible when idle and only knew about dispatch-system tasks. Now always
  shown: what is running on this machine (the dispatched task plus every agent whose run log says it is mid-run,
  with its current step and elapsed time, "+N more"), or "Idle - last: <agent> (<summary>) <ago>". Click goes to
  the agents list. Updates on the 'agents' trigger, with a 10s poll as backstop.
- **First live run (2026-10-05)**: with clarity-captions dispatch on, ticket #21 (third-party notices) went
  claim -> plan -> implement -> verify -> **PR #28** in about 5 minutes: `NOTICE.md`, an About & Credits screen,
  a tested `ThirdPartyNotice` type, an ADR amendment; `swift test` 60 -> 63 passing, 0 failing; the PR says the
  app build was not verified. Two bugs found by running it for real, both mine: (1) the first claim in a project
  that never had a `claimed:<machine>` label failed ("not found"); claims and the ticket agents' labels now
  create a missing label on first use. (2) Two tickets ran at once on one machine: asking for a specific
  machine skips the busy check for the local machine, and the single shared dispatch-state flag is cleared by
  whichever overlapping run finishes first. "Busy" now also means a live `run_ticket` process exists
  (`ticket_pipeline._local_busy`). Also: my own tests were writing realistic ticket numbers into the real
  ticket-stages folder; stage logs are now isolated for the whole suite.
- **MR Review <-> boards, one to one (2026-10-05)**: `relations_service.parity()` pairs every open PR with the
  ticket it closes and that ticket's board column, and checks each ticket filed under "In review" has an open
  PR. MR Review shows it: each card says "closes #N <title>" with the board status (In review / sent back / no
  card / filed elsewhere) and clicking opens the ticket on its board; a summary line says "Matches the boards" or
  lists exactly what disagrees. The board's In-review column says "N waiting in MR Review" and links there; a
  "Waiting on you" strip across all projects (in review, ready-for-human) sits above the project tabs. A denied PR
  stays open but its ticket is now filed under Blocked as "Sent back from review", and MR Review shows the same
  PR as "sent back", so both views say the same thing about it.
- **Cross-project identity**: stage records and the failure breaker were keyed by bare ticket number, so
  clarity-captions #7 and marvin #7 would have collided. Non-marvin tickets are keyed `<repo>-<n>`; marvin's
  keep their plain number (nothing existing moves). `gh pr create`/`gh issue comment` now pass `--repo`
  explicitly instead of relying on the process's directory.
- **Approving and denying from MR Review (2026-10-05)**: the merge gate now reads the profile too. A project's
  PRs get Approve/Deny only if its profile says `"merge_from_dashboard": true`; the webhook enforces that
  itself (not just the screen) and refuses others with `NO_MERGE_PROFILE`. **Deny** needs no profile: the repo
  comes from the PR URL (it used to be hardcoded to marvin for the ticket comment, claim release, label and
  close). **Approve** is `gh pr merge` as before, but when the PR is behind its base branch the gate fetches and
  rebases in the PROJECT's clone against the profile's `base_branch`, then re-runs the profile's required
  checks in that scratch worktree through `project_profile.py verify` (the same measuring code the pipeline
  uses, one implementation); a failure goes back to the ticket as structured feedback (a failing XCTest is
  named). Stage records go to the project's own timeline. marvin-only steps (rebuilding the dashboard app)
  are skipped. If the machine hosting the webhook lacks a tool the required checks need, approve refuses with
  `ENV_MISSING` and does NOT send the ticket back for rework (the ticket did nothing wrong).
  **Verified 2026-10-05 for real**: a branch behind `main` in a local stand-in for GitHub went through the gate's
  own `rebaseAndRetest` in a scratch worktree of a clarity-captions clone, which called the real `verify`
  (real `swift test`, clean, 30s) and pushed the rebased branch; a deliberately broken XCTest came back as
  `GATE_TESTS_FAILED` naming `CaptionCoreTests.ThemeTests/testDarkAndLightBackgroundsAreTold`. The live webhook
  refuses a project with no profile (`NO_MERGE_PROFILE`) and lets an opted-in one through to the merge step.
  Not exercised: a real approve of a real PR (it would merge it). clarity-captions is opted in
  (`merge_from_dashboard: true`) independently of `dispatch`, which is still off.

## Dashboard app — Portfolio tab (2026-10-02/03)

The portfolio site (`G-Eskayo/portfolio-website-updater`, WordPress + Avada) had visible inconsistency
across project pages (measured 2026-10-02: footer cards differing in height and overlapping their heading,
6 GitHub-link wordings / 4 looks, 17 projects sharing 12 thumbnails). Root cause: pages were hand-built,
so nothing enforced parity. The goal is not a nicer tab; it is **plug-and-play site building**: when a new
project is finished, MARVIN can create its page and update the site from a set of rules, with an LLM
involved only where judgment is needed (writing the words, picking a theme) and everything else deterministic.

**Environments.** The **dev site** (localhost:8080) is the pre-production copy of what customers will see:
the place to build and break things. **Production** is what customers see; promotion is Gil's manual act
(a push touching `deploy/` auto-deploys it, so nothing here pushes the portfolio repo). Everything MARVIN builds
writes to dev only.

### Language

- **Element**: one individual kind of thing that appears on the website, defined once: the project card, each
  of the three canonical buttons, the category sidebar, the site header, the page title bar, the Other
  Projects section, the footer, the section heading, each page layout (project, hub, All Projects, content).
  Instances of an element on pages are placements of it, never copies.
- **Element library**: the set of all elements, each with its generalized markup (content replaced by
  placeholders), where its look comes from (which CSS), the rules for using it, and the pages that use it.
  Shown in the dashboard's **Templates** tab exactly as it renders on the dev site, so it is the place to copy
  from. **Built once, by capture**: Gil approved the dev site's look, so each element is captured from the live dev
  site (markup + computed look) and generalized, instead of being re-derived from our own files. After that
  the library is edited deliberately, not re-captured.
- **Site rules**: the machine-readable statement of what a new project or page requires (URL shape, manifest
  fields, which elements in which order, which button where, image requirements). Rules, not prose, so a
  program can apply and check them. Today partly in `templates/design-rules.json` and the generators.
- **Project spec**: the small structured input for a new project (title, category, slug, subtitle, card
  description, body, stack, optional GitHub repo / download file, optional theme). The only thing an LLM
  needs to write.
- **Add-project pipeline**: the automation that turns a project spec into a finished dev-site change by
  applying the site rules and the element library, then checks it with the evaluation.

### Add-project pipeline (target)

1. Validate the spec against the site rules (`plan_new_project`, exists).
2. Render the project page from the project-page layout and its elements (renderer, exists).
3. **Create the page on the dev site** under its category (missing: the generators only update pages that
   already exist).
4. **Append the manifest entry** (missing: this was a copy-by-hand step in the old wizard).
5. Generate the image, let the person choose, apply it (variants, choose, delete, apply, exist).
6. Regenerate the category hub, All Projects and the sidebars from the manifest (exists); the Other Projects
   footer needs nothing, it reads the manifest.
7. Run the evaluation on the new page and the pages it touched (exists).
8. Report: what changed on dev, the manifest diff to review, and what the evaluation found.

Entry points: a dashboard action and a command-line script MARVIN calls (same code). The old interactive "New
project" form was removed from the dashboard on request (templates are a reference, not forms) and **was not
replaced by this automated path**: that gap is what this section closes.

### Components of the tab (as built)

- **Templates** = the element library (read-only reference, live previews, markup to copy, pages using it).
  Today these previews are re-renders of our template files inside a simulated page; the target is the
  captured element itself.
- **Site inventory** = descriptive: what is on the dev site today, crawled live (re-crawled when stale).
- **Guide & rules**, **Evaluation** (deterministic Playwright checks, no tokens), **Images** (generated art
  keyed to slug and theme; every variant kept; choose, delete, apply to dev).
- **Generated hero image**: deterministic art keyed to the project's slug and a chosen theme (a diagram of what
  the project is); existing images are colour inspiration only, never the key photo; uniqueness checked by a
  perceptual hash.

### Task list

1. **Done for the project card (2026-10-03):** captured from the live dev site (`lib/portfolio_elements.py` →
   `templates/elements/project-card.json`): 72 placements on 22 pages, 1 look, 1 geometry, 0 deviations; shown in
   Templates with its look, provenance (which CSS rule sets what), usage and a "verify" button. The capture found and
   fixed two real deviations (legacy per-page CSS overriding the card's padding and min-height; hand-built cards on
   `/distributed-llm-inference/`, now filled by the footer script via `data-category` on the mount).
2. **Done for the card:** parity check (`lib/portfolio_parity.py`): renders the element exactly as the dashboard
   previews it and compares look, geometry and font loading with the captured element. Fails on the old broken preview.
3. **Done for the card:** the evaluator compares every placement (also pages outside the manifest) with the captured
   element: markup, look per part, geometry (`element-markup/look/geometry`), instead of fixed numbers.
4. **Done (2026-10-05):** site rules in one module, `lib/portfolio_rules.py` (categories and hub slugs, required spec
   fields, slug shape, action-button order, image sizes and uniqueness distance, plus the evaluation's thresholds), with
   Gil's overrides in `templates/design-rules.json`. The pipeline, template renderer, apply step, image generator and
   evaluation all read it; tests fail if a consumer grows its own copy. The Guide & rules tab shows the effective rules.
5. **Done:** add-project pipeline (`lib/portfolio_add_project.py`, dashboard "Add project" tab): spec in → unique image,
   page created under its hub, manifest entry appended, hub/All Projects/sidebars regenerated, evaluation run. Proven end
   to end on the dev site with a throwaway project (then removed).
6. **Done for generated pages (2026-10-05):** the hub, All Projects and category-section layouts exist only in
   `templates/*.html`; the generators fill them through `bin/_card.py`, the renderer through `portfolio_templates.py`, and a
   test asserts both produce identical pages. The 9 legacy WP Coder project pages are still hand-built (their cards, GitHub
   links, header and footer already conform; their layout does not).
7. **Done for buttons, header, title bar, sidebar, Other Projects section, footer (2026-10-05):** captured from the live
   dev site into the library (generalized in the page by placeholder rules; per-page state such as the current menu item
   removed; each part records only the properties the element sets; fonts compared by the family drawn). All seven
   dashboard previews match the live site (parity), and the evaluator checks every element wherever it appears:
   100 page/viewport combinations, 0 findings. Capturing them also surfaced and fixed the last legacy GitHub links
   (Anomaly Detection's `href=" https..."` with a stray space, SkineeDipping's WP Coder block). The GitHub rule is now:
   the page has the canonical button; further plain links into the repo are references. Page layouts (project, hub, All
   Projects, content) are still to capture. The download button has no live placement yet (library entry from its template).
8. **Page layouts captured (2026-10-05):** `lib/portfolio_layouts.py` reduces each page's frame to a structure-only skeleton
   (zones in order; embedded elements as tokens; the authored body as one zone; the action row optional) and compares it
   with the template's. Result: hub 3/3 and All Projects 1/1 follow their layouts; project pages 6/17 (the five modern ones
   plus the pilot below); the other 11 are the migration queue, each with its reason, shown as a "legacy layout" badge in
   Site inventory and in the layout's Templates entry.
9. **Legacy migration, pilot done (2026-10-05):** `lib/portfolio_migrate.py` rebuilds a WP Coder "sandwich" page from the
   project-page template: reads hero, title, subtitle, body and the repo link, saves the original (page + WP Coder blocks)
   to `~/.claude/outbox/migrations/<slug>/`, rebuilds, re-wraps the sidebar; `--plan` writes nothing, `--rollback` restores.
   A missing Stack line is reported, never invented. Pilot: Anomaly Detection (rollback and re-migration both exercised).
10. **Legacy migration, batch done (2026-10-05):** 15 of 17 project pages are now built from the layout (5 modern + 10 migrated) (the stacks were taken
   from each page's own text). Guards added: a rebuild that would lose any of the author's words is refused (it stopped two
   pages), the first backup is never overwritten, hard-wrapped text is tidied (WordPress had turned it into mid-sentence
   line breaks), and a leftover "Project Website:" label goes with its link. **Two pages left on purpose:** Helicopter
   Crutches (a long design-process write-up with image/text rows outside the card) and SkineeDipping (a multi-section
   technical write-up). They are a different page type: they need either their sections folded into the card or a second
   "long-form project page" layout in the library: a design decision, not something to automate.

### Long-form project page (decided and built 2026-10-05)

Gil wants more of his projects to be long form: room for diagrams, detail and showing as well as telling. A second project
layout, alongside the short **project page**, built from the same elements (hero, title card, subtitle, Stack line, action
row, Other Projects footer) plus a stack of **sections** after the title card.

- **Layout zones**: hero -> title card (title, pink subtitle, a short LEAD summary, Stack line, action row) -> N sections ->
  Other Projects. A page's layout is chosen by what it needs: short pages stay on the project page.
- **Section**: a centred heading and a body of free-form content, optionally built from the section parts below. Sections are
  the repeating zone; any number.
- **Section parts** (each a library template, so each is copied, not hand-made): **figure** (a full-width image or diagram
  with a caption), **figure row** (image and text side by side, either way round), **callout** (a highlighted note), plus the
  existing paragraph, list and code styles. Diagrams are images (PNG/SVG) or inline SVG.
- **Style** lives in its own stylesheet (`deploy/longform/longform.css`, versioned by mtime like the card's), never inline.
- **Pipeline**: the add-project spec can carry `layout: "long-form"` and `sections`; legacy long pages migrate with
  `portfolio_migrate.py --layout long-form`, which keeps every block of the original (the content-loss guard applies) and
  only standardizes the frame around it. Capture and conformance treat a project page as following EITHER project layout.
- **Built**: `templates/longform-page.html` + parts (section, figure, figure row, callout) in the Templates tab with live
  specimens (a sample diagram included); `deploy/longform/longform.css` + `enqueue-longform.php`; layout capture with a
  `{section}` zone; `portfolio_migrate.py --layout long-form` (keeps every block of a one-block legacy page; the content-loss
  guard applies); the add-project pipeline and the dashboard's Add project tab accept `layout: long-form`, a lead and sections
  (`## Heading` starts a section). Helicopter Crutches and SkineeDipping are migrated: all 17 project pages now follow a
  layout (15 short, 2 long-form).
- **More projects converted (2026-10-05):** `lib/portfolio_longform.py` turns a short project page into a long-form one by
  making each bold heading ("Key Contributions:", "Skills Demonstrated:", "Links:", or a heading tag) its own section;
  lead, title, subtitle, hero, Stack line and buttons carry over; nothing is dropped (guard) and `--rollback` restores. Eight
  pages converted: Anomaly Detection, Regression & Classification, Resume Selector, Random Number, Pipeline, MITRE, Mancala,
  Marketplace Agent (10 long-form pages in all). Left alone, with reasons: Algorithms and Bug Bounty (headings repeat: the
  blocks need grouping by hand) and the five modern pages (Marvin, Paper Dive, Resume Tailor, Killer Sudoku, Clarity
  Captions: short by design, no section structure; they become long-form when they get new content, not by restructuring).

### Element pipeline and the card text box (2026-10-05)

- **One text-box size**: every project card's text box is 300 x 244 px (never within 14px of its photo's borders; narrower only where the photo is) wherever it appears (hub, All Projects, Other
  Projects footer), with the title in a fixed two-line band, the description centred in the space below and Discover pinned
  to the bottom, all on one centre line. 280 is the narrowest desktop column (the hub beside its sidebar at 1100px).
- **Pipeline** (`lib/portfolio_sync_dev.py`, shown and runnable in the Templates tab): repo `deploy/` files -> the dev
  site's own copy (only files that differ) -> regenerate hub/All Projects/sidebars -> capture every element and layout ->
  dashboard-preview parity for every element -> evaluation. Result in `~/.claude/portfolio/pipeline-status.json`.
  Cause it closes: nothing copied `deploy/` to the dev site, and the stylesheet carried a constant `?ver=1.0`, so an edited
  card looked right in one place and stale in another. The version is now the file's mtime, and the dashboard never caches
  dev-site responses.

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

## Pre-dispatch "work already exists" guard (2026-10-05)

`lib/ticket_evidence.py` checks git/PR facts before `ticket_pipeline` dispatches: an open PR, a `pipeline/*` branch or a `refs/rescue/*` ref means **in-flight**; commits on the base branch mentioning `#N` means **looks-done**. Either one removes the ticket from dispatch (logged `skip repo#N`). Unreadable facts fall back to dispatching, so a gh hiccup never stalls the pipeline. The same evidence is shown on Activity cards (`ticket_evidence.py report <repo>` -> `getEvidence` in boards.js, cached 5 min): a chip, and a ready/backlog card's reason says work already exists. A commit that merely *mentions* #N can be a false positive (e.g. a baseline-metrics commit), so it is worded "commit mentions this", never "done".


## Device columns on Activity (2026-10-05)

`lib/device_status.py` gives one row per device in `marvin-network.json`: idle / busy (task) / unreachable. It reuses task_dispatch's readers, but a failed SSH read is *unreachable*, not idle (task_dispatch's own reader treats failure as idle, which is right for picking a machine and wrong for a status view). The dashboard shows them above the boards (`DeviceColumns.jsx`, cached 8s); this machine's column embeds `DispatchStatusBadge`. Closes #115 and #117.

## Merge order and the sent-back loop (2026-10-05)

- **Order:** a PR waits on every OLDER open PR in its repo that shares a changed file (`dashboard/electron/main/pr_order.js`). Derived from the PRs' file lists each time; the MR list shows it, Approve & Merge is disabled with the reason, and `mr:approve` re-checks it in the main process so a stale screen cannot skip it. Deny stays available.
- **Merge state survives navigation:** `merge_ops.js` holds each PR's merging / re-engaged / error state in the main process.
- **Sent-back loop (closed, Gil chose the in-place option):** a `needs-reengagement` ticket is re-dispatched even though its first attempt's PR/branch/rescue ref exist (the existing-work guard exempts those, but not commits already on the base branch). The executor rebuilds `pipeline/<ref>` from the current main, `mr_raiser` pushes with `--force-with-lease` (pipeline branches only; the old work is kept under `refs/rescue/`), and an already-open PR is updated and commented instead of duplicated. Opening the PR clears `needs-reengagement`. After 3 claims a ticket is left for a person (`MAX_REENGAGE_ATTEMPTS`).

## clarity-captions app-build check is now required (2026-10-05)

The profile's `spike-app` tier (xcodegen + `xcodebuild` for the iOS Simulator SDK, signing off) is enabled and **required**, so both the pipeline's verification and the dashboard merge gate fail a PR that breaks the app build, not just CaptionCore's `swift test`. Selftest on main: build ok, 85 tests, about 3.5 min. Needs `xcodegen` (Homebrew, installed on the mini) and the 234 MB Sortformer model, which the `diarizer-model` setup step links into each worktree from `~/.agents-pipeline-cache/clarity-captions/` (fetched once, self-healing if missing). Build output goes to a shared `DerivedData` in that cache dir. Only `mac-mini-1` has these; a machine without them releases the claim without a strike.

## Base-branch rule (2026-10-05, from finance-os #8)

`gh pr merge` merges into whatever the PR *targets*. finance-os #8 targeted `feature/bills-table`, so it showed MERGED while `ipc/bills.js` never reached main; #9 and #10 target the same side branch and now conflict with it. Rules, enforced in the webhook (`assertTargetsBase` in `merge.js`, refusal `WRONG_BASE`, not sent back for rework) and mirrored in the dashboard (`baseProblem` in `pr_order.js`: the button is disabled, and it names the parent PR when the side branch is another open PR's head). Open: finance-os needs a human decision on how to land `feature/bills-table`; its tracked `graphify-out/` files and `package-lock.json` change in every PR, which is what makes unrelated PRs conflict.

## Generated files stop causing conflicts (2026-10-05)

A profile can declare `"generated": [{"path", "unless"?, "regenerate"?}]` (`lib/generated_paths.py`). One implementation, two uses: (1) the pipeline leaves those paths out of its commit (`mr_raiser._leave_out_generated`), except that a lockfile is kept when `package.json` changed in the same change (`unless`); (2) the merge gate, when a rebase conflicts ONLY in generated files, takes main's copy, runs `regenerate` if given, and continues (`rebaseAndRetest`'s resolver). A conflict in real code still fails the gate, and the files stay tracked. finance-os declares `graphify-out` and `package-lock.json`. Not covered: a post-merge job to refresh them on main (they go stale between refreshes).

**Already-on-main conflicts (2026-10-05).** `generated_paths.resolve_rebase` also resolves a non-generated conflicted file when main already contains the PR's change to it (the commit, reverse-applied to main's copy with context ignored, goes through, and every added line is present in main's copy), and drops a commit that becomes empty. It is deliberately strict: finance-os #9/#10 did NOT qualify for `package.json`, because they added `vitest ^4.1.11` while main deliberately pins `^2.1.9`. That is a judgement call, so the gate refuses and says which files, and a person decides. Resolution applied by hand for those two: take main's `package.json`, regenerate the lockfile, run the project's tests, push with a lease on the starting SHA. After it, #9 touches 2 files and #10 four, none shared, so they can merge in either order.

## Conflicts are caught before anyone clicks Approve, and the "boards disagree" alarm re-checks (2026-10-05)

- **Auto send-back:** each pipeline scan runs `_requeue_conflicted_prs` over the board repos: an open PR that GitHub reports CONFLICTING gets its ticket labelled `needs-reengagement` with a comment saying why, and the sent-back loop rebuilds it on the current main (same PR, force-with-lease). Tickets already sent back, `pinned` or `held` are skipped. This fixes the pattern behind clarity #48 and finance-os #9/#10: parallel PRs that all touch a hotspot file (ContentView.swift) and conflict once the first lands.
- **MR Review:** a CONFLICTING PR shows the reason and its Approve button is disabled; "nothing to do here", it is already being reworked.
- **Parity alarm:** the board files a ticket under In review from its pipeline stage log (`verifying`/`gate`/`merging`) even before the PR exists, while the PR list comes from a cached GitHub read. Those two can briefly disagree ("filed under In review but has no open PR"). `parity()` now re-reads with fresh data before reporting and shows only what persists.

## Merge queue of one, and machine failures are not code failures (2026-10-05, from clarity #49)

- **Cause of #49:** all app builds shared one `DerivedData` folder (I did that to save disk), so a pipeline build and the merge gate's build collided ("database is locked"), and the failure was filed as "Regression/quality" and the ticket sent back. Fixed: each build gets its own temp build folder (profile command), deleted afterwards.
- **Serial merges per repo** (`inRepoQueue` in `merge.js`): one `mergePr` at a time per repo, in the order asked, failures don't block those behind, different repos run in parallel. Removes the "base branch was modified" races and gate-vs-gate collisions. `BASE_MOVED` is now a retryable classification.
- **`GATE_INFRA`** (database locked, no space, lost network, ...) refuses without sending the ticket back; the PR can simply be approved again. Real test failures still send a PR back.
- **Failure families seen in `pipeline-failures.jsonl` on 2026-10-05:** base moved/conflicts (NOT_MERGEABLE x8, REBASE_CONFLICT x7, UNKNOWN "base branch was modified" x3), executor timeouts (claude-timeout x7), finance-os test runs producing no output (x9), gate test failures (x2). Prior art: GitHub's merge queue is NOT available on personal-account repos; bors-ng / Zuul (serialise, test on the latest base) and Renovate (recreate conflicted PRs from the new base) are the models this pipeline now imitates.

## Timeouts, empty finance-os runs, and the merge popup (2026-10-05)

- **claude-timeout (8 of 41 planning calls):** not random. Planning calls that finish take 85-298s, many at 255-298s, against a 300s wall, so about 1 in 5 died for being slow. `PLAN_TIMEOUT_S` is now 900. Other long steps already had 900.
- **finance-os "produced no result" (14 records, all `npm error Missing script: "test"`):** finance-os main had no `test` script, so the required unit-test tier could not run at all (these were gate runs on #7 and #10 before #8 landed the script). None of the three repos has GitHub Actions; the dispatch gate and the merge gate ARE the CI. A missing test script is now reported as "this project has no test command yet" and, at the merge gate, refuses WITHOUT sending the PR back (`GATE_INFRA`).
- **Merge popup:** the native "Merge PR #N?" dialog is now opt-in (`confirmMerge` in the app's `prefs.json`, default off). The Approve & Merge click is the decision; duplicate starts are refused, and the gate retests. Deny/Drop still confirm.

## CI on GitHub (2026-10-06)

None of the repos had CI; the pipeline's dispatch gate and the merge gate were the only checks. Added `.github/workflows/ci.yml` to three repos (PRs: clarity-captions #57, finance-os #12, marvin #138), all green on their first real run:
- **clarity-captions** (public, free): `macos-26`; `swift test` (140 tests, 2 skipped) and the app build for the iOS Simulator (xcodegen, cached 240 MB speaker model).
- **finance-os** (private, uses monthly minutes): ubuntu, Node 20; Electron + better-sqlite3 rebuild, `npm test`.
- **marvin** (public, free): ubuntu, Node 20; dashboard vitest only (561 tests, matches local). The Python suite is NOT in CI: it needs a pinned requirements file and some tests read machine-local state.
Pushing workflow files needed `gh auth refresh -h github.com -s workflow` (the gh token had no `workflow` scope). Copies of the workflows are in `~/.claude/outbox/ci-workflows/`. Minor: GitHub warns the v4 actions run on Node 20 (deprecated); bump them when v5 is the norm.

## Python stack template for project onboarding (2026-10-07)

Added `config/onboarding/python/` stack template (ADR 0036, ticket #144). Detects Python projects from `**/*.py` glob, priority 30 (lowest, so it's a fallback after Swift/xcode/Node). During inspection, checks:
- `requirements_pinned`: all dependencies in `requirements.txt` must have `==`; if only `pyproject.toml` exists, a lock file (`poetry.lock` or `uv.lock`) counts as pinned.
- `tests_read_machine_local`: scans `test_*.py`, `*_test.py`, and `conftest.py` files for `Path.home()`, `expanduser()`, `~/.claude`, or `os.environ["HOME"]` — any match flags the project.

During planning, if either condition is unmet, `plan()` marks CI as `needs-human` with both problems named in the reason. If both are clean and no workflow exists yet, CI state is `missing` and the template can be applied. If a pytest workflow already exists, CI is `ok`. The template generates `.github/workflows/ci.yml` with ubuntu-latest and pinned Python 3.11, running `pytest`. Marvin's own repo would hit the machine-local flag (tests read `~/.claude`) and unpinned flag (no `requirements.txt`), keeping its Python suite out of CI until both are fixed — matching the 2026-10-06 decision.

## GitHub CI is now part of the merge decision (2026-10-06)

- **Merge gate:** before the local rebase/retest, `assertChecksGreen` (`webhook-server/ci_status.js`) reads the PR's `statusCheckRollup`. Failing checks (`CI_FAILED`) send the PR back with the check names; checks still running (`CI_PENDING`) refuse without sending it back; a repo with no CI (`none`) is unaffected; a metadata hiccup does not block.
- **MR Review:** each PR shows "GitHub checks passed / failed / still running"; Approve is disabled for failing and pending.
- **Auto send-back:** the pipeline scan (`_requeue_conflicted_prs`) also sends back a PR whose checks genuinely FAILED, naming them. Cancelled / timed-out / still-running checks never trigger a rebuild (the runner's fault, not the code's). The 3-attempt cap still applies.

## Project onboarding (proposed, 2026-10-06)

Design for turning a repo into a fully wired project from one command: **docs/adr/0036-project-onboarding.md** (status: proposed, awaiting Gil's decisions D1-D4). Not the portfolio "add-project pipeline" (ADR 0034).

## GitHub request budget (2026-10-06)

One account, one hourly allowance of 5,000 GraphQL points, shared by the pipeline, the merge gate, and **the dashboard app on every machine** (the Mini and the MacBook each run their own). It ran out three times on 2026-10-05/06.
- **Cause:** local file triggers (pipeline stage logs, saved docs) cleared the GitHub data caches, so each write refetched all 12 registered projects, and the PR-list cache lived only 45s. About 5,000-10,000 points an hour.
- **Fix:** only GitHub-sourced triggers (`refetchesGithub`: change-watcher and webhook pings) clear the caches; board data and the open-PR list live 5 minutes; local changes re-derive columns from cached GitHub data. Measured afterwards over 4 minutes with both apps and the pipeline running: ~1,235/hour.
- **Visible:** Health check `github:budget` (yellow under 20%, red under 5%, red "exhausted" when the query itself is refused).
- **Gap:** each machine's app is installed separately (`dashboard/scripts/rebuild_and_install.sh`), and a merge only rebuilds the machine it ran on. The MacBook stayed on the old build until rebuilt by hand over ssh. Code reaches it through the 30-minute `code-sync-push`, so a change is not live on the other machine until synced AND reinstalled.

## A PR card says one thing (2026-10-06, from clarity #66)

- **Root cause:** after the merge gate rebases and pushes a PR, GitHub recomputes its mergeability and briefly answers UNKNOWN or a stale "not mergeable". The merge step read that as a real conflict, denied the PR and labelled its ticket `needs-reengagement`. Now a "not mergeable" refusal is checked against GitHub's own `mergeable` field (`mergeableNow`, waits out UNKNOWN): only CONFLICTING sends the PR back; otherwise it merges again, and if GitHub keeps refusing a PR it calls MERGEABLE the result is `MERGE_REFUSED` (approve again later), never a send-back.
- **Screen:** `src/lib/prState.js` (`describePrState`) ranks every condition and returns ONE headline, one explanation and only the buttons that make sense (sent back, conflict, checks failed, wrong base, waiting on an older PR, waiting on checks, error, ready). Unusable buttons are hidden, except when the PR is only waiting (then Approve shows disabled). A refusal left over from an earlier click (`SENT_BACK`, `CI_PENDING`, `CI_FAILED`, `WRONG_BASE`) is never shown on its own.
- **Way out of a wrong label:** "The rework is already in? Clear the sent-back label" (inline confirm) removes `needs-reengagement` from the PR's ticket (`clearSentBackLabel`), and refuses while the ticket is claimed (a rework is running).

## Parallel ticket dispatch (accepted, 2026-10-07)

Design for a dashboard toggle that lets several tickets run at once (per-task slot records instead of one shared busy flag, a scan that fills free slots, guard rails for disk/GitHub budget): **docs/adr/0052-parallel-ticket-dispatch-toggle.md** (status: accepted: across projects only, Mini 2 / MacBook 1, toggle in the Activity device strip, automatic guard rails). Today's real limit is one ticket per machine, baked in three places.

## A deadline covers launch work, not the whole backlog (2026-10-07)

Reviewing the ticket agents' first-pass proposals before they start acting on 2026-10-12 showed the clarity-captions hard deadline added +16 to EVERY ticket in the project, so nearly all 30 open ones would be labelled p0/p1, including post-launch work (Apple Watch, iPad, Mac, Android, two-way translation), and priority labels override dispatch order. Fix: a project's deadline can exclude buckets (`dueExcludes` in the shared catalog overrides; a ticket's bucket is its `[X]` title prefix). Gil's scope for the 2026-10-25 build: everything except bucket **V** (iPad, Mac, Watch, Android, two-way translation). `score_ticket` gives excluded buckets no deadline weight; dispatch and the prioritize agent use the same function. Still open: the triage agent's first live pass would post about 38 "missing a 'What to build' section" comments on old tickets (capped at 30 changes per hourly pass), and `refeed` overlaps the automatic conflict send-back.

## Hardening after the red-main incident (2026-10-07)

What went wrong: a figure test with a quote-style bug turned main red; nothing said so; the merge gate denied a good PR (#173) for it; three gate attempts hung with no result; and a PR could show "Merging…" forever. What now prevents a repeat:
- **Main is watched:** `lib/main_health.py` runs the whole Python suite on a clean checkout of origin/main whenever it moves (started in the background by each pipeline scan) and records it; Health check `main:green` is red, naming the failing tests, until it is fixed. It runs everything, including tests that read other repos.
- **A PR is not judged on another repo's data:** the gate runs pytest with `MARVIN_MERGE_GATE=1`, which leaves out tests that read the portfolio repo (`readable_guard.exclude_portfolio_tests`); they run in the main check instead.
- **The gate is bounded:** a gate that doesn't finish in 40 minutes is cut off and refused as `GATE_INFRA` ("did not finish in time"), never sent back; a merge stuck "Merging…" expires into an error after 45 minutes.
- **If main is red anyway:** the gate compares the PR's failing tests with main and refuses `MAIN_RED` instead of denying the PR (earlier fix).
- **clarity-captions' gate clone** is now a dedicated clone outside iCloud (`clone_mode: pipeline`, `~/.agents-pipeline-clones/clarity-captions`); selftest from it: 230 tests, app build ok. Still open: ticket #192 moves the portfolio repo itself out of iCloud ~/Documents (the root of the launchd read hang).

## GitHub outages during a merge (2026-10-07)

A GitHub 5xx (`remote: Internal Server Error`, HTTP 500, 503) is classified `GITHUB_OUTAGE` (retryable, never sends a ticket back). The gate's rebase push is retried with backoff so a finished retest is not thrown away, and the PR card says "GitHub is having an outage" (`github-outage` in `prState.js`) with Approve still available. Found when clarity-captions "Implement clarity-captions#8" (Transcript scrollback and retention) failed its merge during a real incident.
