# Playbook: iOS app (`ios-app`)

The way of working for an iPhone app, written once so every project and every helper inherits it. For people and
agents; `ios-app.json` next to this file holds the same rules for code (change both together). Design and the
reasons: `docs/plans/project-playbooks-2026-10-22.md` (decided with Gil 2026-10-22).

**Applies to:** clarity-captions (Seal Speak), marvin-mobile, nourished, and killer-sudoku through the **macos
variant** (below). A project names it in its execution profile: `"playbook": "ios-app"` (and
`"playbook_variant": "macos"`). The pipeline executor's notes get a section generated from the JSON, below the
project's own notes, so the profile's free text can't drift from this file.

## Decisions (Gil, 2026-10-22)

- Slice 1 lands first: this playbook, the `playbook` field, and the three profile gaps.
- **On-phone checks** (battery, heat, latency, memory) are run by Gil on his phone, guided step by step in chat,
  with MARVIN reading the numbers.
- **killer-sudoku** (macOS SwiftUI) uses this playbook minus the TestFlight steps.

## Stages and proof

| # | Stage | What happens | Proof before moving on | Where |
|---|---|---|---|---|
| 1 | Idea to ticket | A ticket in the project repo, labelled `project:<id>` | The problem, who it's for, and for any look change a **mock-up image on the ticket** | Either Mac |
| 2 | Design (only when needed) | A design doc + ADR draft for anything touching the engine, data, privacy, money or the store listing | A **Decisions block in the PR description**, plus the same questions **asked in chat as tappable options** and written back | Either Mac |
| 3 | Build | Logic in the shared package (e.g. CaptionCore) with unit tests; a thin SwiftUI layer | `swift test` green; tests try to break it; time and space stated | **Mini** for full suites; MacBook for single files |
| 4 | App build | XcodeGen generate + simulator build | `xcodebuild` green (the profile's app-build verify step) | Mini |
| 5 | Look proof | Any on-screen change | **Simulator screenshots** (DeviceHub.app, `xcrun simctl io <udid> screenshot`), a **GIF for anything that moves**, shown in the dashboard's PR detail, plus "you want X, tap Y, you see Z" | Mini |
| 6 | Device check (when it matters) | Battery, heat, latency, memory on Gil's phone | Numbers against a stated limit (e.g. Seal hop: Apple + 10% battery/heat over 30 min) | Gil's phone, guided in chat |
| 7 | Merge | Through the gate | Gate green; decisions answered; images re-pinned after any later look change | Gate |
| 8 | Ship (TestFlight and App Review) | Version/build bump, archive, upload, TestFlight, App Review | The ship checklist, each step ticked | MacBook (signing) |
| 9 | After ship | Beta feedback and crash reports | Ingested from the Xcode cache (`~/Library/Developer/Xcode/Products/<bundle>/Feedback`), tickets by device | Mini |

**How the pipeline does stage 5:** when a profile has `evidence.dev.ios_simulator` (clarity-captions,
marvin-mobile), the pipeline builds the app for the simulator after the executor finishes, launches each configured
scene (debug-only launch arguments) in light and dark, and commits the screenshots (`evidence_capture.capture_ios_simulator`,
marvin #374). The executor itself can't run or tap the app: it makes new screens reachable by a launch argument and
says which behaviour is untested. A UI change with no image can't be approved (`NO_UI_EVIDENCE`).

## Ship checklist (what worked for Seal builds 3 to 6)

1. Bump `CURRENT_PROJECT_VERSION` in `project.yml` **and** rerun the generate script, or the build number goes stale.
2. `xcodebuild archive`, then `-exportArchive` (app-store-connect, upload) on the MacBook. Xcode doesn't need to be open.
3. **Owner gates:**
   - in App Store Connect, expire the old build and add the new one to testers;
   - submit for review, with expedite text if there's a deadline;
   - the listing's screenshots at the size App Store Connect asks for (6.3" = 1206x2622).
4. Once a version is out, the next one waits for it to be released first (Seal 1.1 waited on 1.0).

## Owner gates (always stop for Gil)

- Any look change: a mock-up on the ticket, screenshots on the PR.
- Anything sent to Apple.
- Signing, bundle id, deployment target, entitlements.
- New dependencies or network access (privacy; ADR 0007 in clarity-captions).
- Store listing text.
- **Adding or removing a user feature.** Removing means deleting its code too, not just hiding it: the word list's
  editor was taken out of the UI but its code stayed, and that confused the design.

## Machines

- **Mini (`mac-mini-1`):** builds, tests, screenshots, long runs.
- **MacBook (`macbook-pro-1`):** signing and upload, and single-file tests. It never runs full suites in parallel:
  use `-n 2` at most, and check `sysctl -n vm.loadavg` first (wait while the 5-minute load is over 12).

The pipeline runs a whole ticket on one machine; it does not route single stages. A profile that lists the MacBook
(clarity-captions) can therefore build and screenshot there too.

## Glossary

Each project's own terms are in its `CONTEXT.md` (a Glossary section is slice 3 of the design).

## Known traps (already paid for)

- Xcode 27 has no Simulator.app: use DeviceHub.app and `xcrun simctl`.
- Don't move or modify a repo that's open in Xcode.
- TestFlight and Apple mail go to iCloud, not Gmail.
- The executor can't run the app, so it must say which behaviour is untested.
- A profile with dispatch on and `machines: []` never runs. `project_profile.py selftest` now says so, and Health
  lists it.

## Variant: `macos` (killer-sudoku)

The same playbook without stages 6, 8 and 9 and without the ship checklist: no TestFlight, no device check
(killer-sudoku is local-only, its ADR 0002). Stage 4 is `swift build` / an `xcodebuild` for the macOS destination.
Stage 5 is screenshots of the running macOS app: the pipeline machines don't capture it, so the PR says so and
Gil reviews the look by running the app. "Anything sent to Apple" means notarization or the Mac App Store.
