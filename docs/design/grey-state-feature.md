# Job Staleness Detection (Grey State)

**Ticket:** #1251

**Purpose:** Show jobs on the Work half of the brain-map when they are "going stale" — idle but overdue relative to their expected cadence — so overdue jobs surface as a visual signal without raising to the red "failed" severity.

## Implementation

### 1. Job Catalog (`lib/job_catalog.py`)
Added `max_quiet_s` field to every job:
- **Positive integer (seconds)**: Expected maximum time between runs for scheduled jobs (e.g., 86400 for daily jobs, 3600 for hourly jobs)
- **None**: For continuous-service jobs that always run (desktoplive, dashboard-webhook, machine-resources)

### 2. Work View (`brain-map/scripts/work_view.py`)
Extended `_job_state()` to return three values:
- `state`: "running" | "failed" | "grey" | "idle"
- `ended`: timestamp when the failure/grey occurred
- `last_seen`: timestamp of the job's last activity

**Grey Logic:**
- Job is idle (last run finished cleanly)
- AND `max_quiet_s` is set
- AND `now - last_seen > max_quiet_s`
- THEN `state = "grey"`

**Grey Description:** Shows elapsed time in minutes: `"not hearing from it · N min"`

### 3. Brain-Map Template (`brain-map/template.html`)
- Added `greyIds` tracking object for grey workers
- Extended `applyWork()` to handle `state: "grey"`
- Added `GREY_RGB = "160,163,166"` for grey color rendering
- Grey workers are **excluded from the dismiss tray** and `redWorkers()` (unlike red/failed workers)
- Grey nodes render with the grey color and are not lit by pulses (like red nodes)

### 4. Job Events (`lib/job_events.py`)
Added work nudge integration:
- `job_run()` calls `_nudge_work_started()` on context entry
- `job_run()` calls `_nudge_work_finished()` on context exit (in finally block)
- This ensures the Work half updates immediately when jobs start/finish

### 5. Code Deduplication
Hoisted the `_nudge_work()` and `_nudge_quietly()` pair into `work_nudge.quietly()` and removed duplicates from:
- `lib/chat_helpers.py`
- `lib/ticket_stages.py`

Both now import and call `work_nudge.quietly()` directly.

## Visual Representation

The grey state is rendered in the brain-map's Work half as:
- **Color**: RGB(160, 163, 166) — neutral grey, distinct from red (failed) and project colors
- **Visibility**: Only shown while overdue (not drawn if still within window or if idle with no max_quiet_s)
- **Interaction**: Not dismissible (unlike red/failed workers)
- **Description**: "not hearing from it · N min" — elapsed minutes since last seen

## Example

A job with `"max_quiet_s": 3600` (expected hourly):
- Last run finished at T-30 min: **idle** (not drawn)
- Last run finished at T-90 min: **grey** with desc "not hearing from it · 90 min"
- Last run failed at T-5 min: **red/failed** with standard failure desc

## Tests

Added test coverage:
- `test_job_catalog.py::test_every_job_declares_max_quiet_s` — all jobs have max_quiet_s
- `test_job_catalog.py::test_continuous_service_jobs_have_none_max_quiet_s` — continuous jobs have None
- `test_job_events.py::test_job_run_calls_nudge_functions_on_start_and_finish` — nudge integration
- `test_work_view.py::test_a_job_idle_but_overdue_shows_grey_and_reports_how_long_quiet` — grey state detection
- `test_work_view.py::test_a_job_idle_within_its_window_is_not_shown` — jobs within window stay idle

## Decisions

**Decision 1: Grey Rendering**
- **Chosen:** Use RGB(160, 163, 166), a neutral grey
- **Rationale:** Distinct from red (failure) to signal "needs attention" but not "broken"; matches neutral status colors used elsewhere
- **Alternative:** Could use orange/amber for "warning", but grey is more "just waiting" than "alarmed"

**Decision 2: Grey Exclusion from Tray**
- **Chosen:** Grey workers excluded from dismiss tray and `redWorkers()`
- **Rationale:** Grey is informational (overdue but not failed), so users shouldn't need to dismiss it. It auto-clears when the job runs again.
- **Alternative:** Could include in tray to let users manually clear stale indicators, but that adds noise.

**Decision 3: Continuous-Service Fallback**
- **Chosen:** `max_quiet_s = None` for jobs that always run
- **Rationale:** These jobs (dashboard-webhook, desktoplive) are "always on" and shouldn't surface as stale; job-level health checks (like port 7878 answering) handle their actual health
- **Alternative:** Could set a very long max_quiet_s, but None is clearer intent and costs zero checks

## Future Work

- **Feed-level staleness mark** (mentioned in #1251 as "pending Decision"): Overall indicator if the work.json itself is stale (hasn't been regenerated in too long)
- **Routing to Vitals:** Some of these stale indicators (health-check, cron-health) could feed into Vitals' own health checks
- **Automatic escalation:** Jobs that are grey for more than 2× their max_quiet_s could auto-escalate to red
