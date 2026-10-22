# Playbooks: one way of working per project type and per conversation (design, 2026-10-22)

Status: **decided 2026-10-22** (Gil, in chat): slice 1 first, Gil runs phone checks guided in chat, Sudoku uses the iOS playbook minus TestFlight. Nothing is built yet. This doc starts with the **iOS app** playbook. Web, MARVIN infra and research/hardware follow the same shape later.

## Why

The evidence is from 2026-10-22:
- Gil's Vitals question sat unanswered for 16 hours.
- #154's 7 decisions were buried in a doc file he had no way to answer from.
- Gil was asked about things he had already settled (the Mac in 1.1, the word list), and two different "lists" got mixed up.
- He had to ask "where is it running?" because helpers were invisible.
- The laptop throttled under parallel test runs.

Answered in chat, the 7 decisions took minutes.

**Root cause:** each project and each conversation rediscovers its own rules. **Fix:** write the rules down once per type, and make new work inherit them.

**North-star fit:**
- **Reuse:** extends what exists: onboarding profiles (`config/onboarding/<type>/`, ADR 0036/0058), execution profiles (`config/projects/<repo>.json`), `docs/agents/pr-requirements.md` and the decisions format.
- **Compounding:** every new project and every chat gets cheaper.
- **No new runner:** playbooks are data plus a checklist read by existing code.

## Part 1. Project playbooks

A playbook is one file per type: `config/playbooks/<type>.md` for people and agents, plus `<type>.json` for code. It has the same sections every time:

1. **Stages:** the path a piece of work takes.
2. **Proof per stage:** what must exist before the next stage.
3. **Owner gates:** the steps that always stop for Gil.
4. **Machines:** where each stage runs.
5. **Glossary pointer:** the project's terms (Part 3).
6. **Known traps:** lessons already paid for.

A project's execution profile names its playbook (`"playbook": "ios-app"`). Onboarding sets it from the detected type, and anything the playbook doesn't fit is overridden in the profile.

### The iOS app playbook (`ios-app`)

**Applies to:** clarity-captions (Seal Speak), nourished, marvin-mobile, and killer-sudoku (macOS SwiftUI, so it uses the same playbook minus TestFlight).

**Stages and proof**

| Stage | What happens | Proof before moving on | Where |
|---|---|---|---|
| 1. Idea → ticket | A ticket in the project repo, labelled `project:<id>` | Problem, who it's for, and any look change with a **mock-up image on the ticket** | Either Mac |
| 2. Design (only when needed) | A design doc + ADR draft for anything touching the engine, data, privacy, money or the store listing | A **Decisions block in the PR description**, plus the same questions **asked in chat as tappable options** and written back | Either Mac |
| 3. Build | Logic in the shared package (e.g. CaptionCore) with unit tests; a thin SwiftUI layer | `swift test` green; tests try to break it; space/time stated | **Mini** for full suites; MacBook for single files |
| 4. App build | XcodeGen generate + simulator build | `xcodebuild` green (profile verify step) | Mini |
| 5. Look proof | Any on-screen change | **Simulator screenshots** (DeviceHub.app, `simctl io screenshot`), a **GIF for anything that moves**, rendered in the dashboard's PR detail, plus "you want X → tap Y → you see Z" | Mini |
| 6. Device check (when it matters) | Battery, heat, latency, memory on Gil's phone | Numbers against a stated limit (e.g. Seal hop: Apple + 10% battery/heat over 30 min) | Gil's phone, guided |
| 7. Merge | Through the gate | Gate green; decisions answered; images re-pinned after any later look change | Gate |
| 8. Ship | Version/build bump → archive → upload → TestFlight → App Review | Checklist below, with each step ticked | MacBook (signing) |
| 9. After ship | Beta feedback and crash reports | Ingested from the Xcode cache (`~/Library/Developer/Xcode/Products/<bundle>/Feedback`), tickets by device | Mini |

**Ship checklist** (from what worked for Seal builds 3–6):
1. Bump `CURRENT_PROJECT_VERSION` in `project.yml` **and** rerun the generate script, or the build number goes stale.
2. Run `xcodebuild archive` + `-exportArchive` (app-store-connect, upload) on the MacBook. Xcode doesn't need to be open.
3. **Owner gates:**
   - in App Store Connect, expire the old build and add the new one to testers;
   - submit for review, with expedite text if there's a deadline;
   - the listing's screenshots at the size App Store Connect asks for (6.3" = 1206×2622).
4. Once a version is out, the next one waits for it to be released first (e.g. Seal 1.1 waited on 1.0).

**Owner gates (always stop for Gil):**
- any look change: mock-up on the ticket, screenshots on the PR;
- anything sent to Apple;
- signing, bundle id, deployment target, entitlements;
- new dependencies or network access (privacy, ADR 0007);
- store listing text;
- **removing or adding a user feature.** "Removing" means deleting its code too, not just hiding it: the word list's editor was taken out of the UI but its code stayed, and that confused the design.

**Machines:**
- **Mini:** builds, tests, screenshots, long runs.
- **MacBook:** signing and upload, and single-file tests.
- The laptop never runs full suites in parallel (see the test cap in `memory-search-progress-2026-10-22.md`, slice E).

**Known traps (already paid for):**
- Xcode 27 has no Simulator.app: use DeviceHub.app and `simctl`.
- Don't move or modify a repo that's open in Xcode.
- TestFlight and Apple mail go to iCloud, not Gmail.
- The executor can't run the app, so it must say which behaviour is untested.
- A profile with `machines: []` never runs (marvin-mobile and nourished today).

**Gaps found while writing this (fix when the playbook lands):**
- **clarity-captions:** the profile's executor notes say "you cannot build or run the iPhone app here", yet its verify step builds for the simulator, and screenshots are required. The playbook makes screenshots a Mini step the pipeline can run.
- **marvin-mobile:** dispatch `on` but `machines: []`, so nothing can ever run it.
- **nourished:** dispatch `off`, no machines, no verify steps, and no tests yet.

## Part 2. Conversation playbooks (how I work with Gil)

| Gil says | I do |
|---|---|
| "resume" / "where are we" | At most 5 lines of status (what landed, what's running, where), then **one** question. Read the latest handoff and the PR/ticket record first. |
| a decision is needed | **Tappable options in chat first** (4 at most per round, recommended option first), then write the answers to the PR's Decisions block and post the record comment myself. The dashboard is a second way in, not the only one. |
| "is X done / ready?" | Check the real state (GitHub, builds, devices) before answering. Never answer from memory. |
| a look change | Screenshot or GIF first, words second. |
| "investigate / why" | Finding and evidence first, then the proposed fix. No fix without his OK. |
| work is launched | Say where it runs and where to watch it (Activity), and check machine load first. |
| leaving / "pause" | Pause helpers at safe points with WIP commits, hold any ticket that could loop, write the handoff, and reply in under 10 lines. |

**Rules for every conversation:**
- **Check the record before asking.** Look at the PR comments, Decisions blocks, memory and the project glossary. Never re-ask a settled question.
- **One topic per message.** Tables over paragraphs, the decision at the top. Gil is dyslexic and has ADHD.
- **Name things the way Gil does** (Part 3). If a word could mean two things, say which.

## Part 3. A glossary per project

Each project's `CONTEXT.md` gets a short **Glossary** section in Gil's words: e.g. "Duo = iPhone Duo support", "word list = the removed custom vocabulary feature", "model manifest = build-time list of model downloads, never shipped". Helpers read it first; the delegation preamble (`lib/north_stars.py preamble`) already sends them to CONTEXT.md. New terms go in when they first come up in chat.

## Rollout (vertical slices)
1. **iOS playbook file + `playbook` field.** clarity-captions points at it, and the pipeline executor's notes are generated from it. Fixes the three profile gaps above.
2. **Decisions in chat:** a small tool that turns a PR's Decisions block into chat questions and writes the answers back (what was done by hand for #154). It reuses `decisions.js` parsing and `decisions_submit.js` writing.
3. **Glossary sections** for clarity-captions and marvin, seeded from today.
4. **Conversation playbook:** goes into the MARVIN CLAUDE.md layer as a short table.
5. Web, then infra, then research/hardware playbooks, one at a time.

## Complexity
- Playbooks are static files, so loading one is O(1) per launch.
- Decisions-in-chat is one PR read plus one write per decision round.
- The glossary is a few lines per project.

## Decisions
<!-- marvin:decisions -->
### first-slice: What lands first?
- [x] iOS playbook + fixing the three profile gaps (Seal build 7 is next and uses it)
- [ ] Decisions in chat (the tool for what we did by hand on #154)
- [ ] Glossaries

### device-check: Who runs on-phone checks like battery and heat?
- [x] Gil, guided step by step in chat, with MARVIN reading the numbers
- [ ] MARVIN, through a connected phone on the Mini (Xcode instruments), with Gil only plugging it in

### mac-sudoku: Does killer-sudoku (macOS) use the iOS playbook or get its own?
- [x] iOS playbook minus the TestFlight steps
- [ ] Its own macOS playbook

### notes: Anything to change? (text) (optional)
