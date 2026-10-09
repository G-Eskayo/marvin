No prior attempt logged in CONTEXT.md, and the issue has zero comments — no earlier denial feedback to account for. I now have everything needed to write the plan.

## North-star fit

**Reuses before adding anything new:** the entire local half of this feature already exists and is untouched — `lib/session_work.py`'s `overlaps()`/`pre_edit()`/state file/flock locking, and `lib/machine_profile.py`'s `remote_devices()` (already resolves the other Mac's Tailscale hostname from `~/.claude/marvin-network.json`, already excludes self by hardware UUID). On the server side, `dashboard/webhook-server/index.js` already has the exact shape needed: its `GET /auto-merge-shadow` and `GET /rebase-status` routes already read a local `~/.claude/logs/*.json` file defensively and serve it, precisely for "the other Mac can't see this Mac's local files" (`rebase_status.js`'s own comment says this explicitly). `GET /sessions` is a straight copy of that shape pointed at `~/.claude/logs/sessions-active.json`, the file `session_work.py` already writes. `mr_notification.py` already shows the pattern for a short-timeout `urllib.request` GET against this same webhook server (`timeout=3`, wrapped so failure never breaks the caller) — I'll use the same stdlib-only approach, just with a much shorter timeout per the acceptance criterion.

**Simplest sufficient approach:** no new daemon, no new sync mechanism, no new auth layer. The ticket offers two options (HTTP endpoint vs. synced file); the endpoint wins because the webhook server already runs on both Macs via launchd regardless of whether the dashboard app is open (confirmed in `mr_notification.py`'s own comment), so there's no new process to keep alive, and it avoids the sync system's known collision issues with generated/state JSON (`docs/life-of-a-ticket.md` red list #5). Not adding a Tailscale-identity gate like `mobile-backend/device_gate.js` does for the mobile endpoint: that endpoint is reachable by any device on the tailnet and needs to vet an external peer; `/sessions` sits on the same server as `/approve`, `/auto-merge-shadow`, `/portfolio/*`, none of which gate by caller identity today — adding one gate to just this route would be a new, inconsistent security model for a two-Mac, single-owner trust boundary the rest of the file already accepts.

**Token cost:** spends a little — one new ~10-line Node route + a small pure module, one new Python function plus a few lines of glue in `session_work.py`, each covered by a handful of unit tests. No LLM calls anywhere in the runtime path (pure stdlib HTTP + JSON), so no inference-token cost; this is pure engineering-token spend, paid once for a permanently-cheap mechanism (a `urllib` GET and a dict scan).

**More capable or more passive:** more capable — it closes red-list #9 directly: a person building on the laptop no longer duplicates work already running on the mini (or vice versa), without being asked to check manually. It doesn't take over judgment: Gil still gets asked and decides whether the overlap matters, exactly as the local-Mac version already works.

The ticket's own "Build" text says "Each Mac publishes its live sessions... to the other" (symmetric) — correct and consistent with both Macs already running the webhook server locally; no correction needed there.

## Files to touch

- `dashboard/webhook-server/index.js` — add `GET /sessions` route (read-only).
- `dashboard/webhook-server/sessions_endpoint.js` — **new**, pure `readSessionsSnapshot(file)`, mirrors `rebase_status.js`'s `readRebaseStatus()`.
- `lib/session_work.py` — add `fetch_remote_sessions()`, `remote_overlaps()`; extend `pre_edit()` to merge in remote overlaps and name the Mac; `handle("pre", ...)` glue builds the real remote URLs via `machine_profile.remote_devices()`.
- `lib/tests/test_session_work.py` — new tests (below).
- `dashboard/test/sessions_endpoint.test.js` — **new** test file.

## Tests first

JS (`sessions_endpoint.js`, mirroring `readRebaseStatus`'s own untested-but-trivial precedent — except TDD requires tests here regardless):
1. Missing file → `{}`.
2. Valid JSON with a `sessions` object → returned as-is.
3. Corrupt/malformed JSON (`"{not json"`) → `{}`, not a thrown error.
4. File read throws a non-ENOENT error (e.g. permission denied, mocked) → `{}`, not a thrown error — "wrong permissions" / "dependency failing" case.

Python (`session_work.py`), one per generic misuse category since the ticket has no "How we'll try to break it"/"Attacks" section of its own:

1. **Happy path / acceptance criterion 1:** a remote session (from `fetch`) that edited the same file within the live window produces a `pre_edit` ask naming the Mac and the remote request — exactly like the existing local-overlap test, but sourced from `remote_overlaps`.
2. **Unreachable dependency (acceptance criterion 2):** `fetch` raises/returns `None` → `pre_edit` returns `None` (edit goes through), and the attempted timeout passed to the network call is ≤ the budget (assert the `timeout=` kwarg is small, not the literal "300ms" since that's a human description, but bounded e.g. `<= 0.5`).
3. **Cache window / repeats:** calling `pre_edit`/`remote_overlaps` twice within 60s of each other → `fetch` is called exactly once (second call is a cache hit) — "once per minute" from acceptance criterion 2, and a repeats/concurrency case.
4. **Cache expiry:** call again after the cache window has elapsed → `fetch` is called a second time.
5. **Stale remote session:** a remote session whose `last` timestamp is older than `LIVE_S` (45 min) → not reported as an overlap, even though it's in the fetched payload — mirrors the existing local staleness test, applied to remote data.
6. **Malformed remote response:** `fetch` returns garbage shapes — a list instead of a dict, a `sessions` value that isn't a dict, an entry missing `files`/`last`/`request` keys, absurdly long `request` string — in each case `remote_overlaps`/`pre_edit` must not raise and must not corrupt the ask message (treat as no-overlap or defaulted fields, never `KeyError`/`TypeError`).
7. **No other Mac registered (person's mistake / cold start):** `remote_devices()`-equivalent returns empty / `remote_urls=()` → behavior is identical to today (local-only), no crash, no network call attempted.
8. **Empty/falsy inputs:** empty file key, empty request string, empty sessions dict from remote → no overlap, no exception.
9. **Asked-once-per-pair across Macs:** the same remote overlap is not re-asked on a second `pre_edit` call for the same (local session, remote session, file) triple — extends the existing local "asked once" test to the remote path, and checks a remote session id that happens to collide in spelling with the local dedup key still gets a distinct cache key (prefixed by the Mac label) so it can't collide with a same-named local session's dedup entry.
10. **Two remote Macs overlapping the same file (repeats):** `pre_edit` reports both without one suppressing the other, and both lines name their own Mac.
11. **Concurrency / lock reuse:** two back-to-back `handle("pre", ...)` calls through the real `_Locked` file-lock path (like the existing `test_hook_handlers_round_trip_through_the_state_file` test) still work with the remote glue wired in — i.e. adding the remote fetch doesn't break the existing flock-based single-writer state file.
12. **Broken state file still never blocks an edit:** extend the existing `test_a_broken_state_file_never_blocks_an_edit` scenario to confirm it still holds once the remote-fetch code path is wired into `handle`.

Verify check: re-run `lib/tests/test_session_work.py` and `dashboard/test/sessions_endpoint.test.js` against the current (pre-change) code first to confirm every new test fails for the right reason (missing function/route), then implement, confirm tests 1–12 and the JS tests pass, and confirm the pre-existing tests in both files still pass unchanged.