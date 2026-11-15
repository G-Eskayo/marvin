Now I have the full picture. Let me write the plan.

## North-star fit

**Reuses:** the home-path regex pattern already proven twice in this codebase — `brain-map/export_snapshot.py:237-249` (`redact_home_paths`/`HOME_PATH`) and the inline one-off `dashboard/src/components/DocsExplorer.jsx:970` (`source.dir.replace(/^\/Users\/[^/]+/, '~')`) — generalized into one shared helper instead of a third copy. Reuses the existing cross-boundary import pattern electron/main already uses for pure `src/lib` helpers (`boards.js:7-8`, `deliverables.js:6`, `docs.js:1`, `docs_search.js:5`, `index.js:136,144` all do `import { x } from '../../src/lib/y.js'`), so the one helper is importable from both React components and `boot_data.js` without new plumbing.

**Simplest sufficient approach:** a single pure, dependency-free string function (`dashboard/src/lib/redact.js`) — no registry, no IPC, no network/Tailscale lookup. I checked whether the registry (`~/.claude/marvin-network.json`, read by `device_identity.js` and `boot_data.js`) stores a Tailscale IP anywhere so an IP could become the literal device name as the ticket's prose suggests — it doesn't (`lib/machine_profile.py` and the registry only ever carry `tailscale_hostname`, never an IP). Building IP→device resolution would mean new infrastructure (a `tailscale status` call or DNS resolution) threaded through every render site — exactly the kind of scope creep that likely drove this ticket's five prior timeouts/regressions. Redacting any IP (v4 or v6) to a generic, non-identifying placeholder satisfies the literal acceptance criterion ("no username, IP or private filename back") with zero new infrastructure. Flagged as a Decision below rather than assumed.

**Token/compute cost:** pure regex-based string transform, no file I/O, no async, no new dependencies (no `@testing-library/react`, no jsdom — the test suite's documented convention is `react-dom/server` static rendering only, per `dashboard/vitest.config.js`'s comment; a prior attempt may have broken this by reaching for DOM/timer testing tools it needed). One small new file plus small edits to 4-5 existing files. Tests are all synchronous, in-process, no fixtures beyond temp dirs already used by `boot_data.test.js`.

**Phone-OS direction:** installs other than the owner's are explicitly named in the ticket ("in other people's installs") — this is parity/safety work, not owner-specific, so it fits "general, reachable from anywhere" rather than hardcoding Gil's own paths.

**User impact:** purely protective (stops leaking the owner's filesystem layout, doc titles, and network topology on screen and in demos); it doesn't change what the user does, so it's neutral on the capable-vs-passive axis — pure safety/privacy hardening.

## Decisions

<!-- marvin:decisions -->
### ip-redaction: Tailscale/private IPs in status text — generic placeholder, or resolve to the real device name?
- [ ] A: Generic placeholder (e.g. "a device") for any IP found. No new infrastructure — the device registry only stores Tailscale hostnames, never IPs, so there's nothing to map from today.
- [ ] B: Build real IP→device-name resolution (new: a `tailscale status`-backed lookup or DNS resolution, threaded through every call site). Bigger, riskier change — likely contributor to this ticket's past timeouts.

## Tests (written first)

All in `dashboard/test/`, following existing conventions (`boot_data.test.js` for pure-logic temp-dir tests, `open_dev_site_button.test.jsx` for `react-dom/server` static-markup checks — no jsdom/timers, matching `vitest.config.js`'s stated convention).

**`dashboard/test/redact.test.js`** — the core helper, `redactPrivate(text)`:
1. IPv6 address → redacted (ticket's named attack).
2. A username that is also a common word (e.g. `/Users/user/...` next to the unrelated word "user" elsewhere in the same string) → only the path is redacted; the bare word survives untouched (proves matching is structural on `/Users/<name>`, never a literal username-string replace).
3. IPv4 address (including a realistic Tailscale CGNAT-range address, `100.x.x.x`) → redacted.
4. The real live leak from `lib/health_checks.py:1350` — `"...docs/plans/storage-and-distribution-2026-10-06.md"` → filename dropped, `docs/plans/…` kept.
5. The real live leak from `device_identity.js`'s `PY` path pattern — `"/Users/user/.agents/venv/bin/python: command not found"` → `"~/.agents/venv/bin/python: command not found"`.
6. All four leak types concatenated in one string (the realistic case — a single stderr blob mixing a path, an IP, and a plan filename) → all redacted in one pass, nothing missed by ordering.
7. Repeats: the same leak type appearing twice in one string → every occurrence redacted (global match, not just the first).
8. Bad/empty/malformed input: `null`, `undefined`, `123`, `{}`, `''` → returns input unchanged / `''`, never throws.
9. Huge input: a ~50,000-character string with many repeated leak patterns → completes well under the test's 5 s default timeout (guards against ReDoS from a sloppy backtracking regex — this is exactly the "huge/malformed input" adversarial case the north stars require for anything that touches text from a collaborator/process).
10. A string with no private content at all → returned byte-for-byte identical (no over-redaction of ordinary text, e.g. a plain version string or an unrelated dotted number that isn't a valid IPv4 octet sequence).
11. A string containing a `docs/plans/...md` path nested inside a `/Users/...` path (e.g. the real `~/.agents/instance/docs/plans/x.md` shape) → both layers redacted correctly regardless of application order.

**`dashboard/test/fade_message.test.js`** — the pure timing helper (`MESSAGE_FADE_MS`, `messageExpired(setAt, now)`):
12. `messageExpired` is `false` right after `setAt`, `false` just under 4 s later, `true` at/after 4 s.
13. `null`/`undefined` `setAt` → `false` (no message ever shown, nothing to expire).

**`dashboard/test/boot_data.test.js`** (extend existing file):
14. `handoffLine` no longer includes the handoff's slug/title — only the date — even when the newest handoff's filename encodes a private-sounding name.
15. `deviceReason`/`deviceLines`: a check `detail` containing a home path or a plan filename (as real `disk:space`/`jobs:exit` details can, per `lib/health_checks.py:1350`) comes out redacted in the boot's device-line text.

**`dashboard/test/marvin_button.test.jsx`** (new, static-markup only, matching existing convention):
16. Initial render (no message yet) shows no status text — existing behavior, regression guard.
17. Given a result whose `dir` is a raw home path (simulating what `marvin_session.py`'s real `"dir"` field looks like), the rendered message contains no `/Users/` substring — proves the component calls the redaction helper before display, not just that the helper exists in isolation.
18. Given an error result whose `error` is a raw stderr blob containing a path, the rendered error text is redacted the same way.

**`dashboard/test/health_drilldown.test.jsx` / extend `render_smoke.test.jsx`** (whichever existing file already covers `HealthDrilldown`/`CheckCard`/`RecentErrors`):
19. A check `detail` or a recent-error `raw`/`message` containing a home path, IP, or plan filename renders redacted, in each of the three render sites (`HealthDrilldown`'s detail block, `HealthDashboard`'s `CheckCard`, `RecentErrors`'s `e.raw`/`e.message`).

## Task List

1. Add `dashboard/src/lib/redact.js`: pure `redactPrivate(text)` — IPv6 regex, IPv4 regex (placeholder per the `ip-redaction` decision), `/Users/<name>` → `~`, `docs/plans/<slug>.md` → `docs/plans/…`. No registry/IPC dependency.
2. Add `dashboard/src/lib/fade_message.js`: `MESSAGE_FADE_MS = 4000` and pure `messageExpired(setAt, now)`.
3. Write `dashboard/test/redact.test.js` and `dashboard/test/fade_message.test.js` (tests 1-13 above) against the not-yet-correct/empty implementations, then implement `redact.js`/`fade_message.js` until green.
4. Wire `MarvinButton.jsx`: apply `redactPrivate` to `result.dir` and `result?.error` before putting them in `state.message`/error text; add a `useEffect` that clears `state.message` after `MESSAGE_FADE_MS` (clearing the timer on unmount/re-trigger). Write/extend `marvin_button.test.jsx` (tests 16-18).
5. Edit `boot_data.js`: `handoffLine` drops the slug (date only); `deviceReason` (and its caller `deviceLines`) run `c.detail` through `redactPrivate` before deriving the summary text. Extend `boot_data.test.js` (tests 14-15).
6. Apply `redactPrivate` at the three remaining render sites in `HealthDashboard.jsx` (`CheckCard`'s `check.detail`, `RecentErrors`'s `e.message`/`e.raw`) and `HealthDrilldown.jsx` (`check.detail`). Add/extend the corresponding component test (test 19).
7. Run the full dashboard suite (`npm test` in `dashboard/`) once, per [[feedback-full-suites-before-hand-merge]] — not just the new files — before calling this done, since a prior attempt on this same ticket regressed main.
8. Take 900px and 1440px screenshots of the MARVIN button message and a Health check detail panel showing redacted text, pin them on the PR (`marvin-show --pr N`), per the ticket's acceptance criterion.