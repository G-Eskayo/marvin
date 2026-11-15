No existing redaction test, confirming this is genuinely new. I have what I need to write the plan.

## North-star fit

**Reuses:** the component-logic-extraction pattern already used for `getDeviceStatuses`/`describeDevice` in `dashboard/electron/main/devices.js` + `dashboard/src/components/DeviceColumns.jsx:7` (pull the pure logic into a named export, test it directly, keep the component a thin wiring layer) and the injectable-timer factory pattern from `createTriggerHub` in `dashboard/electron/main/triggers.js:4` (tested with `vi.useFakeTimers`, never by mounting a component — this repo's tests render React only via `react-dom/server` per `dashboard/vitest.config.js:22`, so nothing here can depend on real effects/timers firing inside a render). The cross-process import pattern (`../../src/lib/...` from `electron/main/*.js`, e.g. `machine_names.js:1` → `src/lib/merge_progress.js`) is reused to let `boot_data.js` (main process) and the renderer components share one redaction helper instead of two implementations.

**Simplest sufficient approach:** one pure function, `redactText`, doing structural (not blocklist) matching — `/Users/<anything>` or `/home/<anything>` is a home path regardless of what the username is (defeats the "username that is also a common word" attack by construction, never by a word list), and *any* IPv4/IPv6 literal is masked unconditionally rather than trying to classify "Tailscale vs. private vs. public" — Tailscale's own CGNAT range is just IPv4, so one regex covers it with no special-casing. IPv6 detection requires a touch of care: a naive colon-group regex would also match duration text already shown in this UI (`0:05:31` in `main:green`'s detail, asserted in `boot_data.test.js`), so the rule only fires on an address-shaped token (`::` compression, a hex letter, or a full 8-group address) — never on pure-decimal, colon-separated clock/duration text.

**Where it saves/spends tokens:** spends a small, bounded diff (one new lib file + wiring at the exact sites named in the evidence) instead of sweeping all ~15 unrelated `.detail`/`.error` render sites across the dashboard (job-queue detail, workshop evidence, portfolio findings) — those don't share the health-status.json data source this bug is about, so pulling them in would be scope creep against north star 1. I note this scoping call below rather than silently expanding it.

**Phone-OS direction:** low — this is a trust/privacy hygiene fix (never breaks demos or other people's installs by leaking this install's layout), not a capability the OS vision depends on.

**More capable or more passive:** neither really — it removes an irritant (addresses the owner, not the user's judgment), and makes the dashboard safe to show other people, which is a precondition for MARVIN serving anyone beyond its developer (north star 3).

## Scoping note (made, not asked)

The Fix text says "every status/detail text," but the only sites proven to carry this install's private strings are the ones in the issue's own Evidence plus the two other places that render the *same* `health-status.json` check `.detail` field (`HealthDashboard.jsx` CheckCard, `HealthDrilldown.jsx`, and `ActivityBanner.jsx`, which all display raw `check.detail`). Other `.detail`/`.error` renders in the dashboard (dispatch badges, workshop evidence, portfolio findings) come from different, non-filesystem/non-network data and aren't evidenced as leaking anything — I'm leaving those alone rather than auditing the whole app under this ticket.

## Tests to write first

1. **`redact.test.js`** (new) — covers the ticket's break-it list plus the misuse cases it missed:
   - Evidence strings: `/Users/gileskayo/.agents/venv/bin/python` → `~/.agents/venv/bin/python`; a Tailscale-range IPv4 (`100.x.x.x`) in free text → masked; a `docs/plans/<slug>.md` reference → filename dropped.
   - **IPv6 address** (ticket's attack): `fe80::1`, `2001:db8::8a2e:370:7334`, a full 8-group address — all masked.
   - **IPv6 false-positive guard** (missed by the ticket, caught by reading `boot_data.test.js`): `'main @ abc1234: 2143 passed, 9 skipped in 331.58s (0:05:31)'` must come back **unchanged** — `0:05:31` must never be mistaken for an address.
   - **Username that is also a common word** (ticket's attack): `/Users/will/.claude/handoffs/...` and `/home/max/...` both redacted — proves it's structural, not a blocklist.
   - Windows path shape (`C:\Users\gil\...`) — this install isn't Windows, but the helper must not be Mac-only (north star 2).
   - Empty string, `null`, `undefined`, a number — no throw, safe/neutral return.
   - Huge input (a 300-char stderr slice packed with repeated paths/IPs) — all instances redacted (global match), no catastrophic-backtracking hang.
   - Multiple distinct private tokens in one string — all redacted, not just the first.
   - Idempotence — running `redactText` on its own output doesn't mangle it further.
   - A string with no private content at all — returned unchanged (no false positives on ordinary text).
   - A path already containing a literal `~` — left alone.
   - Case-insensitivity — `/USERS/Gil/...` and `/users/gil/...` both caught (so order of redaction vs. any `up()`/uppercasing elsewhere never matters).

2. **`fading_message.test.js`** (new) — `createFadingMessage()` with injected fake timers:
   - Fires `onClear` once at exactly `MESSAGE_FADE_MS` (4000ms), not before.
   - A second `show()` call before the first fires cancels the first timer — only the second clear ever runs (repeats/rapid re-trigger case).
   - `cancel()` before it fires means `onClear` never runs (the unmount case).
   - Calling `cancel()` twice, or before any `show()`, doesn't throw (person's mistake / wrong-order case).

3. **`marvin_button.test.js`** (new) — a pure `composeOpenMessage(result)` extracted from `MarvinButton.jsx`, covering:
   - Success: `Opened in ${result.dir}` comes back with the dir redacted.
   - `result.focused`: the existing "already open" message, untouched.
   - Failure: `result.error` (standing in for `marvin_session.js`'s up-to-300-char stderr slice) comes back redacted, truncation-length-preserving behavior unaffected.
   - Malformed `result` (`null`, `{}`, `{ok: false}` with no `error`) — falls back to the existing generic message, never throws.

4. **`boot_data.test.js`** (extend existing file) — adversarial additions:
   - Newest handoff **does** have a descriptive slug (today's only fixture happens not to exercise this — the file picked as "newest" coincidentally has no slug) → asserts the `PLOT` line is exactly `'HANDOFF · <date>'`, no topic words at all (this is the exact scenario the current code gets wrong).
   - A `machine:<id>` or `jobs:exit@<id>` check whose `detail` embeds a raw IP and a `/Users/<name>/...` path in its free-text portion (the generic fallback branch of `deviceReason`, not the disk-percent/job-count branches) → asserts the `LINK` line's text contains neither.
   - Confirms the existing disk-percent and job-count assertions (`'MAC-MINI-1 · DISK 10% FREE'`, `'... 3 JOBS FAILED'`) are unchanged — those branches never reach the raw-text fallback, so redaction must not touch them.

## Decisions

<!-- marvin:decisions -->
### fade-scope: should the 4-second auto-fade also apply to other header-button status messages?
The acceptance criterion only names the MARVIN button, but the Fix text says "status messages under header buttons" (plural). `PortfolioHub.jsx` has the identical `state.message`/`state.error` pattern under its own header button.
- [ ] This ticket only: MarvinButton. Extend `PortfolioHub.jsx` and any others in a follow-up ticket.
- [x] Do both now, reusing the same `createFadingMessage` helper in `PortfolioHub.jsx` too.

## Task List

1. Add `dashboard/src/lib/redact.js`: `redactText(text, { registry } = {})` — home-path→`~` (Mac/Linux/Windows shapes, case-insensitive), IPv4/IPv6 masking (with the duration-text false-positive guard), Tailscale/private IP or hostname → registry-resolved device name when `registry` is supplied, else a generic placeholder, and `docs/plans/<file>` / `handoff-<date>-<slug>.md`-shaped filename dropping.
2. Write `dashboard/test/redact.test.js` per the list above (TDD: these land before step 1's implementation is considered done).
3. Add `dashboard/src/lib/fading_message.js`: `createFadingMessage()` / `MESSAGE_FADE_MS`, with `dashboard/test/fading_message.test.js` written first.
4. Update `dashboard/src/components/MarvinButton.jsx`: extract `composeOpenMessage(result)` (named export, redacts via `redactText`), wire `createFadingMessage()` into `launch()` so `state.message` self-clears, cancel on unmount. Add `dashboard/test/marvin_button.test.js` first.
5. Update `dashboard/electron/main/boot_data.js`: `handoffLine()` stops including the filename's descriptive slug (date only); `deviceReason()` and `syncLine()` run their extracted text through `redactText` (passing the already-loaded `registry`) before it reaches `lines[].text`. Extend `dashboard/test/boot_data.test.js` first per item 4 above.
6. Wire `redactText(check.detail)` (no registry) into `dashboard/src/components/HealthDashboard.jsx`'s `CheckCard`, `dashboard/src/components/HealthDrilldown.jsx`'s detail panel, and `dashboard/src/components/ActivityBanner.jsx`'s red-check list.
7. Resolve the Decisions item above and, if "do both now" is chosen, wire `createFadingMessage` into `PortfolioHub.jsx`'s equivalent message state too.
8. Run the full dashboard test suite (`full suites before a hand-merge`), then take 900px and 1440px screenshots of the MARVIN button (message visible, then gone after 4s) and the Health tab (a check with a redacted detail open in drilldown) via `marvin-show`, per the PR's acceptance criterion.