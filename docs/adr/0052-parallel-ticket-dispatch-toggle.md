# 0052. Parallel ticket dispatch: a dashboard toggle, per-task slots, and guard rails

Date: 2026-10-07. Status: **accepted** (Gil confirmed D1-D4 on 2026-10-07); nothing built yet.

"Multi-threading" here means **several tickets being worked at once** (separate runs on separate worktrees), not
threads inside one run.

## Context

The pipeline finishes one ticket at a time per machine, and that limit is baked in three places, not one:

1. **One ticket per scan.** `_scan` picks the single best candidate across projects, claims it, dispatches it, and
   stops. A scan runs hourly and after each merge, so the next ticket waits for one of those.
2. **One shared "busy" boolean.** `~/.claude/dispatch-state.json` is a single `{busy, task}` record that the wrapper
   sets at start and clears at exit. With two overlapping runs, the first to finish clears it while the other still
   runs (this caused the double dispatch on 2026-10-05, patched by also checking for a live `run_ticket` process).
3. **One machine, one slot.** `select_machine` / `_select_for_profile` skip a machine that is busy. Marvin's own
   tickets run on the Mac mini only (the MacBook has 18 environment-only test failures); clarity-captions may use both.

So today's real concurrency is at most 2 (one per machine) and for marvin tickets exactly 1.

What already helps: merges are serial per repo (the merge queue of one, ADR 0036's follow-up), conflicts and failing
checks send a ticket back automatically, claims are per ticket, the circuit breaker is per project, and dispatch order
already weighs deadlines (ADR 0047).

**Facts that bound the design** (measured 2026-10-07): Mini 10 cores, 16 GB RAM, 36 GB disk free; MacBook 8 cores,
16 GB, 136 GB free. A run's worktree is about 0.6 GB (build output is a per-run temp folder, deleted afterwards).
A finished ticket costs a median of $1.39 and p90 $3.13 of model usage; two at once double the burn rate against
the same Claude allowance and the same 5,000/hour GitHub allowance (the dashboard and pipeline together measured about 1,235 an hour on
2026-10-06; see CONTEXT.md, "GitHub request budget"). Two tickets in one project touching one hotspot file is how clarity #48 and #62
conflicted.

## Requirements

1. **R1 A toggle in the dashboard** that turns parallel dispatch on or off, with two limits: how many tickets at once
   in total, and how many per project.
2. **R2 Off by default, and Off means exactly today's behavior.**
3. **R3 Takes effect on the next scan.** Turning it off drains: running tickets finish, nothing is killed.
4. **R4 Per-task accounting.** Each running ticket has its own record; one finishing can never make another look idle.
5. **R5 Conflict-aware by default.** Parallel across *different projects* freely; within one project only up to its own
   limit (default 1).
6. **R6 Guard rails that pause starting new work, not running work:** low disk, GitHub budget under 20%, a tripped
   circuit breaker, a machine short of the project's required tools. The scan log and Health say which and why.
7. **R7 Freed slots refill promptly**, not on the next hourly timer.
8. **R8 Visible.** The Activity device columns show slots used (for example "2 of 2") and each running ticket.

**Non-goals:** splitting one ticket into parallel sub-tasks; running on machines beyond the registered devices;
changing merge order (merges stay one at a time per repo).

## Design

**Settings** live in one synced file, `config/dispatch.json`:

```json
{ "parallel": false, "max_total": 2, "max_per_project": 1,
  "machine_slots": { "mac-mini-1": 2, "macbook-pro-1": 1 },
  "guards": { "min_disk_gb": 15, "min_github_budget_pct": 20 } }
```

`parallel: false` ignores every other field and behaves as today. `machine_slots` is the machine's physical ceiling
(derived from cores and RAM, editable); `max_total` is your appetite, and the effective limit is the smaller.

**Per-task records** replace the shared boolean. The dispatch wrapper writes `~/.claude/dispatch/tasks/<task_id>.json`
(`ticket`, `repo`, `machine`, `pid`, `started_at`) at start and removes it on exit (trap). `slots_in_use(machine)`
counts records whose pid is alive and reaps the dead ones. The old `dispatch-state.json` stays as a compatible summary
(`busy` = any record) so readers that only ask "is anything running" keep working.

**The scan becomes a fill loop.** It keeps today's candidate ordering (priority, deadline-weighted score, age), then
repeats: take the next candidate whose project is under `max_per_project`, find a machine with a free slot that the
project's profile allows and that has the required tools, run the guard rails, claim, dispatch, and stop when slots,
`max_total` or candidates run out. The single-ticket code path becomes `_dispatch_one` and is reused unchanged.

**Refilling.** When a run exits it asks for a scan (debounced), so a freed slot is refilled in seconds. Today only a
merge triggers one.

**Dashboard.** An IPC pair `dispatch:getConcurrency` / `dispatch:setConcurrency` reads and writes the file. The
Activity tab's device strip gets a control: `Parallel [off|on] up to [2] at once, [1] per project`, with a one-line
cost note when turned on. Setting it kicks `code-sync-push` so the other machine sees it within a minute, not 30.
Device columns show `n of m` slots and one line per running ticket.

**Guard rails** are one function, `can_start_another(machine)`, returning `(ok, reason)`; the reason is written to the
run log's scan step and surfaced in Health ("Not starting another ticket: disk 9 GB free, minimum 15").

## Architecture

- `lib/dispatch_concurrency.py`: load/validate settings, `effective_limit`, `slots_in_use`, `can_start_another`. Pure
  over injected readers (disk, budget, process table), unit-tested with fixtures like `ticket_evidence.py`.
- `lib/task_dispatch.py`: wrapper writes and removes per-task records; `select_machine` consults slots.
- `lib/ticket_pipeline.py`: `_scan` fill loop around the existing `_dispatch_one`.
- `lib/run_ticket.py`: on exit, request a scan.
- Dashboard: `electron/main/dispatch_concurrency.js`, preload API, a `ParallelToggle` component in the Activity strip,
  slot display in `DeviceColumns`.
- Health: a check "Parallel dispatch is keeping up" (slots idle while tickets wait, and why).

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Two tickets in one project conflict on a hotspot file | per-project limit defaults to 1; the automatic send-back and rebuild loop still catches any that slip through |
| Double the model usage and GitHub calls | the toggle shows the cost note; the GitHub guard pauses new starts under 20% budget; the Metrics tab already charts usage |
| 16 GB RAM with two Xcode builds | Mini slot ceiling 2; MacBook 1; the guard can add a memory check if swap pressure shows up |
| A crashed run leaves a record behind | records are validated by pid and reaped; a stale one never holds a slot |
| The setting reaches the other machine late | the toggle triggers a sync; the scanning (primary) machine reads its own file |
| Turning it on mid-day surprises a running ticket | turning on only adds starts; turning off drains and never kills |

## Decisions (confirmed by Gil, 2026-10-07)

- **D1. Across different projects freely; one at a time within a project** (`max_per_project: 1`, adjustable).
- **D2. Machine slots: Mini 2, MacBook 1.** Marvin's own tickets stay Mini-only.
- **D3. The control lives in the Activity tab's device strip**, next to the slot display.
- **D4. Guard rails pause new starts automatically** (disk, GitHub budget, tripped breaker, missing tools), never
  touching running tickets, and say why in Health and the scan log.

## Tasks

Filed 2026-10-07 as tracer-bullet slices (test-first, each shippable on its own):

1. G-Eskayo/marvin#193 Parallel dispatch: per-task slot records and a slots display on the device columns
2. G-Eskayo/marvin#194 Parallel dispatch: settings file and guard rails (`can_start_another`)
3. G-Eskayo/marvin#195 Parallel dispatch: the scan fills free slots across projects
4. G-Eskayo/marvin#196 Parallel dispatch: a finished run refills its slot right away
5. G-Eskayo/marvin#197 Parallel dispatch: dashboard toggle and limits in the Activity device strip
6. G-Eskayo/marvin#198 Health check: parallel dispatch is keeping up
7. G-Eskayo/marvin#199 Parallel dispatch: first live run with two projects at once, reviewed together
