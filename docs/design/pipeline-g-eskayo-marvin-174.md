## North-star fit

**Existing pattern reused:** `brain-map/DesktopLive/EventLog.swift` (the whole logging primitive: `write`/`format`/`quote`, 1 MB cap with one rotated `.1` copy) plus its call sites already wired through `brain-map/DesktopLive/main.swift` — `eventLog.write(...)` at `launch`, `window-created`/`-resized`/`-removed`, `page-loaded`, `page-load-failed` (with `error.localizedDescription`), `page-process-died`, every entry in `observeSystemEvents()` (sleep/wake/screens-sleep/screens-wake/session-inactive/session-active/display-change), and `exit` (SIGTERM + terminate). This is not a related pattern to borrow from — it **is** the ticket's ask, already built and merged to `main` (`5cb8c1ff`, extended by `2b0bb590`, `cd392d24`, `ec318191`). Checked line-by-line against the issue's event list above; nothing is missing.

**Simplest sufficient approach:** write no new code. Writing code to satisfy criteria already satisfied would be pure padding — exactly what the Colton check flags (imitating effort instead of checking whether the problem is already solved). The two prior automated attempts on this ticket likely failed *because* they manufactured changes to have something to show (one got sent back for "must-fix" review issues, the other for "no tests changed") against code that didn't need touching.

**Resource spend:** zero new files, zero new tests, zero tokens spent on implementation — directly serves north star 1 (minimise resources).

**Phone-OS direction:** neutral; this is a Mac-desktop reliability/diagnostics feature, not phone-OS-shaped either way.

**More capable or more passive:** Gil already gets the diagnostic trail he asked for (a wallpaper failure now leaves a trace). The one criterion left — AC4, sleeping/waking this physical MacBook and changing its display settings while reading the log — is a hands-on hardware action nobody but Gil can perform from this worktree; that's not a "coach vs. do" judgment call, it's a hard physical constraint. His own 2026-10-07 triage comment already called this "ready-for-human" for exactly that reason, before the queue re-flagged it for an agent twice.

## Tests already covering the breakage the ticket cares about

The ticket has no "How we'll try to break it" section, so per the guiding principle I checked misuse cases myself against what's actually touchable from code (EventLog is a local-only sink — no network/user input — so it isn't an "outward-facing" surface requiring adversarial-grade hardening):

- **Malformed field values** (newlines, embedded quotes, backslashes in an error string) → `EventLogTests.swift`'s `multi` case: escaped, never splits a line.
- **Oversized log** → rotation-at-cap case: file stays ≤ `maxBytes`, exactly one `.1` kept, no `.2`.
- **Missing log directory** (fresh install, deleted `~/.claude/logs`) → "creates missing directories" case.
- **Bare event, no fields** (`wake`) → covered.
- **Concurrent writers:** not applicable — every `eventLog.write` call site runs off a `Timer`/`NotificationCenter` callback on the main run loop, so writes are already serialized; nothing to test.
- **A single write failing (disk full / permission denied):** `append()` uses `try?` by design — logging must never crash the wallpaper it's describing. That's a pre-existing, correct choice from the original implementation, out of this ticket's scope to change.
- **AC4's actual cases** (real sleep/wake, real display reconfiguration, real session switch) are exactly the one thing that can't be exercised by a unit test in this environment — they need a running WindowServer and a human to trigger and read the result, which is why the ticket itself asks for a manual, on-machine check rather than a test.

No new test is needed because no new code is needed. I verified this by reading `main.swift`/`EventLog.swift` end-to-end rather than running `./test.sh` — Bash is denied in this plan-only session.

## Task List

TOO_VAGUE: N/A — not invoking this; the ticket is concrete, I'm just not following the default "write code" template below. Actual plan:

1. No code changes. Every event in "What to build" (launch, window created w/ screen+frame+scale, page load success, page load failure w/ error, wake from sleep, login/session change, display configuration change, WebKit content-process termination) already has a corresponding `eventLog.write` call in `main.swift`, and log size is already bounded (1 MB cap, one rotated copy) in `EventLog.swift`. AC1–AC3 are met by code already on `main`.
2. Before this ticket closes, run `brain-map/DesktopLive/test.sh` on the MacBook (requires `swiftc`, not available to run from this plan-only session) to reconfirm `EventLogTests`, `RecoveryTests`, `ActivityTests`, and the `main.swift` typecheck all still pass — a cheap regression check, not new work.
3. AC4 (sleep/wake + display-settings change, read on this MacBook) is the only open item, and it requires Gil physically on the machine — it cannot be done from this worktree. Comment on #174 (not a code PR) stating AC1–AC3 are satisfied by existing code and pointing at AC4 as the remaining step, so the pipeline stops re-queuing this as agent-buildable work.
4. Recommend the ticket go back to `ready-for-human` (as Gil himself set it on 2026-10-07) rather than being retried a third time against code that already does what's asked.