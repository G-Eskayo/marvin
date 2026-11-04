# The loop kernel (marvin#1123, Phase 1)

Gil approved the plan on #1123 (2026-11-04). This is the design for its Phase 1, the shared kernel that every loop in
Phase 2 plugs into. The decision is recorded in [ADR 0083](../adr/0083-loops-close-through-one-kernel.md).

A **loop** works only when all four steps run: **notice → act → verify → remember**. The audit found 31 of 34 loops
incomplete. Nearly all of them notice. What's missing is the act/alert step, a verify step that checks the real
outcome, and an honest record.

## Reused, not rebuilt

| Need | Existing piece reused | Change |
|---|---|---|
| Send an alert | `lib/mr_notification._fire` (desktop + dashboard fan-out, never raises) | becomes the one path; `notify.notify` calls it |
| Alert on a change, not every poll | `accounts.alerts_due` / `alert_changes` (per-key state memory) | generalised to `mr_notification.alert_on_change`, plus a daily reminder while still red |
| Record what happened | `lib/job_events.py` (per-job run log, shown in Activity) | each alert is a run of job `alerts`, one step per channel |
| Was the output consumed? | `lib/output_contracts.py` | a loop can watch a contract |
| Did the job run? | `job_events` run files, `health_checks` status | a loop can watch a job or a check |
| Install a job the same everywhere | `lib/job_units.py` (`config/jobs/*.json` → plist/systemd) | adds a default `PATH` with `/opt/homebrew/bin`, and runs commands under `job_report` so every run is recorded |
| One file per item, one parser | `lib/proposals.py` (ADR 0068) | its file rules move to `lib/inbox.py`; proposals is one pile of it |
| Fix levels | CONTEXT.md "Fix level", #874 (`{level, action, undo?}`) | each loop's fix uses the same shape |

Nothing new is paid for. Where a model is needed later (Phase 2: judging, classifying), it is local Ollama/qwen on
the Mini.

## 1. One alert path

- `mr_notification._fire(title, message, open_target)` is the only fan-out. Channels:
  - **desktop**: `notify.desktop()`. It finds `terminal-notifier` on `PATH` or in `/opt/homebrew/bin` and
    `/usr/local/bin`, else uses `osascript`. It returns the real result (the exit status), not "sent".
  - **dashboard**: the existing POST to the local webhook server.
  - **phone**: a plug-in slot, empty until MARVIN Mobile's Apple push (#958) fills it. Gil's answer on #1123:
    phone alerts wait for #958. The headless `claude -p` PushNotification call is removed; it spent plan usage per
    alert.
- `notify.notify()` keeps its signature and calls `_fire`, so every existing caller is on the one path with no edit.
- Every alert is a `job_events` run of job **`alerts`** with one step per channel and its real result. The run fails
  when no channel delivered. The caller's own run also gets a "Told the owner" step with the same result.
  `code_sync.py` logs that result, not the fixed text "told the owner".
- `mr_notification.alert_on_change(items, path)`: one memory file per caller, keyed per item. It alerts when an
  item **turns bad**, when it changes from one bad state to another, and when it **clears**. While an item stays bad it
  reminds **once a day**. Accounts and the health sweep both use it. The health sweep batches: one notification per
  sweep for what turned red, one for the daily reminder.
- `disk_forecast_notify.py` is retired. `disk:headroom` is a health check, so it alerts through the sweep like any
  other red check.
- **"Can MARVIN reach you?"**: a Vitals row reading the last `alerts` run (which channels worked, when), with a
  **Send a test alert** button.

## 2. The loop registry

`config/loops.json`, read only by `lib/loops.py`. Each loop declares:

| Field | Meaning |
|---|---|
| `id`, `name` | stable id, plain name |
| `watches` | its signal: `job:<name>`, `check:<id prefix>`, `contract:<producer>`, or `none` |
| `broken_when` | `red` (the signal is red) or `failed_runs:<n>` (n failed runs in a row; ADR 0080 I5 says 3) |
| `action` | what closes it: `job:<name>` or plain words for a person's step |
| `verify` | the signal that proves the outcome, same forms as `watches`, or `none` |
| `cycle_days` | how long a full cycle may take before the loop counts as stalled |
| `owner` | `marvin` or `gil` |
| `fix` | `{level: auto|one_tap|decision, kind: rerun|relogin|install_job|rollback|ticket|decision, arg}` |
| `wired` | false until its Phase 2 ticket plugs it in |
| `ticket` | the ticket that wires or fixes it |

**Status** is derived each time, never stored:
- **not wired**: `wired` is false, or its action job has never reported.
- **broken**: the watched or verify signal is red, or the action job failed `n` runs in a row.
- **stalled**: no full cycle within `cycle_days`.
- **closed**: otherwise.

**Last full cycle**: the most recent run of the action job that passed while the verify signal wasn't red.

**Every job reports.** `lib/job_report.py <job> -- <command…>` runs any command as a `job_events` run. A non-zero
exit is a failed run, and so is a run whose output starts a line with `REFUSING` or says it skipped because of an
error. `job_units` wraps every `config/jobs` command in it, and the older hand-written plists move to `config/jobs`
one by one (Phase 2). The registry shows a loop whose job doesn't report as **not wired**, so the gap is visible, not
silent.

The registry is seeded with every loop from the audit. Most start as not wired.

## 3. One inbox

`lib/inbox.py`: one JSON file per item under `~/.claude/inbox/<pile>/`, safe for the two Macs' git sync (merged by
file, never conflicting on an append), with one reader and writer. It keeps `proposals.py`'s rules: ids claimed with
`O_EXCL`, atomic writes, a lock per item, a size cap, symlinks refused, and a bad file reported, never fatal.

Migration, one pile at a time. Each step imports the old file once, switches its writers and readers, and leaves the
old file as a read-only backup:

| Pile | Phase 1 | Later |
|---|---|---|
| suggestions.md | **done here** (ADR 0017's priority order becomes a sort when read) | |
| improvement-queue.md | **done here** | |
| quarantine.md | | after safety reviews move to local qwen (Tier 2) |
| to-research.md | | with research → proposals (#533) |
| open-loops.md | | merges with "dismiss until" (ADR 0068) |
| proposals | already one file per item; stays at `~/.claude/proposals` as the inbox's `proposals` pile | |
| question-log | | with the "answered" status (Tier 4) |
| retrospective-log | | Tier 4 |
| self-improve's "Needs attention" | | with the playbook harvester (Tier 3) |

## 4. The Vitals Loops panel

A **Loops** view in Vitals (Health), beside Checks. One row per loop, worst first: its status
(closed / stalled / broken / not wired), last full cycle, owner, and one **fix** button. The buttons map to fixed
actions in the main process, never to a command the renderer chooses:

| Fix | What it does |
|---|---|
| re-run | starts the loop's job now (`launchctl kickstart` of its label) |
| re-login | the Accounts renew flow that already exists |
| install missing job | `job_units.py install <name>` |
| rollback | opens the ticket's rollback step (Phase 2 fills this per project) |
| file ticket | creates a needs-triage ticket naming the loop |
| answer Decision | opens the PR or ticket with the Decision |

## North-star fit

- **1, fewer resources:** reuses five existing modules. It removes the per-alert Claude call and one duplicate
  notifier. Alerts fire on a change, not on every poll.
- **2, phone OS:** one alert path with a phone slot is what MARVIN Mobile plugs into, and one inbox is what its Thread
  reads. Reliability first: nothing breaks silently.
- **3, raise the human:** Gil acts through one-tap fixes and Decisions, not raw counts.
- **Against it:** a registry is one more file to keep current. It is checked by tests (every action job exists in the
  job catalog, or the loop says it's not wired), not trusted.

## Complexity

- Alert memory: O(k) per call for k items, one small JSON file.
- Loop status: O(L × r) for L loops and r runs kept per job (r ≤ 20), plus one read each of the health and contract
  files.
- Inbox: list is O(N) small files; an action is O(1).
