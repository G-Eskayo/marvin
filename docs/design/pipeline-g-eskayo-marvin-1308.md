## North-star fit

**Reuses before adding:** the whole "producer copy" stack from `marvin#1223` — `lib/stamped.py`/`dashboard/electron/main/stamped.js` (envelope + age/stale), `dashboard/electron/main/peer_copy.js` (`createPeerCopies().read()`, cache, newer-of-two), `dashboard/webhook-server/copy_route.js` (`GET /copy/<name>`, Tailscale-only), and the exact pattern `health.js`/`health_checks.py` already use end-to-end (`readHealthStatusFresh`, `write_status` → `stamped.write`). The only new code is extending that *same* machinery to one more file (`accounts-status.json`); nothing new is invented. `VitalsAccountsCard.jsx`'s `checkedAge` prop (PR branch) already has a slot for this — no new UI surface needed, just real data through it.

**Simplest sufficient approach:** 6 of 7 owner decisions are already built exactly as decided ("as built") — those need no code, only confirmation + the PR reply. Only `accounts_everywhere` ("serve accounts-status through the producer copy route") is undone today, and it is a same-shape extension of an existing, already-merged mechanism, not a new design.

**Tokens:** spends a small, one-time amount extending an existing pattern; saves by not re-litigating 6 settled decisions, and the reply closes the ticket (`lib/owner_decisions.py` loop) so it stops re-surfacing hourly.

**Phone-OS / human experience:** Gil gets a straight, grounded answer to a real question (the planet view isn't lost, it's nested in the evidence panel as #879) instead of a vague reassurance, and the MacBook stops lying about having "no" Mini accounts data.

**Machine:** read/write side runs on whichever Mac opens the dashboard; the producer side (sweep + `copy_route.js` server) already only runs on the Mini (`ctx.pull_only` gate, unchanged).

---

## Current state vs. the 7 decisions

Checked against the code (not assumed):

| id | Owner's answer | Built today? |
|---|---|---|
| `placement` | Over the map, on the left | ✅ as built (`vitals_view.js`/`VitalsMockup.jsx` on PR branch) |
| `watching` | "Also watching (N)" folded at bottom | ✅ as built |
| `accounts` | One panel per Mac, side by side | ✅ as built (`VitalsAccountsCard.jsx`) |
| `accounts_everywhere` | **Yes** — serve `accounts-status` via the producer-copy route (#1223) over Tailscale | ❌ not built. `lib/accounts.py:write_status` still plain `json.dump`, no stamp; `accounts-status` is absent from `copy_route.js`'s `COPY_NAMES`; `dashboard/electron/main/accounts.js:createAccounts` reads only the local file, no `peers` dependency |
| `evidence` | Right edge | ✅ as built |
| `limit` | 12 | ✅ as built |
| `look` | Keep the HUD style | ✅ as built |
| `notes` (question) | "What happened to the planet view? How many interactive views does Vitals have?" | Needs an answer, not code |

Only commit on the PR branch since the Decisions comment (19:12 UTC) is `fab2cfe7`, a conflict-repair **rebase onto main**, not an attempt to act on any of this — confirmed via `gh pr view --json commits` (author/committer timestamps) and the PR's own comment log. So nothing has actually been carried out yet; this plan is the real first pass.

## The owner's question — answer to post

- **"Whatever happened to the planet view?"** It wasn't dropped. In the 2026-10-29/30 grilling (Q7–Q8, recorded in `vitals-v5-2026-10-30.md` and ticket **#879**), the v4 Network view (which had the literal Planets visualization) was retired in favour of the live map as Vitals' front door. **Planets** (machines) and **Tunnel** (time) survive as two *modes inside a row's evidence panel*, not a separate page — that's #879, explicitly scheduled "after the demo" (build order step 6), so it's correctly out of scope for #873's mock-up and absent from these captures.
- **"How many interactive views do we have on Vitals?"** In this mock-up: **3** — (1) the verdict line + "what needs you" column (switchable over/below the map), (2) the live map itself (hover/tap spotlight), (3) the evidence panel opened by tapping a row — plus the redesigned Accounts card. Counting the rest of Vitals: the permanent **Loops view** (#1134, every loop) is a 4th. Once **#879** ships, Tunnel and Planets add two more, nested *inside* the evidence panel rather than as standalone views.

## Earlier answers (supersession check, `lib/supersession.py`, marvin#1226)

None of the four restates a *different* answer to any of today's 7 decision ids — each only cites `#836`/`#873` for an unrelated purpose. Kept, with a dated note rather than an "Amendment", since nothing is being corrected:
- `data-freshness-2026-11-09.md` — cites #836 as the "honest data" dependency for Vitals' stamped-copy design (which is exactly what `accounts_everywhere` now also uses). Kept as-is.
- `tab-consolidation-intent-and-gaps-2026-11-09.md` — cites #836 (evidence contract) and #873 (the mock-up ticket itself); its own Decisions (`vitals-verdict`, `map-work-half`) are different ids. Kept as-is.
- `vitals-v5-2026-10-30.md` — §8 already settled `placement` the same way (2026-11-04); `evidence`/`limit`/`look`/`watching`/`accounts` aren't recorded there at all. Add a short dated note (not an amendment — nothing contradicts) pointing these settled answers at their spec sections, and record `accounts_everywhere`'s outcome once built.
- `memory/project-vitals-v5.md` — update "How to apply" to say the 2026-11-12 Decisions are carried out, so a future session doesn't re-ask them.

## Tests first

**A. `lib/accounts.py` — `write_status` gains the stamp (mirrors `health_checks.write_status`)**
1. Happy path: after `write_status`, `stamped.read()` on the file returns non-missing, non-legacy, with `host`/`hardware_uuid`/`tolerance_s` present.
2. Misuse: `write_status` called with a non-dict payload raises the same `TypeError` `stamped.write` already guarantees (bad input).
3. Round-trip: a file written by `write_status` is still readable by the *old* plain-`json.load` reader (no breaking change for anything not yet updated).

**B. `dashboard/webhook-server/copy_route.js` — add `accounts-status` to the allow-list**
4. `GET /copy/accounts-status` from an allowed Tailscale/loopback peer → 200 + file contents (happy path).
5. Same request from a disallowed address → 403 (dependency/permissions: wrong caller).
6. File absent (fresh Mini that hasn't swept yet) → 404 "not here yet" (empty state).
7. File over `MAX_BYTES` → 413 (huge input).
8. File content not a JSON object (truncated/garbled/array) → 502, body never echoed (malformed input).
9. A name that isn't exactly `accounts-status` (e.g. `accounts-status-evil`, `../../etc/passwd`) → 404, confirming the allow-list isn't widened by a prefix match (misuse / path traversal).

**C. `dashboard/electron/main/accounts.js` — `createAccounts` takes a `peers` reader**
10. Producer Mac: `list()` never calls `fetchCopy` — reads its own file only (no regression on the Mini).
11. Standby Mac, local copy fresh: no network call, local wins.
12. Standby Mac, local stale/missing, producer reachable and fresher: returns the producer's rows, `copy.from === 'producer'` — the exact MacBook-today scenario from the PR description.
13. Standby Mac, producer's copy itself stale or *older* than local: keep local, flagged `producerOlder` (never silently prefer a worse copy — stale-state case).
14. Standby Mac, producer unreachable (timeout/refused/Tailscale down) or sends oversized/malformed JSON: falls back to local with `producerUnreachable: true`, never throws (dependency failing).
15. `mergeLocal` regression: when the saved view now legitimately holds *every* Mac's rows (from the producer), a fresh local check still swaps only this machine's rows and keeps every other machine's exactly once — no dup, no drop (repeats/each-machine-once).
16. Repeats: two `list({fresh:false})` calls inside `peer_copy.js`'s `CACHE_MS` window issue one producer fetch, not two (reuses `peer_copy.js`'s existing cache contract).
17. `MARVIN_CAPTURE_ACCOUNTS` override stays deterministic with `peers` wired in: the fixture file is read as local/fresh, no network attempt (a person's mistake — captures must never depend on live Tailscale).

**D. `dashboard/src/components/VitalsAccountsCard.jsx` (PR branch)**
18. `checkedAge` shows "Mini, as of N min ago" (via `describeCopy`) when data came from the producer, not just a bare "checked N ago".
19. Fresh MacBook, never swept, producer unreachable: the existing "No accounts read yet…" empty state still renders and says it couldn't reach the Mini, rather than looking indistinguishable from "all fine."

No Decisions section is needed — every owner choice here is either already answered (6 of 7, "as built") or explicitly spells out the mechanism to use (`accounts_everywhere` names #1223 by number); nothing is ambiguous enough to put back to Gil.

## Task List

1. `lib/accounts.py`: add `ACCOUNTS_TOLERANCE_S = 20 * 60` (same as Health's sweep cadence); change `write_status` to call `stamped.write(path, status, tolerance_s=ACCOUNTS_TOLERANCE_S)` instead of the raw `json.dump`. Add tests 1–3 to `lib/tests/test_accounts.py`.
2. `dashboard/webhook-server/copy_route.js`: add `'accounts-status'` to `COPY_NAMES` and `COPY_PATHS` (→ `~/.claude/logs/accounts-status.json`). Add tests 4–9 to `dashboard/test/copy_route.test.js`.
3. `dashboard/electron/main/accounts.js`: add a `peers` option to `createAccounts`; in `list()`, when `peers` is given, read the saved view through `peers.read('accounts-status', statusPath, { defaultToleranceS: ACCOUNTS_TOLERANCE_S_MS })` (mirroring `readHealthStatusFresh`) instead of calling `readAccountsStatus` directly, carrying `copy` metadata (`host`, `ageS`, `stale`, `from`, `producerUnreachable`, `producerOlder`) onto the returned object; keep `mergeLocal` unchanged underneath it. Add tests 10–17 to `dashboard/test/accounts.test.js`.
4. `dashboard/electron/main/index.js`: pass `peers: peerCopies` into the existing `createAccounts({...})` call (the `peerCopies` instance already exists for Health).
5. On PR branch `vitals-mockup-873`'s `VitalsAccountsCard.jsx`: feed `copy`'s `describeCopy()` text into the `checkedAge` prop instead of the raw `generatedAt` diff, and adjust the empty state to mention an unreachable producer. Add tests 18–19 (extend `dashboard/test/accounts_view.test.js` / a component test).
6. Retake the Accounts-card screenshots (`dashboard/scripts/vitals_mockup_evidence.mjs`) at 1440 and 860 px showing a standby-Mac view with cross-Mac accounts and the "Mini, as of N min ago" label, and re-pin them to the new commit in PR #1291's description (screenshots must match the commit, per the PR-images rule).
7. `instance/docs/plans/vitals-v5-2026-10-30.md`: add a short dated note (not an "Amendment" — nothing is contradicted) recording where `watching`, `accounts`, `evidence`, `limit`, `look` and `accounts_everywhere` now live in the spec, and that `accounts_everywhere` is served through #1223's producer-copy route.
8. `~/.claude/projects/-Users-gileskayo/memory/project-vitals-v5.md`: update "How to apply" to note the 2026-11-12 Decisions are carried out.
9. Run the full dashboard (`vitest`) and Python (`pytest lib/tests/test_accounts.py`) suites, plus the existing `brain-map` and `vitals_*` suites untouched by this change, to confirm nothing else regresses (per "full suites before a hand-merge").
10. Post the PR #1291 reply carrying `<!-- marvin:decisions-addressed -->`: name the commit, confirm each of the 6 "as built" decisions, describe the `accounts_everywhere` change and the retaken/pinned screenshots, answer the owner's planet-view and interactive-views question (text above), and state the outcome (kept vs. noted) for each of the 4 earlier-answer docs and the memory file.
11. Close out ticket #1308 once the PR reply is posted (the ticket closes itself per `lib/owner_decisions.py` once PR #1291 is addressed).