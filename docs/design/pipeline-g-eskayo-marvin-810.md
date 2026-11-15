## North-star fit

**Reuses:** `window.api.mr.historyDetail` (preload `dashboard/electron/preload/index.js:51` → IPC handler `dashboard/electron/main/index.js:1031-1038`) — the exact "read one PR's real GitHub state, read-only" call `MrReview.jsx`'s `openRow` (`MrReview.jsx:626`) already uses for the Merged/History tab. And `MrDetail.jsx`'s existing `pr.readOnly` branch (`MrDetail.jsx:265-271`, tested in `test/mr_history_render.test.jsx:68-87`) already renders exactly what the ticket asks for — a badge ("merged · read-only" / "closed · read-only"), no Approve/Deny, and the PR's own link is already shown unconditionally above it (`MrDetail.jsx:241-243`). Nothing new needs inventing for the "show its real state, hide the actions, link to the PR" part — it's wiring, not a new feature.

**Root cause, confirmed in code:** `MrReview.jsx:695`, inside `OpenPrs`'s `reload()`:
```js
setSelected((cur) => (cur ? list.find((p) => p.key === cur.key) || cur : cur))
```
`list` only ever holds *open* PRs. Once a PR closes/merges on GitHub, `list.find` returns nothing and the `|| cur` fallback keeps showing the stale local copy forever — with Approve/Deny still live. That's the whole bug; it's a one-line gap in an otherwise-correct "detail follows the list" pattern.

**Simplest sufficient approach:** don't rebuild the "is this PR really gone" check inline in the component. Add one tiny pure module (`src/lib/selected_pr.js`) with three testable functions, and one `useEffect` in `OpenPrs` that fires only when the already-fetched `prs` stops containing `selected` — no new polling, no new timer (so `test/polling_guard.test.js`'s "no new `setInterval`/recurring `setTimeout`" rule, CONTEXT.md:913-915, stays satisfied; this rides the existing 120s/push-triggered `reload()` cadence, north star 1).

**Where it spends tokens/cost:** one extra `gh pr view` (via `historyDetail`) only when a selected PR's key stops appearing in the list — not a timer, not per-render. Matches CONTEXT.md:945-947 ("Approve's preflight uses what the dashboard has... one conditional check").

**Correcting the ticket's own claim:** the Fix text says "The webhook refuses non-open PRs (W5.5)" as settled fact. It isn't yet — W5.5 is issue **#809** ("Approving one PR twice... queues two merges"), currently `needs-info`, and its own Fix line says `mergePrUnqueued` needs a `state === OPEN` check it doesn't have yet (confirmed: no such check exists in `webhook-server/merge.js:847-926`). That's a separate P1 ticket already tracked — not in scope here, and not blocking this one (this fix is a pure read via `historyDetail`, independent of the gate). Noting it rather than silently absorbing #809's scope or silently relying on a guard that isn't there.

**A real correctness trap I'm designing around:** `historyDetail`'s IPC always returns `readOnly: true`, whatever GitHub's actual `state` is. If a PR drops out of the aggregate `prs` list for an unrelated transient reason (one repo's listing briefly failing — the existing `#422` partial-failure pattern) while it is still genuinely `OPEN`, blindly trusting `historyDetail`'s `readOnly:true` would wrongly freeze that PR as "closed" and permanently hide Approve on a PR that's actually fine. So the recheck only accepts the answer when GitHub's own `state` is `CLOSED` or `MERGED`; an `OPEN` or anything else is treated exactly like a failed read — left alone, retried on the next normal list refresh. This also makes "PR reopened after closing" (the ticket's own break-it case) self-healing for free: once reopened, the next `list()` finds it again and the existing `list.find(...) || cur` fallback (`MrReview.jsx:695`, unchanged) overwrites the stale read-only copy with the live one.

**More capable, not more passive:** the owner never again sees a live Approve button on a PR GitHub already closed, and never has to notice and manually reload to find out — the screen reports reality on its own next heartbeat.

No open decisions for the owner — this is fully determined by the existing read-only pattern already shipped for Merged history.

## Tests first

All new, in `dashboard/test/selected_pr.test.js` (pure functions, no DOM — matches this codebase's established test style; there is no jsdom/interactive-mount harness configured, confirmed in `dashboard/vitest.config.*`, so logic goes in testable pure functions and the `useEffect` stays thin, uninstrumented glue):

- `stillInList`: PR present by key → true; absent → false; empty list → false; `null`/`undefined` list → false; `null` PR → false.
- `recheckVanished` — **"PR reopened after closing" (ticket's own attack)**: `historyDetail` answers `state: 'OPEN'` → treated as *no real answer* (returns `null`), so a live PR is never force-marked read-only by a stale/transient list gap.
- `recheckVanished` — real answers: `state: 'CLOSED'` and `state: 'MERGED'` are both accepted and returned as-is.
- `recheckVanished` — **dependency failing**: `historyDetail` rejects (GitHub unreachable/outage) → returns `null`, never throws.
- `recheckVanished` — **malformed input**: resolves with `null`, `undefined`, or an object missing `key` → returns `null`.
- `applyRecheck` — **happy path**: `selected === asked` and `fresh` truthy → returns `fresh`.
- `applyRecheck` — **race / stale state (a person's mistake / reopen-before-read-lands)**: `selected !== asked` (the owner navigated away, or a live copy already replaced it via the normal list refresh while the read was in flight) → returns `selected` unchanged, never clobbering a fresher state with a stale one.
- `applyRecheck` — **failed read**: `fresh` is `null` → returns `selected` unchanged.

`dashboard/test/mr_history_render.test.jsx` (extend existing `MrDetail read-only` describe block):
- New case: `MrDetail` given `backLabel="MR Review"` on a `readOnly: true` PR still renders "Back to MR Review", not "Back to merged history" — proves the label isn't hard-coded to `readOnly` once a second call site can produce a read-only PR.
- Re-run existing cases unchanged (no Approve/Deny, `data-readonly="1"`, no Decisions submit) to confirm the `backLabel` prop addition is non-breaking with no prop passed (defaults to current behavior).

No test mocks GitHub's own refusal rules here since nothing in this change talks to the gate — `historyDetail` is a single already-tested read; its own adversarial coverage (bad JSON, missing PR, etc.) already exists where it's implemented.

## Task List

1. Add `dashboard/src/lib/selected_pr.js` exporting `stillInList(pr, list)`, `recheckVanished(url, historyDetail)` (accepts only `CLOSED`/`MERGED`, else `null`, never throws), and `applyRecheck(selected, asked, fresh)`.
2. Write `dashboard/test/selected_pr.test.js` covering every case above; confirm all fail against a stub/no-op implementation first (red), then pass once (1) is correct (green).
3. In `dashboard/src/components/MrReview.jsx`: import the three functions; add a `useEffect` inside `OpenPrs` (right after the existing `reload()` effect at `MrReview.jsx:718-726`) that, when `selected` is non-null, not already `readOnly`, and no longer present in `prs` (`!stillInList(selected, prs)`), calls `recheckVanished(selected.url, window.api.mr.historyDetail)` and applies the result via `applyRecheck`, guarded by a `cancelled` flag on cleanup.
4. In `MrReview.jsx`, pass `backLabel="MR Review"` on the `<MrDetail>` call inside `OpenPrs`'s `selected` branch (`MrReview.jsx:784-796`), and `backLabel="merged history"` on the top-level `historyPr` branch's `<MrDetail>` call (`MrReview.jsx:621-623`).
5. In `dashboard/src/components/MrDetail.jsx`: add `backLabel = null` to the prop list (`MrDetail.jsx:190`) and use it at the back-button line (`MrDetail.jsx:226`): `← Back to {backLabel ?? (pr.readOnly ? 'merged history' : 'MR Review')}` (keeps existing behavior when no `backLabel` is passed, so no other caller breaks).
6. Extend `dashboard/test/mr_history_render.test.jsx`'s `MrDetail read-only` block with the `backLabel` case described above.
7. Run the full dashboard suite (`npm test` in `dashboard/`), specifically confirming `test/polling_guard.test.js` still passes (no new timer introduced) and `test/mr_history_render.test.jsx` / `test/pr_state.test.js` show no regressions.
8. Manually verify in the running app (per repo convention): open a pipeline PR's detail from the **Open** tab, close it on github.com, wait for/trigger a refresh, confirm Approve/Deny disappear and the read-only badge + working PR link appear; then reopen it on GitHub and confirm the next refresh restores the live Approve/Deny card.
9. Take and pin screenshots at 900 px and 1440 px of the detail view in its new read-only state (acceptance criterion), via `marvin-show`.
10. Open the PR against #810, body states "Closes G-Eskayo/marvin#810", includes a short north-star-fit note and the W5.5/#809 clarification above (no Decisions section needed).