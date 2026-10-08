# Brain-Map — Context Glossary

Domain terms only. No implementation details — see `docs/adr/` for decisions and rationale.

- **Recurring agent**: a `com.marvin.*` launchd job that repeats on a schedule — a daily or weekly
  calendar time, or a fixed interval (e.g. the ticket pipeline every 15 minutes). Distinct from a
  **one-off task**, which sets `Day`/`Month`/`Year` for one specific date (e.g.
  `com.marvin.verify-digest-fix`, fired once on 2026-07-07), and from an **always-on service**, which
  runs continuously with no schedule (e.g. the wallpaper app). Only recurring agents appear under the
  "Autonomous Agents" trunk. (Widened 2026-10-06, #182: interval jobs used to be left out.)
- **System layer**: the overview — MARVIN's parts (memory, skills, infrastructure, agents,
  machines, dashboard, pipeline, projects) as one tree. The only layer the desktop wallpaper shows.
- **Code layer**: the code behind one system node, taken from the graphify code graph: its files,
  functions and call edges, grouped by graphify community. Vendor and generated files never appear.
- **Opening a node**: showing a system node's code layer in place, as a cluster around that node,
  while the rest of the system layer fades but stays put. Closing it returns to the overview.
  One node is open at a time.
- **Owned code**: the code a system node is responsible for, decided by path — a skill owns its
  skill folder, a file node owns that file, a recurring agent owns the script its job runs, a
  dashboard tab owns its source files. Grouping nodes and machines own no code and can't be opened.
- **Borrowed node**: shared code (e.g. the common library) that an opened node calls but doesn't
  own. Shown once, faded, at the edge of the cluster. Shared code is never a system node itself.
- **Live event**: something MARVIN actually did, as it happens — a skill call, a file touched (in
  MARVIN's own code or a project repo), a recurring job starting/finishing/failing, a pipeline stage
  change. Each one lands on a system node (and a code node, when that node is open). Live events
  exist only on the local machine; the website snapshot has none.
- **Pulse** vs **state**: a live event shows as a pulse — brief, then gone. Machine health and
  online/offline are states — a lasting tint that changes only when the condition does.
- **Map surfaces**: the one map, shown three ways — the **wallpaper** (system layer only, live,
  not clickable), the **map tab** in the dashboard (both layers, live, clickable), and the
  **snapshot** on the website (both layers, clickable, frozen, public data only).
- **Locked node**: a private project shown by name on the snapshot but never openable — no code,
  no live events. Tells visitors what else is in progress without exposing it.
- **Feeds** (thread kind): a data flow from a library module to a dashboard tab, detected by matching
  path constants (e.g., `STAGES_DIR = ~/.agents/stages` in writer → `STAGES_DIR = path.join(homedir(), '.agents', 'stages')` in reader).
  Distinct from `calls:` (direct code dependency), `hook`/`cron` (infrastructure wiring), and `undeclared` (real dependency not in frontmatter).
  Rendered with a unique dash pattern (`— — —`) per ADR 0055.
