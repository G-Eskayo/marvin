# Changelog

- Daily digest reads real inputs: the correct bench results path and a working reviewer-log split ([#601](https://github.com/G-Eskayo/marvin/pull/601))

- Docs search: one ranked list with kind tags, freshen clean local clones, index PDF text ([#618](https://github.com/G-Eskayo/marvin/pull/618))

- Docs search: a doc's own name doesn't find it, and long sections outrank it ([#610](https://github.com/G-Eskayo/marvin/pull/610))

- Profiles with dispatch on and no machines: assign the Mini, stop calling marvin unrunnable ([#617](https://github.com/G-Eskayo/marvin/pull/617))

- Project playbooks, slice 1: iOS app playbook, profile playbook field, three profile gaps ([#615](https://github.com/G-Eskayo/marvin/pull/615))

- Ticket pipeline: honour one needs-a-person state, stop bot comments resetting the failure streak, reuse the plan across review rounds ([#606](https://github.com/G-Eskayo/marvin/pull/606))

- Show chat helper agents in the Activity tab ([#614](https://github.com/G-Eskayo/marvin/pull/614))

- Owner decisions on a PR go unanswered: flag them, then file a follow-up ticket after N hours ([#608](https://github.com/G-Eskayo/marvin/pull/608))

- Change-detector fires on ETag churn: decide 'changed' from the newest issue's content, not the ETag ([#604](https://github.com/G-Eskayo/marvin/pull/604))

- Cleanup sweep leaves du processes hung on protected folders (TCC); add timeouts and single-flight ([#589](https://github.com/G-Eskayo/marvin/pull/589))

- Main is red on two portfolio tests (project-card parity, reference templates) ([#588](https://github.com/G-Eskayo/marvin/pull/588))

- Release dead ticket claims automatically, so the queue never freezes on a run that died ([#582](https://github.com/G-Eskayo/marvin/pull/582))

- Docs: fold the Files tab into Docs (chosen layout from #562) ([#579](https://github.com/G-Eskayo/marvin/pull/579))

- main-health runs pile up (3 full test suites at once) and starve the merge gate: single-flight lock + skip docs/log-only commits ([#576](https://github.com/G-Eskayo/marvin/pull/576))

- Docs tab: stop calling GitHub on every click for projects without a local clone ([#571](https://github.com/G-Eskayo/marvin/pull/571))

- MR Review: merge progress bar (stage by stage, pushed live), and fix merges that hang or time out ([#569](https://github.com/G-Eskayo/marvin/pull/569))

- Guard: fail the build when new code polls instead of using a trigger (Triggers over polling) ([#559](https://github.com/G-Eskayo/marvin/pull/559))

- MR Review: show GitHub checks progress (N of M done, what's running, last checked) with a per-check drill-down ([#557](https://github.com/G-Eskayo/marvin/pull/557))

- Proposals section in MR Review: big north-star ideas, plain-language cards, actions ([#542](https://github.com/G-Eskayo/marvin/pull/542))

- Signed dashboard builds crash after packaging (null publish 'channel'), so installs fall back to ad-hoc signing ([#541](https://github.com/G-Eskayo/marvin/pull/541))

- code_sync push fails to merge when sync-log.md (or any file) has uncommitted edits, e.g. after the Mac sleeps mid-run ([#452](https://github.com/G-Eskayo/marvin/pull/452))

- code_sync auto-commits onto whatever branch is checked out, sweeping other sessions' WIP into PR branches ([#445](https://github.com/G-Eskayo/marvin/pull/445))

- GitHub usage: replace the sawtooth allowance line with hourly low-point bars linked to calls-per-hour (24h/7d/30d) ([#418](https://github.com/G-Eskayo/marvin/pull/418))

- A healthy no-op push never clears an earlier push failure, so Health stays stuck (yellow, then red) after the problem is fixed ([#439](https://github.com/G-Eskayo/marvin/pull/439))

- Boot sequence: hover glow + click-through to the real check (summary lines and banner) ([#434](https://github.com/G-Eskayo/marvin/pull/434))

- MARVIN Metrics app icon: celestial-navigation M on pure black (R6) ([#437](https://github.com/G-Eskayo/marvin/pull/437))

- Dashboard: celestial-navigation boot sequence with a real health verdict (port of #428 v7) ([#432](https://github.com/G-Eskayo/marvin/pull/432))

- Memory-sync block is a hard stop at the top of the session-start report, with stuck duration and refusal count ([#429](https://github.com/G-Eskayo/marvin/pull/429))

- Errors are never silent: one bounded error log per Mac, Health 'Recent errors', shown where they happen ([#425](https://github.com/G-Eskayo/marvin/pull/425))

- Pipeline screenshots: capture by attaching over CDP (Playwright launch is broken), then unstick #358/#359/#368 ([#424](https://github.com/G-Eskayo/marvin/pull/424))

- Seal Speak beta report ingest job on the Mini, summarised by device and build ([#413](https://github.com/G-Eskayo/marvin/pull/413))

- MR Review: Open | Merged toggle with full merged history and refused approvals (read-only detail) ([#420](https://github.com/G-Eskayo/marvin/pull/420))

- code-sync auto-commits a builder's half-finished edits in ~/.agents and pushes them to both Macs ([#398](https://github.com/G-Eskayo/marvin/pull/398))

- Map shows no infrastructure, and onboarding PRs close no ticket ([#395](https://github.com/G-Eskayo/marvin/pull/395))

- [Ops] Dashboard: machine resources panel (disk, memory pressure and swap, CPU, GPU) for each Mac ([#364](https://github.com/G-Eskayo/marvin/pull/364))

- Holds come back: an 'On hold' group on the board, a 'Revisit by' line, and a revisit agent ([#362](https://github.com/G-Eskayo/marvin/pull/362))

- Map snapshot test deletes the real ~/.claude/logs and health ([#397](https://github.com/G-Eskayo/marvin/pull/397))

- Pipeline screenshots pop a JavaScript error dialog: capture copy collides with the dashboard's refresh port ([#389](https://github.com/G-Eskayo/marvin/pull/389))

- Pipeline scans overlap: a busy scan lock is ignored after 120 s ([#388](https://github.com/G-Eskayo/marvin/pull/388))

- Portfolio tab: Open dev site button focuses the existing Chrome tab ([#378](https://github.com/G-Eskayo/marvin/pull/378))

- A needs-you list ranked by how much each item unblocks ([#371](https://github.com/G-Eskayo/marvin/pull/371))

- Resolve rebase conflicts cheaply before rebuilding a ticket ([#363](https://github.com/G-Eskayo/marvin/pull/363))

- Sessions on both Macs see each other's work (share the working-on list) ([#372](https://github.com/G-Eskayo/marvin/pull/372))

- Mobile backend: board, overview and MR read endpoints the phone needs to mirror the dashboard ([#370](https://github.com/G-Eskayo/marvin/pull/370))

- Onboarding opens the CI + agent-docs pull request in each project's repo, once ([#367](https://github.com/G-Eskayo/marvin/pull/367))

- Task list derived from the design doc; execution phase works from it ([#365](https://github.com/G-Eskayo/marvin/pull/365))

- MARVIN button: a second press opens a new tab in the window it already opened ([#376](https://github.com/G-Eskayo/marvin/pull/376))

