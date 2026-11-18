## North-star fit

- **Reuses before adding anything new:**
  - `lib/chat_helpers.py:_update()` (the existing per-helper lock + read-modify-write + atomic-replace machinery, already used by every hook event) for the new `dismiss()` — no new file format, no new store.
  - `dashboard/webhook-server/chat_helpers.js:sortHelpers()`/`RANK` for ordering before the cap — no new sort.
  - `dashboard/electron/main/proposals.js`'s `PY`/`CLI`/`execFile`/"parse last JSON line of stdout" pattern, for the new `dismissLocalHelper()` call into the Python CLI.
  - `dashboard/webhook-server/merge_stage_relay.js:allowedPeerAddress()` and the `/merge-stage` POST shape (peer-only, body-capped, JSON-validated) for the new cross-Mac `/helpers/dismiss` route.
  - `AgentsPanel.jsx:AgentCard` (already shared between Health's agents and Activity's chat helpers) — extended with one optional prop rather than forked.
- **Why simplest sufficient:** dismiss state lives as one field (`dismissed_at`) on the helper's own already-existing JSON file, so "persists across restarts" and "stays in the helper's history" fall out for free — no new store, no new sync path. The 24h-expiry and the interim cap-of-10 (per the ticket's own text, deferred to #625's real design) are pure filter/slice functions on data that's already computed.
- **Tokens:** this is a pure code task (no model calls in the feature itself); spend here is implementation + adversarial tests, not inference.
- **Phone-OS direction:** N/A directly, but keeps the dashboard honest ("never show a dead thing as if it's still happening" — W4's rule) which the OS-shaped dashboard depends on.
- **More capable or more passive:** more capable — Gil stops having to mentally filter out stale crash cards or wait for 30 unrelated helpers to push one out; nothing is done "for" him that he'd rather do himself.
- **Machine:** no machine-specific work; runs in the existing per-Mac dashboard/webhook-server processes, unchanged.
- **Where it's scoped tighter than the full plan doc:** the plan doc (`dashboard-ux-potholes-2026-10-29.md`, W6) also wants "last 3 + N earlier ▸" bucketing — that's explicitly deferred to #625 (open, unbuilt, waiting on a mock-up). This ticket's own Fix text already simplifies to a flat cap of 10, so I'm building exactly that, not the fuller redesign.

No Decisions needed: every open question (does dismiss need to work for a crashed helper that ran on the *other* Mac; does the 24h rule cover `failed` too) is resolved by reading the existing architecture and the ticket's own wording, not a matter of taste — see Task List notes.

## Tests to write first

**`lib/tests/test_chat_helpers.py`** (new `dismiss()` + CLI):
1. `dismiss(aid)` sets `dismissed_at` on an existing helper doc, returns `True`, and leaves `runs`/`helper` untouched (history preserved).
2. `dismiss()` on an id with no file returns `False` and creates nothing (bad input — unknown id).
3. Dismissing twice is idempotent (repeats) — no error, `dismissed_at` just updates.
4. A `dismiss()` racing a real hook `stop` event on the same id, from two threads, never corrupts the file (concurrency; reuses the existing lock, same style as `test_two_helpers_at_once_each_keep_their_own_row`).
5. `dismiss()` against a corrupt (`{half`) file returns `False` and does not "fix" it (stale/malformed state — matches `_update`'s existing `create=False` contract).
6. CLI `chat_helpers.py dismiss <id>` with a path-traversal-style, empty, or 500-char id exits non-zero and writes nothing (hostile/malformed input, mirrors `test_garbage_and_hostile_payloads_write_nothing_and_never_raise`).
7. CLI `dismiss` with no `~/.claude/logs/jobs` at all exits cleanly with `{"ok": false}` (fresh install / missing dependency).
8. CLI `dismiss` when the jobs dir isn't writable (permissions) reports `{"ok": false}`, never raises.

**`dashboard/test/chat_helpers.test.jsx`** (filtering, cap, merge, security):
9. A crashed helper whose last sign of life is <24h ago still appears in `listHelpers()`.
10. A crashed helper whose last sign of life is >24h ago is excluded from `listHelpers()` (the acceptance criterion, core case).
11. Boundary test at exactly 24h (pins which side is "expired").
12. A `dismissed_at`-flagged helper is excluded regardless of status/age (defensive — matches ticket's generic "Dismiss button").
13. A `failed` (not `crashed`) helper, however old, is **not** auto-expired — pins the scope precisely to "crashed", per the ticket's own title/Fix text.
14. "Crashes, restarts, crashes again": two distinct helper ids (a restart is a new agent id/new file in this architecture) — dismissing/expiring the first never affects the second's visibility.
15. Home cap: with 3 running + 20 done helpers, the merged `createHelpersReader()` result keeps the 3 running plus the 10 most recent after them capped at 10 total, never dropping a running one.
16. Clock skew: a peer's crashed helper is filtered using *that machine's own* `now` before it crosses the wire (filtering lives in `listHelpers()`, which runs on the origin machine), so a skewed local clock on the reading Mac can't wrongly show or hide it.
17. `GET /helpers` from a non-loopback, non-Tailscale address can't reach `/helpers/dismiss` (403, mirrors `allowedPeerAddress` test for `/merge-stage`) — adversarial/outward-facing per north stars.
18. `/helpers/dismiss` with an oversized or garbage JSON body, or a malformed id, is rejected (400) without touching disk.
19. `dismissHelper()` for a `machine` that isn't in the peer registry fails cleanly (no hang, no crash) — dependency/peer unreachable.
20. After a successful cross-machine dismiss, the reader's cache entry for that peer is invalidated so the next read doesn't serve a stale pre-dismiss list for up to 10s.

**Component tests** (`dashboard/test/chat_helpers.test.jsx`, `renderToStaticMarkup` — this repo has no DOM-interaction test harness, so only markup is asserted, consistent with existing tests):
21. `AgentCard`/`ChatHelpersView` renders a Dismiss control only when `agent.status === 'crashed'` **and** an `onDismiss` prop is supplied.
22. Rendered through `AgentsPanel.jsx` (Health's agents, no `onDismiss` passed) a crashed launchd agent gets **no** Dismiss control — confirms the shared `AgentCard` change doesn't leak into Health.

## Task List

1. `lib/chat_helpers.py`: add `dismiss(aid, *, jobs_dir=None, now=None) -> bool` built on `_update()`; add a `dismiss` branch in `main()` ahead of the hook/alarm path, printing `{"ok": bool}` and exiting non-zero on failure (the hook path's "always exit 0, swallow everything" contract is untouched).
2. `lib/tests/test_chat_helpers.py`: tests 1–8 above; generalize the existing `_run_cli` helper to take the subcommand as an argument instead of hardcoding `"hook"`.
3. `dashboard/webhook-server/chat_helpers.js`: export `CRASH_EXPIRY_MS` (24h), `HOME_CAP` (10, interim per #625), `HELPER_ID` regex; add `dismissedAt` to `describeHelper()`'s output; filter dismissed and >24h-crashed helpers out of `listHelpers()`; add `dismissLocalHelper(aid, { run = execFile })` using the `PY`/`CLI`/execFile pattern from `proposals.js`.
4. `dashboard/webhook-server/index.js`: add `POST /helpers/dismiss`, guarded by `allowedPeerAddress`, body-capped and id-validated via `HELPER_ID`, calling `dismissLocalHelper`.
5. `dashboard/electron/main/chat_helpers.js`: apply `HOME_CAP` after merging local+remote in `createHelpersReader`'s returned function; attach a `.forget(peerId)` cache-buster; add `postDismissTo(host, id)`; add `createHelperDismisser({ dismissLocal, postRemote, resolveMe = resolveDeviceId, peers = peerHosts })` resolving local-vs-peer by comparing the card's `machine` to this device's own id.
6. `dashboard/electron/main/index.js`: wire `ipcMain.handle('activity:dismissHelper', (_e, { id, machine }) => dismiss(id, machine))`, returning the refreshed helper list so the renderer updates immediately.
7. `dashboard/electron/preload/index.js`: expose `activity.dismissHelper(id, machine)`.
8. `dashboard/src/components/AgentsPanel.jsx`: add optional `onDismiss` prop to `AgentCard`; render a Dismiss button only when `onDismiss` is set and `agent.status === 'crashed'`.
9. `dashboard/src/components/ChatHelpers.jsx`: pass `onDismiss={(id, machine) => window.api.activity.dismissHelper(id, machine).then(setData).catch(() => {})}` into `ChatHelpersView` → `AgentCard`; leave `AgentsPanel.jsx`'s own usage unchanged (no `onDismiss`).
10. Tests 9–22 above, added to `dashboard/test/chat_helpers.test.jsx`.
11. New evidence script (modelled on `dashboard/scripts/chat_helpers_evidence.mjs`) at 900 px and 1440 px viewports, with fixtures showing: a recent crashed card with its Dismiss button, an old (>24h) crashed card absent, and the cap in effect; run it and pin both screenshots on the PR (acceptance criterion 3).
12. `CONTEXT.md`: append a short addendum to the existing "Chat helpers in Activity (2026-10-22, #612)" section documenting the `dismissed_at` field, the 24h crash-expiry rule, and the interim home cap of 10 (superseded when #625 lands).