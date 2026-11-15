## North-star fit

**Reuses before adding:** the entire accounts_everywhere fix is an application of the already-built, already-tested producer-copy pattern from #1223 — `dashboard/electron/main/stamped.js` / `lib/stamped.py` (the envelope), `dashboard/electron/main/peer_copy.js`'s `createPeerCopies().read(name, localPath, opts)`, `dashboard/webhook-server/copy_route.js`'s `/copy/<name>` route, and the exact two-function split `health.js` already uses (`readHealthStatus` sync-local / `readHealthStatusFresh(peers, statusPath)` producer-aware) and its wiring at `index.js:470` (`ipcMain.handle('health:status', () => readHealthStatusFresh(peerCopies))`). The `peerCopies` singleton (`index.js:156`) already exists and is reused unchanged. No new abstraction is added — this is the fourth reader of the same mechanism (health, ticket-agent proposals, dispatch-state, board registry already use it).
**Simplest sufficient:** everything else the owner chose is **already built** ("as built" was selected on 6 of 7 options) — most of this ticket is verification, not construction. The one real gap (accounts_everywhere) is closed by extending an existing allowlist and copying an existing 15-line pattern, not designing something new.
**Tokens:** spent mainly on reading (confirmed exact file/line reuse points) rather than invention; the build itself is a small, mechanical diff. No new Claude calls anywhere in the fix (pure data-plumbing + a doc/memory correction).
**Phone-OS / capable, not passive:** closes a real gap Gil would otherwise hit personally (the MacBook silently under-reporting Accounts); the owner's two questions get grounded, sourced answers instead of a vague "not sure," so he isn't left to go dig it up himself.
**Machine:** this runs wherever the dashboard runs (as Health's copy-of-copy already does); no new machine dependency.

**Important correction found while planning, not yet acted on:** `~/.claude/projects/-Users-gileskayo/memory/project-vitals-v5.md` already contains a line dated 2026-11-12 claiming *"Accounts card now uses producer-copy routing for cross-Mac display (ticket #1308); copy metadata carries host, ageS, stale, from, producerUnreachable flags to the UI."* This is **false as of right now**: `git log origin/vitals-mockup-873` shows only the original mock-up commit (`fab2cfe7`); nothing implementing this exists on the branch or on `main`. It was written by one of the two earlier failed automated attempts on this ticket (issue comments show "did not pass verification" / a failed `git commit`), before the work actually landed. This is exactly the stale-cache pattern `instance/docs/plans/data-freshness-2026-11-09.md` warns about (incident type A: a claim written once, never re-checked). It must be fixed as part of this ticket, not left to mislead the next session.

---

## Tests to write FIRST

Per `instance/docs/plans/data-freshness-2026-11-09.md`'s own "how we'll try to break it" entries for #1223, plus the ticket's two generic attacks ("notes contradict a chosen option" / "the PR changed since"), plus standard misuse coverage:

1. **`lib/tests/test_accounts.py`** — `write_status()`/`sweep_and_alert()` output now carries the stamp envelope (`host`, `tolerance_s`) via `stamped.stamp()`, **and** the file keeps its existing `0o600` permission (extend the existing `test...0o600` assertion, don't regress it).
2. **`lib/tests/test_accounts.py`** — a legacy `accounts-status.json` with no `host`/`tolerance_s` (today's on-disk shape) still round-trips through `check`/`sweep` without crashing (backward compatibility for files already on disk).
3. **`dashboard/test/accounts.test.js`** — new `readAccountsStatusFresh(peers, statusPath)`:
   - local copy fresh, or this Mac is the producer → returns local, no producer call.
   - local copy stale, this Mac is **not** the producer → `peers.read('accounts-status', statusPath, {...})` is used; result's `copy.from === 'producer'`.
   - producer unreachable (Tailscale down, timeout) → falls back to the stale local copy with `copy.producerUnreachable === true`, **never** reported as fresh/green.
   - producer's copy is itself missing or unparsable → same safe fallback.
   - no file at all (fresh machine) → unchanged `{generatedAt: null, by: null, accounts: [], problem: 'missing'}` shape, no crash.
   - both local and producer copies are stale → the fresher of the two wins (reuse `newerCopy`), still marked stale with age and Mac — never silently "current."
4. **`dashboard/test/accounts.test.js`** — `createAccounts({ ..., peers })`'s `list({fresh:false})` uses the peers-aware path when `peers` is supplied, and **existing tests that don't pass `peers` are untouched** (back-compat); `list({fresh:true})` still runs this machine's own live check and `mergeLocal` replaces only this machine's rows, even when the "saved" view came from the producer (repeat calls don't duplicate rows).
5. **Attack coverage reusing existing generic suites** (no new logic, just extend the parametrized lists):
   - `dashboard/test/copy_route.test.js`: add `'accounts-status'` to the fixture paths used by the already-parametrized traversal/oversize/wrong-method/wrong-IP/malformed-JSON cases (`COPY_NAMES` drives them, so this is additive, not new code).
   - Confirm (by test) `/copy/accounts-status` is refused off-Tailscale/off-loopback exactly like the other three — same `allowedPeerAddress` gate, no new auth path to get wrong.
   - Confirm the 60s `CACHE_MS` read-through cache in `peer_copy.js` keys by name, so repeated `accounts:list` calls don't hammer the Mini (existing behavior, add one assertion if not already covered for a second name).
6. **UI**: no new test expected to be needed — `accountsBoard()`/`VitalsAccountsCard.jsx` already group purely by the `machine` field on whatever rows arrive and carry no assumption that rows are locally sourced; verify this by reading, and only add a test if that assumption turns out to be wrong once the real data flows through.
7. **Process checks, not code tests:** re-read PR #1291 immediately before pushing (it may have gained comments since this plan was written); the four "earlier answers" files are checked for restatement of today's 7 decisions and amended or explicitly kept — verified by reading the diff in review, not by an automated test.

---

## Earlier-answers check (done now, to act on during build)

Using the existing tool this ticket's checklist came from (`lib/supersession.py`, marvin#1226 — it only lists, never edits, per its own docstring), plus a manual read since none of the four hit by decision-id (all four were found only "by relation," i.e. citing #836/#873 generically):

- `instance/docs/plans/data-freshness-2026-11-09.md` — cites #836 only as part of the general stamped-copy mechanism (piece 2). Doesn't restate any of today's 7 decisions. **Keep as is**, note why in the reply.
- `instance/docs/plans/tab-consolidation-intent-and-gaps-2026-11-09.md` — cites #836, #873 for the Workshop/Vitals pipeline-vs-machine split (decisions `vitals-verdict`, `map-work-half`), a different question than today's 7. **Keep as is**, note why.
- `instance/docs/plans/vitals-v5-2026-10-30.md` — **genuine contradiction found**: its "Folded in without new questions" bullet says *"Accounts (#640) ... → loops, shown as rows only when broken"*. The owner's 2026-11-11 redesign and today's `accounts` decision ("One panel per Mac, side by side, as built") show **every** account, not just broken ones, as its own card. **Needs an "Amendment (2026-11-12)" note** pointing at the built `VitalsAccountsCard`/`accounts_view.js` design and decisions `accounts`/`accounts_everywhere`.
- `~/.claude/projects/-Users-gileskayo/memory/project-vitals-v5.md` — **stale/false claim found** (see North-star fit above): the 2026-11-12 line claims accounts_everywhere is already implemented. It isn't. **Must be corrected** to either remove the premature claim or rephrase it as "planned, landing in #1308" until the real PR commit exists, then updated again once it actually merges.

---

## Owner's question, answered from the record (no new Decisions needed)

> *"So what ever happened to the planet view on Vitals? How many interactive views do we have on vitals?"*

- **Planets never got dropped.** It's ticket **#879**, *"Vitals evidence modes: Tunnel (time) and Planets (machines) as views of a part's evidence"* — open, p3. Per `vitals-v5-2026-10-30.md`'s decided Q7–Q8, the old v4 **Network view is retired** in favor of the live map, and Tunnel + Planets become **tabs inside a row's evidence panel** (not separate pages), ported from the v4 prototype onto live per-Mac data. The spec's build order puts it explicitly **after** this mock-up/demo (step 6), so it's deferred, not forgotten.
- **Interactive views today, in this mock-up:** one — the evidence panel opened by tapping a "what needs you" row (reason, age, Mac, confidence, fix, loop steps). The map's hover/point highlighting and the over/below placement toggle are interactions, not separate views. Two more (Tunnel, Planets) are planned as tabs inside that same evidence panel via #879.

This answer, plus what changed and the screenshot verdict, goes into the PR reply carrying `<!-- marvin:decisions-addressed -->` (matching `owner_decisions.py`'s `ADDRESSED_MARKER`), per `docs/agents/decisions-format.md`.

**Screenshots:** the look doesn't change — `VitalsAccountsCard`/`accounts_view.js` get no code changes, and the existing captures were already taken from the Mac mini's full sweep (per their own caption), so they already show the multi-Mac layout the fix extends to the MacBook. The reply states the images stand, with that reason given explicitly (not silently assumed).

## Decisions

No new Decisions section is needed — every choice here extends an existing, already-approved pattern 1:1 (the same envelope, the same read helper, the same route gate, the same tolerance value Health already uses). Nothing is ambiguous enough to put back to Gil.

---

## Task List

1. **Re-read PR #1291 and issue #1308 live** immediately before starting (ticket's own warning: "the PR changed since the decisions"), to catch any comment added after this plan was written.
2. **Backend stamp:** in `lib/accounts.py`, call `stamped.stamp(status, tolerance_s=ACCOUNTS_TOLERANCE_S)` (new constant, `20 * 60`, matching `health_checks.py`'s `STATUS_TOLERANCE_S`) inside `write_status()`, keeping the existing secure 0600 temp-file-rename write unchanged.
3. **Serve route:** add `'accounts-status'` to `COPY_NAMES` and `COPY_PATHS` in `dashboard/webhook-server/copy_route.js` (update the "four files"/"four names" comments to five).
4. **JS reader:** in `dashboard/electron/main/accounts.js`, add `ACCOUNTS_TOLERANCE_S = 20 * 60` and `readAccountsStatusFresh(peers, statusPath = ACCOUNTS_STATUS_PATH)`, mirroring `health.js`'s `readHealthStatusFresh` exactly (`peers.read('accounts-status', statusPath, { defaultToleranceS: ACCOUNTS_TOLERANCE_S })`, mapping to `{generatedAt, by, accounts, problem, copy}`).
5. **Wire it in:** give `createAccounts()` an optional `peers` param; when present, `list({fresh:false})` uses `readAccountsStatusFresh(peers, statusPath)` instead of the plain sync read; `list({fresh:true})`'s local-check/`mergeLocal` path is unchanged. Update the call site at `dashboard/electron/main/index.js:191` to pass `peers: peerCopies` (the singleton already created at line 156).
6. **Tests** for steps 2–5, per the "Tests to write FIRST" list above, written and red before the implementation, then green after.
7. **Amend** `instance/docs/plans/vitals-v5-2026-10-30.md`'s Accounts-folds-into-loops bullet with an "Amendment (2026-11-12)" note.
8. **Correct** the stale 2026-11-12 line in `~/.claude/projects/-Users-gileskayo/memory/project-vitals-v5.md` so it no longer claims unmerged work as done.
9. **Note, don't edit:** state in the PR reply why `data-freshness-2026-11-09.md` and `tab-consolidation-intent-and-gaps-2026-11-09.md` are kept as-is (different questions, no restatement).
10. **Post the PR reply** on #1291 carrying `<!-- marvin:decisions-addressed -->`: what changed (naming the commit), the screenshot verdict and why, the answer to both parts of the owner's question (Planets = #879, deferred; 1 interactive view today), and the earlier-answers disposition for all four files.
11. Run the full relevant suites (`lib/tests` accounts + stamped, `dashboard/test` accounts/copy_route/peer_copy/vitals_*) before pushing, per the full-suites-before-hand-merge rule.