# Map connections: link everything, not just skills — 2026-10-08

For #189 (Map v2: review the first live snapshot). Gil, reviewing the dev snapshot: "looking much better but we are
still missing all the connections".

## What was wrong

The map's gold threads (synapses) only connect skills: 11 `calls:`, 1 undeclared and 14 hook/cron threads. Projects,
Dashboard, Infrastructure, Autonomous Agents and the machines have no threads at all.

The one feature meant to connect them, **feeds** (a job's output → the dashboard tab that shows it), never drew
anything:

1. `generate.py` read the dashboard's reader files from `dashboard/src/components/`; they live in
   `dashboard/electron/main/`. Each missing file was skipped silently, so there were 0 readers.
2. Reader paths were only found for constants named `*_PATH`/`*_DIR` built from `homedir()`. Most of the dashboard
   names them differently (`JOBS_DIR` works, `HEALTH_CHECKS_SCRIPT`, `CLI`, `evalScript` don't) or runs a script
   rather than reading a file.
3. Tab keys (`docs`) didn't match the tab node ids (`Docs tab`), so the generator dropped the one thread it found.

## Decided connection types (Gil, 2026-10-08: all four)

All derived from files that are already the source of truth. No LLM calls, nothing hand-maintained beyond small
existing tables.

| Type | From → to | Source of truth |
|---|---|---|
| `feeds` | job/script node → dashboard tab | the tab's main-process files: `lib/x.py` it runs, and data paths it reads that a lib script writes (incl. via `job_events.job_run`) |
| `runs-on` | background agent → machine | `JOB_PLACEMENT` in `lib/health_checks.py` (the Health tab already flags a job running where it shouldn't) |
| `builds` | ticket-pipeline → project | `config/projects/*.json` with `dispatch: "on"` |
| `skill-project` | skill ↔ its project | a project node `project:<skill>`, plus `skill_projects` in `enrichment.json` for names that differ |

## Rules

- **No silent drops.** A listed reader file that doesn't exist, a tab key that isn't a node, or a thread whose end
  isn't on the map prints a warning, and tests cover each.
- **Public snapshot:** threads to locked (private) projects are kept; they reveal only that the project exists, which
  the locked node already shows. Machines stay anonymised by `export_snapshot.py`.
- **Visual:** same gold as other threads, distinct dash per type, tooltip names the type, footer legend lists all.

## Tasks

1. [ ] `scripts/connections.py`: pure functions `runs_on(placement, node_ids)`, `builds(profiles, node_ids)`,
   `skill_projects(skill_ids, project_ids, overrides)`. Tests first.
2. [ ] `scripts/data_flow.py`: readers from `dashboard/electron/main`, any `join(homedir()|agentsDir, ...)` path and any
   `'lib', 'x.py'` script reference; helper-module writers (`job_events`); tab keys are node ids; warn on missing
   files/tabs. Tests first.
3. [ ] `generate.py`: wire 1 + 2, warn on dropped threads (already does) and on 0 threads of a type.
4. [ ] `template.html`: dash, tooltip and legend for `runs-on`, `builds`, `skill-project`.
5. [ ] Regenerate, re-export the snapshot, deploy to the dev site only, screenshot, Gil reviews (#189).
