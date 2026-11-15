## North-star fit

- **Reuses:** the #1223 producer-copy mechanism end to end — `dashboard/electron/main/peer_copy.js`'s generic `createPeerCopies().read(name, localPath, opts)` (already name-agnostic, proven by `dashboard/test/peer_copy.test.js`), the `GET /copy/<name>` route (`dashboard/webhook-server/copy_route.js`) and `stamped.js`'s `fromData`'s existing **legacy** fallback (mtime-dated) for a file that doesn't carry the full `host/hardware_uuid/generated_at/alive_at/tolerance_s` envelope — exactly `accounts-status.json`'s current shape (`lib/accounts.py:474` writes only `generated_at`/`by`/`accounts`). `health.js`'s `readHealthStatusFresh`/`copyMeta` (lines 51–57) is the pattern to copy verbatim into `accounts.js`. No new mechanism, no Python change, no new timer or network scheme.
- **Simplest sufficient approach:** everything else the ticket's "chosen options" ask for is **already built** on `vitals-mockup-873` at its current head (`fab2cfe7` — confirmed only one real commit on the branch since the decisions comment; the later "Stuck sweep" rebase only touched `App.jsx`'s merge conflict, nothing Vitals). Verified directly against `dashboard/src/components/VitalsMockup.jsx` / `vitals_view.js`: `placement` defaults to `'overlay'` (over the map), `evidence` renders at the right edge, `COLUMN_LIMIT = 12`, amber-not-broken rows fold into "Also watching", one Accounts panel per Mac already exists. So five of the seven decisions need **zero code**, only a reply confirming them. Only `accounts_everywhere` is real new work, and it is a thin wiring change, not a new subsystem.
- **Spends tokens on:** the one gap that's real (cross-Mac accounts data) and on reading the owner's actual question correctly (traced "planet view" to the v4 prototype and ticket #879) instead of guessing. Saves tokens everywhere else by reusing existing code/pattern rather than re-verifying from scratch.
- **Leaves Gil more capable:** answers his question with the actual history/ticket trail instead of a vague reply, and the MacBook's Accounts card stops being silently incomplete (today it only shows its own machine, with no indication anything's missing).
- **Where it runs:** Electron main process, on whichever Mac isn't the producer (the Mac mini); on the producer nothing changes (peers.read skips the network call when `isProducer()`).

**Correction to the ticket's framing:** none needed — the ticket's own framing ("check whether they carry out every choice, finish what they don't") matches what I found: most are already done, one isn't.

**Note against CONTEXT.md:** the "Stamped copies" section (`CONTEXT.md:2064-2076`) names exactly four files as carrying the full stamp envelope. `accounts-status.json` is not one of them and isn't being changed to carry one — it rides the same `GET /copy/<name>` route as a **legacy** (mtime-dated) copy, which `stamped.js` already supports by design. This doesn't contradict the recorded decision, but the doc will go stale if left unmentioned, so updating that bullet to note the fifth, legacy-shaped file is in scope.

## Tests to write first

From the ticket's "How we'll try to break it":
1. **"The notes contradict a chosen option"** → a doc-consistency check, not code: before writing the reply, re-diff each of the 4 cited docs against today's 7 decisions (done in planning above) and record amend-or-keep with a reason for each, instead of asserting correctness blind.
2. **"The PR changed since the decisions"** → re-confirmed via `git log origin/vitals-mockup-873` that the only commit since the decision timestamp is the main-rebase merge, which doesn't touch any Vitals file — re-verify this again at implementation time in case someone pushes in the meantime.

Code tests (for the one real change, `accounts_everywhere`), extending `dashboard/test/accounts.test.js` (mirrors `peer_copy.test.js`'s own break-list):
3. A fresh local `accounts-status.json` (within tolerance) is used with no network call, same as `peer_copy.test.js`'s "fresh local copy" case.
4. A stale local copy on a non-producer Mac fetches the producer's copy and returns it, labelled with its host and age (`copy.from === 'producer'`).
5. Producer asleep / Tailscale down: own stale copy returned, `copy.producerUnreachable === true` — never silently empty, never shown as current.
6. On the producer itself, nothing is fetched even when "stale" (no self-call).
7. A reply that isn't a JSON object / is an array / has no accounts array / is `null` — ignored, falls back to the local copy, never throws.
8. Missing local file entirely + producer reachable → uses the producer's copy (same as `peer_copy.test.js`'s "no file here" case).
9. `fresh: true` (this machine's own live `accounts.py check`) still only replaces this machine's own rows on top of whichever base (local or producer) was used — `mergeLocal` unchanged, re-run existing `mergeLocal` tests to confirm no regression.
10. `dashboard/test/copy_route.test.js`: extend to prove `/copy/accounts-status` serves 200 with the file's content, and still refuses non-Tailscale IPs, non-GET, oversized, and non-JSON for the new name (the existing parameterized tests are name-driven so this is a small, not a new, surface).
11. Capture mode (`MARVIN_CAPTURE_ACCOUNTS` override): confirm `peers` is **not** wired when the override is active, so the evidence-capture script stays network-free and deterministic (misuse case: don't let a new wiring regress the screenshot pipeline).
12. Renew path unaffected: a row whose `machine` isn't locally known (because it came from the peer copy) still falls back to "run this command on `<Mac>`", never attempts a local tab for another machine — regression check on `renewPlan`, no behavior change intended.

## Decisions

None. This ticket answers the owner's existing Decisions on PR #1291; it doesn't raise a new choice for him. The "notes" field was a question, not a decision, and is answered directly (see Task List).

## Task List

1. `dashboard/webhook-server/copy_route.js`: add `'accounts-status'` to `COPY_NAMES` and its path (`~/.claude/logs/accounts-status.json`) to `COPY_PATHS`; update the file's header comment ("only the four names below") to five.
2. `dashboard/test/copy_route.test.js`: add the `/copy/accounts-status` coverage (test 10 above).
3. `dashboard/electron/main/accounts.js`: add `readAccountsStatusFresh(peers, statusPath, opts)` + `copyMeta`, mirroring `health.js:51-57` exactly; thread an optional `peers` param through `createAccounts({ peers })`'s `list()` so the base read goes through `peers.read('accounts-status', ...)` when `peers` is supplied, else falls back to today's `readAccountsStatus` (unchanged default — no behavior change for the producer Mac or for tests that don't pass `peers`).
4. `dashboard/test/accounts.test.js`: add tests 3–9, 12 above.
5. `dashboard/electron/main/index.js`: pass `peers: peerCopies` into the existing `createAccounts({...})` call, but only outside evidence-capture mode (keep the existing `captureOverride(... 'MARVIN_CAPTURE_ACCOUNTS')` branch exactly as today; add `peers` only on the non-capture branch) — test 11 above covers this.
6. `CONTEXT.md` "Stamped copies" section: add one line noting `accounts-status.json` now rides the same `GET /copy/<name>` route as a legacy (unstamped, mtime-dated) copy — the four fully-stamped files stay as listed.
7. `~/.agents/instance/docs/plans/vitals-v5-2026-10-30.md` (separate repo, `marvin-instance`): add an "Amendment (2026-11-12)" note under the Accounts section recording the `accounts_everywhere` decision and linking marvin#1308/PR #1291, as its own small PR against `marvin-instance` (linking back to #1291, per the ticket's "if the work belongs in a new PR, link PR #1291 from it").
8. Run the full dashboard test suite (not just the touched files) before pushing, per the "full suites before a hand-merge" rule.
9. Push the above as a new commit on branch `vitals-mockup-873` (not a new PR) — retake no screenshots: the existing captures already came from the Mac mini's saved sweep (the full multi-machine view), which is exactly what the MacBook now also shows once stale; the look is unchanged.
10. Post the reply on PR #1291 carrying `<!-- marvin:decisions-addressed -->`, covering:
    - All 6 "(as built)" decisions: already satisfied at the PR's current commit, nothing changed for them.
    - `accounts_everywhere`: implemented in commit `<sha>`, via the existing #1223 producer-copy route; screenshots not retaken (reason above).
    - The owner's question: the "planet view" is the v4 prototype's per-machine orbiting-jobs view (`~/.agents/instance/docs/screenshots/vitals-v4/planets.html`); the 2026-10-29/30 grilling retired v4's separate Network/Tunnel/Planets switcher in favor of the live map as Vitals' single background, and moved Tunnel + Planets into a part's evidence panel as a later ticket, **#879** ("Vitals evidence modes: Tunnel and Planets"), explicitly scheduled after the investor demo and not yet built. So today, counting the mock-up's interactive surfaces: the live map (hover-spotlight), the "what needs you" column (worst-first, fold/unfold, show-all), the evidence drawer, and the Accounts card — one tab, four interactive parts, not separate "views"; #879's Tunnel/Planets will add two more once built.
    - The 4 cited docs: `vitals-v5-2026-10-30.md` amended (new line, step 7); the other three (`data-freshness`, `tab-consolidation`, memory note `project-vitals-v5.md`) kept unchanged, each with the one-line reason from the analysis above (background investigation / unapplied proposal / already-correct anticipatory note).
11. Verify the `project-vitals-v5.md` memory note's existing "2026-11-12" line (host/ageS/stale/from/producerUnreachable) still matches what was actually built; fix it if it drifted during implementation.