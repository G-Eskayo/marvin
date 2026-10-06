# Brain-Map — Context Glossary

Domain terms only. No implementation details — see `docs/adr/` for decisions and rationale.

- **Recurring agent**: a `com.marvin.*` launchd job whose `StartCalendarInterval` sets only
  `Hour`/`Minute` (fires every day at that time). Distinct from a **one-off task**, which sets
  `Day`/`Month`/`Year` alongside `Hour`/`Minute` (launchd only sets those three for a specific
  calendar date — e.g. `com.marvin.verify-digest-fix`, which fired once on 2026-07-07). Only
  recurring agents appear as nodes under the graph's "Autonomous Agents" trunk.
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
