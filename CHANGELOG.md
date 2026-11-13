# Changelog

- Dispatch skips parent PRDs, using the PRD test triage already uses ([#1309](https://github.com/G-Eskayo/marvin/pull/1309))

- academic_search.py silently reports failed sources as empty results, and unbounded S2 retries can stall past the Bash timeout ([#1307](https://github.com/G-Eskayo/marvin/pull/1307))

- Audit skill's suggestion-entry template omits the required Priority field and misstates the header format, so… ([#1303](https://github.com/G-Eskayo/marvin/pull/1303))

- Workshop: parked tickets (needs-info after failed builds) and held tickets show as Stuck instead of Yours / On hold ([#1297](https://github.com/G-Eskayo/marvin/pull/1297))

- Docs: "Where things are" shows a raw IPC error on a fresh install ([#1283](https://github.com/G-Eskayo/marvin/pull/1283))

- A sleeping or closed Mac shows as red "Unreachable" on Activity ([#1281](https://github.com/G-Eskayo/marvin/pull/1281))

- MR Review dot turns green ("Nothing awaiting review") when GitHub can't be reached ([#1280](https://github.com/G-Eskayo/marvin/pull/1280))

- Enabling an add-on can wipe instance.json ([#1279](https://github.com/G-Eskayo/marvin/pull/1279))

- Boot: derive its device lines and memory path from this install, and give a fresh install a first-run verdict ([#1278](https://github.com/G-Eskayo/marvin/pull/1278))

- research/SKILL.md links epistemic-framework.md relatively, so /research (read via the commands symlink) can't find it ([#1294](https://github.com/G-Eskayo/marvin/pull/1294))

- PRs without the evidence template lose their ticket: Deny and Drop don't touch it, details show "Not available" ([#1285](https://github.com/G-Eskayo/marvin/pull/1285))

- A gate refusal can vanish, leaving "Ready to merge" with Approve enabled ([#1288](https://github.com/G-Eskayo/marvin/pull/1288))

- "Send back for options" always fails with "Webhook call failed: 400" ([#1282](https://github.com/G-Eskayo/marvin/pull/1282))

- Merge gate: clarity-captions merges fail since #155 because the gate checkout lacks the Parakeet model ([#1277](https://github.com/G-Eskayo/marvin/pull/1277))

- Freshness: Parked choices: one grammar, one overdue check, refused at write time ([#1256](https://github.com/G-Eskayo/marvin/pull/1256))

- Decision: model-adaptive harness — what changes per model ([#1273](https://github.com/G-Eskayo/marvin/pull/1273))

- Freshness: Decision supersession (extend ticket 652): answered Decisions find and flag earlier answers to the same question ([#1257](https://github.com/G-Eskayo/marvin/pull/1257))

- Freshness: `stale-relay` probe: measure caught vs leaked stale claims ([#1246](https://github.com/G-Eskayo/marvin/pull/1246))

- Freshness: Memory claims checked: notes asserting open state about closed work get flagged daily ([#1244](https://github.com/G-Eskayo/marvin/pull/1244))

- Freshness: Stamped copies: one envelope and read helper, with standby Macs reading the producer ([#1247](https://github.com/G-Eskayo/marvin/pull/1247))

- Tests: test_cross_machine_merge downloads an embedding model in every CI run, and parallel runs corrupt it ([#1258](https://github.com/G-Eskayo/marvin/pull/1258))

- Freshness: Resume check: verify a handoff's ticket and PR claims before SessionStart surfaces it ([#1237](https://github.com/G-Eskayo/marvin/pull/1237))

- code_sync: concurrent runs race on one clone (MERGE_AUTOSTASH / HEAD lock), logged as CONFLICT ([#1189](https://github.com/G-Eskayo/marvin/pull/1189))

- Auto-sync swept 12 worktrees into main as gitlinks (again, after #430) ([#1191](https://github.com/G-Eskayo/marvin/pull/1191))

- Workshop: a "Part of #N" PR hides ticket #N completely (it should only fold in on "Closes #N") ([#1204](https://github.com/G-Eskayo/marvin/pull/1204))

- Main is red at 2b914e8: fix forward ([#1194](https://github.com/G-Eskayo/marvin/pull/1194))

- Box builds: Mac-side dispatch of Linux-safe tickets to a VM on mac-mini-2012 ([#981](https://github.com/G-Eskayo/marvin/pull/981))

- MARVIN shows what it's talking about: opens the document in a Docs sub-window and works on it with you ([#1032](https://github.com/G-Eskayo/marvin/pull/1032))

- Merge queue: a PR built on a squash-merged base conflicts on rebase and is held silently ([#1186](https://github.com/G-Eskayo/marvin/pull/1186))

- Main is red at 6adae14: fix forward ([#1187](https://github.com/G-Eskayo/marvin/pull/1187))

- Box builds: frozen marvin-build golden image and VM sweep ([#969](https://github.com/G-Eskayo/marvin/pull/969))

- auto_route_hook.py reads wrong payload key ("user_prompt" vs "prompt") — hook has never fired since 2026-08-13 ([#1118](https://github.com/G-Eskayo/marvin/pull/1118))

- Merge gate: mac-mini-2012 as a parallel, non-blocking extra test runner (never the verdict) ([#942](https://github.com/G-Eskayo/marvin/pull/942))

- SBIR desk 1: topic monitor that scores new SBIR/STTR topics against a product's capability profile ([#1178](https://github.com/G-Eskayo/marvin/pull/1178))

- Pipeline: a model run hitting its time limit ends the whole ticket run (3% of calls; #1156 and the decisions follow-ups parked) ([#1182](https://github.com/G-Eskayo/marvin/pull/1182))

- Box trial work: the five trial types runnable on mac-mini-2012, with its prerequisites and the retrieval question file handed in per run ([#941](https://github.com/G-Eskayo/marvin/pull/941))

- Main is red at cc83048: fix forward ([#1163](https://github.com/G-Eskayo/marvin/pull/1163))

- Pipeline verify: an unchanged reading passes when the build made a real change; an empty build says nothing changed ([#1159](https://github.com/G-Eskayo/marvin/pull/1159))

- Pipeline verify runs the whole Python suite on every marvin ticket and times out; run the affected tests, same set before and after ([#1153](https://github.com/G-Eskayo/marvin/pull/1153))

- Site ship step: the live link on each shipped ticket, and an alarm when a publish fails ([#1145](https://github.com/G-Eskayo/marvin/pull/1145))

- Dispatch wrapper: a SIGTERM that lands as bash starts the command waits for the command (seen on Linux CI under load) ([#1149](https://github.com/G-Eskayo/marvin/pull/1149))

- Pipeline and merge gate: Seal Speak worktrees get the app's models from one sha-checked cache per machine, so the app builds there ([#1119](https://github.com/G-Eskayo/marvin/pull/1119))

- Main is red at e46bda3: fix forward ([#1147](https://github.com/G-Eskayo/marvin/pull/1147))

- GitHub's Python tests run on Linux: start at once, and Mac-only tests skip there with a reason ([#1135](https://github.com/G-Eskayo/marvin/pull/1135))

- Pipeline verify timeout counts the wait for the test slot, so builds behind merges are parked without running a test ([#1120](https://github.com/G-Eskayo/marvin/pull/1120))

- Publish the MARVIN site to marvin.gileskayo.me on GitHub Pages from main ([#1126](https://github.com/G-Eskayo/marvin/pull/1126))

- Wire MR Review by project into the real tab (#767), with one set of project names everywhere ([#935](https://github.com/G-Eskayo/marvin/pull/935))

- Merge queue: a PR set aside as CI_PENDING comes back by itself when its checks finish ([#1109](https://github.com/G-Eskayo/marvin/pull/1109))

- Accounts: live checks, expiry warnings, one alert per change, and renewal for every MARVIN credential (backend for #640) ([#977](https://github.com/G-Eskayo/marvin/pull/977))

- Workshop: one item page for a ticket and its PRs ([#1053](https://github.com/G-Eskayo/marvin/pull/1053))

- Chat tabs restart onto a new Claude Code version on their own, by resume, only while idle on your turn ([#1096](https://github.com/G-Eskayo/marvin/pull/1096))

- Send into a chat, safely: dashboard only, idle only, never onto a permission prompt ([#1095](https://github.com/G-Eskayo/marvin/pull/1095))

- Chat list data for the dashboard: both Macs, the other Mac read-only, honest when WezTerm is down ([#1093](https://github.com/G-Eskayo/marvin/pull/1093))

- Main red: the gate progress test pins the check list from before the gate ran the secret scan ([#1104](https://github.com/G-Eskayo/marvin/pull/1104))

- Open session focuses the existing chat instead of opening a duplicate ([#1090](https://github.com/G-Eskayo/marvin/pull/1090))

- MARVIN's WezTerm config: synced, guarded, installed on both Macs, accessible palette ([#1092](https://github.com/G-Eskayo/marvin/pull/1092))

- Chat state hooks: working, waiting on you, your turn, done, without ever slowing a chat ([#1085](https://github.com/G-Eskayo/marvin/pull/1085))

- Chat records: each MARVIN chat tab recorded in the existing session store, with a read-only `marvin chats list` ([#1084](https://github.com/G-Eskayo/marvin/pull/1084))

- WezTerm wrapper: one place for every wezterm cli call, aimed at the right WezTerm when two run ([#1082](https://github.com/G-Eskayo/marvin/pull/1082))

- Contrast checker: every MARVIN colour pair measured against the accessibility rule ([#1091](https://github.com/G-Eskayo/marvin/pull/1091))

- Main red on the Mini: pipeline handover tests read live claims and runs ([#1089](https://github.com/G-Eskayo/marvin/pull/1089))

- Profile parity: one facts file and one check across the site, resume, GitHub, LinkedIn and the product sites ([#1039](https://github.com/G-Eskayo/marvin/pull/1039))

- Main red on the Mini: portfolio dev-site drift (brand redesign) fails main-health; outside-state checks should be named, not block merges ([#1049](https://github.com/G-Eskayo/marvin/pull/1049))

- Main red on the Mini: a marvin show test hard-codes the portfolio folder the catalog guard reserves ([#1048](https://github.com/G-Eskayo/marvin/pull/1048))

- Merge gate: a test the PR doesn't touch that fails once sends a good PR back, silently (#892) ([#968](https://github.com/G-Eskayo/marvin/pull/968))

- Main is red at f5b194d: fix forward ([#1008](https://github.com/G-Eskayo/marvin/pull/1008))

- Main red: two tests hard-code the Mac's home folder (after #911) ([#986](https://github.com/G-Eskayo/marvin/pull/986))

- Main red: the identity rule fails on two docstrings that name the owner (after #926 and #936) ([#980](https://github.com/G-Eskayo/marvin/pull/980))

- Portable scheduled jobs: launchd on the Macs, systemd timers on mac-mini-2012 (health-check, cleanup-sweep, usage-scan) ([#919](https://github.com/G-Eskayo/marvin/pull/919))

- Linux box: 55 test failures from Mac-only paths, BSD stat, missing pytest-timeout, gh on PATH ([#918](https://github.com/G-Eskayo/marvin/pull/918))

- Health never noticed mac-mini-2012's mirror failing for 4 days: read the box's sync state from the Mini ([#913](https://github.com/G-Eskayo/marvin/pull/913))

- The Mac mini can't see the other Macs: Tailscale lookup is app-only, and a probe that can't run reads as 'everyone offline' ([#890](https://github.com/G-Eskayo/marvin/pull/890))

- Disk keeps filling on the Mini: the cleanup can't reach GitHub over ssh, the merge gate leaks temp clones, pytest temp dirs pile up ([#880](https://github.com/G-Eskayo/marvin/pull/880))

- Docs tab: doc-relative image paths render broken, and new docs/plans files may not appear in a running app ([#885](https://github.com/G-Eskayo/marvin/pull/885))

- Build #769: nightly resets with guardrails, recovery between the M4 and 2012 minis, and a Health card ([#856](https://github.com/G-Eskayo/marvin/pull/856))

- MR Review: build the approved merge motion into the real dashboard (round 2 of #761) ([#855](https://github.com/G-Eskayo/marvin/pull/855))

- Live map: nothing moves unless something real happened; leaf nodes and links light from real activity ([#851](https://github.com/G-Eskayo/marvin/pull/851))

- Plan first, credit for overflow: builds bill the API credit only when a Mac's normal slots are busy (extra slots on the Mini) ([#850](https://github.com/G-Eskayo/marvin/pull/850))

- MR Review: blue sweep slide-out when an MR merges, and an Open | Merged split view ([#761](https://github.com/G-Eskayo/marvin/pull/761))

- bin/gh refuses Decisions the dashboard can't read (rule I2) ([#744](https://github.com/G-Eskayo/marvin/pull/744))

- Builders run on the plan's monthly API credit when the machine has an API key, and fall back to the plan when it runs out ([#776](https://github.com/G-Eskayo/marvin/pull/776))

- Screenshot gate blocks every MARVIN UI PR: images in marvin-instance are looked up in marvin (UI_EVIDENCE_UNCHECKED) ([#774](https://github.com/G-Eskayo/marvin/pull/774))

- Dashboard: opening an MR or doc jumps to the bottom of the page ([#759](https://github.com/G-Eskayo/marvin/pull/759))

- helper-tab: start helpers in labelled, grouped WezTerm tabs (not Terminal) ([#754](https://github.com/G-Eskayo/marvin/pull/754))

- Merge gate on a nearly full disk: name the cause instead of GATE_INFRA ([#745](https://github.com/G-Eskayo/marvin/pull/745))

- calibrate() returns lowest labeled score instead of risk-controlled max, and tau never recalculates after new labels ([#703](https://github.com/G-Eskayo/marvin/pull/703))

- Real titles on PRs: ticket title instead of "Implement …#n", repo name on onboarding PRs, repo shown in MR Review ([#590](https://github.com/G-Eskayo/marvin/pull/590))

- Pipeline stage strip on PR and ticket cards (GitLab-style), showing where it failed ([#368](https://github.com/G-Eskayo/marvin/pull/368))

- Support link: IT button, Support tab and counter (ADR 0073) ([#662](https://github.com/G-Eskayo/marvin/pull/662))

- Cleanup sweep: back up leftover worktree edits to a branch, then remove the folder (Mini disk full again) ([#630](https://github.com/G-Eskayo/marvin/pull/630))

- About 40% of headless pipeline model runs exit non-zero; classify the causes and fix the top ones ([#598](https://github.com/G-Eskayo/marvin/pull/598))

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

