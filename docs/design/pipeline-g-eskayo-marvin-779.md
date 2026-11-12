## North-star fit

**Reuses:** `dashboard/electron/main/device_identity.js` (`resolveDeviceId`, registry loader pattern), `dashboard/electron/main/github_feed.js`'s `readNetworkRegistry` (the one JS reader of `~/.claude/marvin-network.json`, already used by `machine_names.js`), `dashboard/electron/main/machine_names.js`'s `machineNames` (device → display label, built on `src/lib/merge_progress.js`'s `machineLabel`), and `lib/box_memory_review.py`'s `_home_slug()` (`str(Path.home()).replace("/", "-")`) as the proven algorithm for the memory-dir slug boot_data.js currently hardcodes. No new module is needed — `boot_data.js` already imports sibling main-process helpers this way (`health.js`, `stamped.js`); this just adds two more imports from existing files.

**Simplest sufficient approach:** the bug is that `boot_data.js` has device/owner knowledge baked in instead of reading it from the registry it already has a JS reader for. Generalizing `syncLine`/`miniLine` into one per-device pair, and `memoryDir` into a one-line slug function, removes the hardcoding without inventing new abstractions (ADR 0071 step 3, part of #646 — same pattern other dashboard files already use for the owner/repo).

**Tokens:** spends a small amount reading a few more sibling files up front; saves going forward because every future non-Gil install stops rendering fabricated WARN lines (and the #646 ratchet test's grandfathered list shrinks by one, which is the point of that epic).

**User capability:** this is pure correctness/truthfulness of a status display — it doesn't change what Gil does, it stops MARVIN lying to a different installer about problems that don't exist.

**Machine:** no change — this is Electron main-process code, runs wherever the dashboard runs.

**Ticket's stated fit:** none was stated in the issue body; the above is derived directly from the code.

One correction to the ticket's own phrasing: "Read the memory dir from `homedir()` (**and the instance**)" — I read "the instance" here as plain English ("this particular install"), not a literal call into `dashboard/electron/main/instance.js` (which only knows engine repo/owner/feature flags, nothing about home directories or memory paths). `homedir()` alone is sufficient and is what `lib/box_memory_review.py`'s Python twin does.

## Design decisions resolved from evidence (no owner input needed)

- **First-run condition is `health === null AND no remote devices in the registry`, not `health === null` alone.** A missing health file on Gil's real two-Mac registry must keep saying "HEALTH UNKNOWN · OPEN HEALTH" (an established install with broken monitoring is a real problem, not a fresh install) — confirmed by the existing, currently-passing test for that exact case. The ticket's own AC1 test fixture (fake home **and** one-Mac registry, together) backs this reading. Health-present-but-0-checks stays on the existing "unknown" path too (explicitly called out in "how we'll try to break it").
- **"No handoff yet" is unconditionally neutral** (not tied to first-run) — the ticket states this as a standalone fix, and it's one of the bug's listed symptoms on *any* install, not just fresh ones.
- **TEST's neutral "not yet run" state uses the same first-run condition as the verdict** (health null + no peers), so an established install with a broken health cron still correctly warns.
- **Per-device SYNC/LINK text uses the registry's own label** (`machineNames` → `machineLabel`, e.g. "Mac mini" → `MAC-MINI`), not the old made-up "MBP ⇄ MINI" abbreviation. For Gil's actual setup this reproduces today's `LINK` text byte-for-byte (`MAC-MINI · DISK 10% FREE` etc., already pinned by existing tests); `SYNC`'s old text was never asserted anywhere, so this is a clean, equivalent generalization, not a behavior loss.
- **First-run banner/subtitle use the existing "orange" accent tone** already used for ORIGIN/lock/bar-fill/default-subtitle in this design language (amber=warning, red=critical, orange=neutral/accent) — not a new color.

## Tests first

All in `dashboard/test/boot_data.test.js` unless noted; `tree()` gains `registry`/`selfId` params defaulting to Gil's real two-device shape (`macbook-pro-1` as self, `mac-mini-1` as the one peer) so the existing suite keeps its current meaning.

1. `homeMemoryDir(home)` (new exported pure fn) with a normal home, a home containing spaces, and a root/trailing-slash home — matches `home.replace(/\//g,'-')`, never throws.
2. One-Mac install (empty `registry: {}`, `selfId: null`) → no `SYNC` and no `LINK` line at all.
3. One-Mac install + no health file + a populated memory index (so MEMORY is green) → verdict is exactly `{nominal:false, tone:'first-run', text:"NEW INSTALL · LET'S SET UP"}` and **no** line anywhere in `d.lines` has level `yellow` or `red`. (Literal AC1.)
4. Gil's two-device registry + `GREEN()` health → exactly one `SYNC` and one `LINK` line, same chip/level/target shape as today (update the one existing assertion that legitimately changes: `SYNC`'s target moves from the self check `@macbook-pro-1` to the peer check `@mac-mini-1`, since self's own sync check must never produce a line about itself). (Literal AC2.)
5. Self-exclusion: a red `disk:space@macbook-pro-1` (self) check must never surface in any `LINK` line; only the peer's own checks can.
6. Three Macs, one unreachable: self + two peers, one peer has only a yellow `machine:<dev>` check (no disk/jobs checks) → two `SYNC` + two `LINK` lines, the unreachable one reflects that yellow check without crashing or being silently dropped.
7. Malformed `registry` (`"evil"`, `[]`, `{a: null, b: 42}`) and malformed `selfId` (a number, an object, `undefined` vs explicit `null`) → never throws, degrades to zero or safely-labeled lines.
8. Health snapshot present but `checks: []` on a one-Mac registry → verdict stays `unknown`/`HEALTH UNKNOWN`, **not** first-run. (Ticket's explicit "0 checks" attack.)
9. Gil's two-Mac registry with the health file genuinely missing → verdict stays `unknown`/`HEALTH UNKNOWN`, **not** first-run (guards against misreporting a broken established install as new).
10. `TEST` line is neutral (`{chip:'TEST', level:'lock', text:'TESTS · NOT YET RUN'}`) only under the true first-run condition; stays `yellow`/`UNKNOWN` whenever health exists or peers exist.
11. `PLOT`/handoff: empty handoffs dir → `level: 'lock'`, never `yellow`, unconditionally (not just on first-run).
12. Idempotency: calling `buildBootData(opts)` twice with identical opts returns deep-equal results (no hidden state from the new registry reads).
13. Source-scan: `boot_data.js`'s own source text contains none of `gileskayo`, `mac-mini-1`, `MBP`. (Literal AC3; backed independently by `lib/tests/test_instance.py`'s existing ratchet, once `boot_data.js` is removed from `instance_grandfathered.txt`.)

`dashboard/test/boot_view.test.js` additions:

14. `bannerTone({nominal:false, tone:'first-run'})` → `'first-run'`.
15. `bannerTarget({nominal:false, tone:'first-run'})` → `null`.
16. `subtitleText(verdict)` for `nominal`/`first-run`/`issues`/`unknown`, plus `undefined` → never says `SYSTEMS ONLINE` unless truly nominal (the bug), never throws.

No automated test exists today for `boot_animation.js`/`BootSequence.jsx` (no DOM/WAAPI harness in this repo) — verification for the skipped check-bar and subtitle-in-the-browser stays manual via the required screenshots (AC4), stated here rather than silently skipped.

## Task List

1. `dashboard/electron/main/boot_data.js`: add `homeMemoryDir()`; import `readNetworkRegistry`, `resolveDeviceId`, `machineNames`; replace `syncLine`+`miniLine` with a single `deviceLines(checks, registry, selfId)` producing per-remote-device SYNC/LINK pairs (rename `miniReason`→`deviceReason`); make `handoffLine`'s empty case neutral (`level:'lock'`); add the `freshInstall` (health===null && no peers) signal, threaded into `testLine` and `verdictOf`'s new first-run branch; guard against non-object `registry`.
2. `dashboard/src/lib/boot_view.js`: extend `bannerTone`/`bannerTarget` for `'first-run'`; add `subtitleText(verdict)`.
3. `dashboard/src/components/BootSequence.jsx`: drive the `.boot-sub` text and tone class from `data.verdict` via `bannerTone`/`subtitleText` instead of the hardcoded `SYSTEMS ONLINE`.
4. `dashboard/src/lib/boot_animation.js`: gate the system-check feed/progress-bar block on `data.verdict?.tone !== 'first-run'`, collapsing `CHK_END` to `C0` when skipped so downstream timing stays coherent.
5. `dashboard/src/components/boot.css`: add `.boot-banner.first-run` and per-tone `.boot-sub` color rules.
6. `lib/tests/instance_grandfathered.txt`: remove the `dashboard/electron/main/boot_data.js` line.
7. `dashboard/test/boot_data.test.js`: extend `tree()` with `registry`/`selfId`, update the one changed `SYNC` target assertion, add tests 1–13 above.
8. `dashboard/test/boot_view.test.js`: add tests 14–16 above.
9. Run the full dashboard suite plus `lib/tests/test_instance.py` (both ratchet tests) to confirm the grandfathered-list removal doesn't regress.
10. Capture and pin 900px and 1440px screenshots on the PR for both a one-Mac/fresh-install boot and Gil's normal two-Mac boot (AC4 — visible output changes in both the summary lines and the subtitle/banner).