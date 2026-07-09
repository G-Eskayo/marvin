# Brain-Map — Context Glossary

Domain terms only. No implementation details — see `docs/adr/` for decisions and rationale.

- **Recurring agent**: a `com.marvin.*` launchd job whose `StartCalendarInterval` sets only
  `Hour`/`Minute` (fires every day at that time). Distinct from a **one-off task**, which sets
  `Day`/`Month`/`Year` alongside `Hour`/`Minute` (launchd only sets those three for a specific
  calendar date — e.g. `com.marvin.verify-digest-fix`, which fired once on 2026-07-07). Only
  recurring agents appear as nodes under the graph's "Autonomous Agents" trunk.
