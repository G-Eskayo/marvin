## North-star fit

**Reuses:** `webhook-server/failure.js`'s `refusal()`/`classifyFailure()`/`MergeFailure` (existing structured-failure plumbing, ADR 0074 item 3 — which already *instructed* `failure.js` to export one `REMEDIATION_BY_CODE` "built from RULES + inline refusals" for `stage_strip.js` to consume; that instruction was never carried out, which is the actual root cause of this bug) and the existing collapsible-disclosure markup pattern already used for exactly this purpose in `SupportTab.jsx:217` ("Technical details (sent automatically, no passwords)") and `ProposalsSection.jsx:175` ("▸ Technical details"). No new UI primitive, no new error-plumbing mechanism — just finishing the consolidation ADR 0074 already called for, and reusing the disclosure widget Gil already approved twice elsewhere.

**Simplest sufficient approach:** The temptation is to make `{code, message, remediation}` cross the Electron IPC boundary as a real structured object. It can't cleanly: `approve_flow.js`'s `refused()` (line 87-89) is the one branch in that function that still `throw`s instead of returning a plain result object like every sibling branch (`waitingMemory`, `queued`, `interrupted` all return `{ ...fields, cancelled: false }`); a thrown `Error`'s custom `.payload` property does not reliably survive `ipcMain.handle`/`ipcRenderer.invoke` serialization, and no renderer code today reads `err.payload` — only `err.message` (confirmed: `cleanIpcError` only touches `.message`; `prState.js` does regex matching against the flattened string). Rearchitecting that boundary to carry a real object would ripple through `approve_flow.js`, every approve-outcome branch in `MrReview.jsx`, and a dozen tests that assert exact thrown-error strings (`approve_stream.test.js`, `merge_failover.test.js`). Instead: keep the single string channel, but stop putting the code at the front of it. Append it as a machine-markable suffix using the *same* `<details><summary>...</summary>...</details>` convention `decisions.js:249` already embeds in PR bodies and `SupportTab.jsx:77` already regex-extracts out of a string for separate rendering. One small extractor function, reused by both `prState.js` (to strip it before display) and a new JSX `<details>` block (to show it on request). This is the "elegant sufficiency" cut: same outcome the issue asks for, zero IPC-boundary risk.

**Where it spends tokens, not saves them:** this ticket is pure plumbing/copy work across 4-5 files plus tests; it doesn't compound into other tickets beyond "the next new refusal code gets one table entry instead of three." That's a modest but real compounding win (north star: compounding leverage) — worth doing once, not iterating on.

**Leaves the user more capable:** yes — Gil currently has to mentally decode `RATE_LIMITED at merging: …` to know whether to act; after this he reads one plain sentence and only digs into "Technical details" when filing a bug himself. Argues *for* this work under north star 3 (raises the human experience without doing anything "for" him he'd rather do himself — decoding internal codes was never a skill worth preserving).

**No north star argues against this.**

---

## What's actually broken (confirmed by reading the code, not just the ticket text)

Three *wording* tables exist, as the ticket says, and genuinely drift:

| Code | `failure.js` RULES/`REMEDIATION_BY_CODE` | `stage_strip.js` `REMEDIATION_BY_CODE` (hand-copied) | `mr_history.js` `REASONS` |
|---|---|---|---|
| `IMAGES_STALE`, `IMAGES_UNPINNED`, `UI_EVIDENCE_UNCHECKED`, `DECISIONS_UNCHECKED`, `DECISIONS_UNSTRUCTURED`, `ENV_MISSING`, `ALREADY_MERGING` | missing from the static table (payload carries dynamic remediation instead) | **missing entirely** | **missing entirely — falls back to the raw code string** (`mr_history.js:23`, `plainReason = (code) => REASONS[code] || code`) |

That `REASONS[code] || code` fallback is a live violation of "no code string visible without opening Technical details" today, for any code it doesn't know — confirmed by the existing test `dashboard/test/mr_history.test.js:88`: `['WHATEVER', 'WHATEVER']`.

The deeper bug — "`-- needs you` added even when the fix is `approve again in a moment`" — is concrete and reproducible, not vague:
- `ci_status.js:88-90`: `refusal('CI_PENDING', 'request', ..., 'Wait for them to finish, then approve again. The PR was not sent back.')` passes **no 5th `action` argument**, so `refusal()`'s default (`action = 'escalate'`, `failure.js:185`) applies. `describeApproveFailure` (`mr_review.js:446-448`) turns any `action === 'escalate'` into `-- needs you`. So a pure "just wait, nothing to do" refusal currently renders as "CI_PENDING at request: GitHub's checks are still running: … **-- needs you**. Wait for them to finish, then approve again." That sentence is self-contradicting today.
- `GATE_INFRA` is worse: its own sub-causes (`failure.js:120-128`, `INFRA_CAUSES`) span both "self-heals, no person needed" (`database is locked` → "Approve again once the other build has finished"; `cannot allocate memory`/`too many open files` → "once the machine is less busy") and "a person must act" (`no space left on device` → "Free up space…"; `has no test command` → "Add a test script…"). One static `needsYou` per code cannot be right for `GATE_INFRA`; it has to come from which `INFRA_CAUSES` rule actually fired, i.e. from the *instance*, not just the code string. "Pick 'needs you' from the code" (the ticket's fix) is right for every other code; `GATE_INFRA` needs it picked from the code **and** the already-computed `infraCause()` result.

---

## Design

**One canonical table, in `webhook-server/failure.js`** (it has zero Node-only imports — confirmed, no `fs`/`child_process` at the top — so it's already safe to import from both `dashboard/src/lib/*` (bundled for the renderer/future Mobile) and `dashboard/electron/main/*`, exactly like `mr_review.js` already imports `ci_status.js`/`ui_evidence.js`/`decisions.js` from `webhook-server/`):

```js
// failure.js
export const FAILURE_TABLE = {
  CODE: { reason: '<short phrase, history row>', remediation: '<static default, used when a call site supplies none>', needsYou: true|false },
  ...
}
export function plainReason(code) {        // replaces mr_history.js's REASONS + fallback-to-code
  return FAILURE_TABLE[code]?.reason ?? 'unclassified failure'   // never the bare code
}
export const REMEDIATION_BY_CODE = Object.fromEntries(Object.entries(FAILURE_TABLE).map(([c, v]) => [c, v.remediation]))
```

- `RULES` (error-pattern matches) keep `code`/`action`/`retryable`/`test`; `remediation` is dropped from each rule entry and looked up from `FAILURE_TABLE` instead, removing the one duplication that already exists *inside* `failure.js` itself (RULES' remediation strings and `REMEDIATION_BY_CODE`'s are currently the same text typed twice).
- `classifyFailure()` and `refusal()` both add `needsYou` to the returned payload: `needsYou: overrideIfGiven ?? FAILURE_TABLE[code]?.needsYou ?? true` (fail closed: an unmapped code defaults to "needs you" — same "fails closed" posture `mr_review.js:256` already uses for `ownBlocker`'s unknown-files case).
- `refusal(code, stage, message, remediation, action = 'escalate', needsYou)` gets an optional 6th param. Every call site stays unchanged **except** the ones that need a true per-instance value:
  - `ci_status.js:88-90` (`CI_PENDING`): add `needsYou: false` explicitly (or just fix the table default — but since the remediation is dynamic text per call, pass it explicitly for clarity).
  - `merge.js:973` (`GATE_INFRA`) and wherever `infraCause()`'s result feeds the refusal: add a `needsYou` field to each `INFRA_CAUSES` entry (`disk full` → true, `no test command` → true, `database locked` → false, `lost network` → false, `operation not permitted` → true, `too many open files`/`cannot allocate memory` → false) and to the disk-check branch (true), and thread that value into the `refusal('GATE_INFRA', ...)` call instead of letting it default. The no-sentence-yet fallback (unrecognized `GATE_INFRA` signature) stays `needsYou: true` (fail closed, matches `UNKNOWN`'s posture).
- `FAILURE_TABLE` gets one entry per code found in the codebase today (full list compiled by grep, 34 codes: `GH_AUTH_INVALID, NOT_MERGEABLE, PR_DRAFT, BRANCH_PROTECTION, BASE_MOVED, RATE_LIMITED, GITHUB_OUTAGE, TRANSIENT_NETWORK, TOOL_MISSING, PR_NOT_FOUND, INVALID_REQUEST, UNKNOWN, REBASE_CONFLICT, GATE_INFRA, GATE_TESTS_FAILED, UI_EVIDENCE_UNCHECKED, NO_UI_EVIDENCE, IMAGES_UNPINNED, IMAGES_STALE, DECISIONS_UNCHECKED, DECISIONS_PENDING, DECISIONS_UNSTRUCTURED, CI_FAILED, CI_PENDING, NO_MERGE_PROFILE, ENV_MISSING, WRONG_BASE, SENT_BACK, MEMORY_PRESSURE, MAIN_RED, MERGE_REFUSED, OUT_OF_ORDER, VERSION_BUMP_FAILED, ALREADY_MERGING`), each with a plain `reason` and the `remediation` text that already exists somewhere today (`stage_strip.js`'s copy where present, written fresh for the 7 codes that have none anywhere yet: `UI_EVIDENCE_UNCHECKED, NO_UI_EVIDENCE, IMAGES_UNPINNED, IMAGES_STALE, DECISIONS_UNCHECKED, DECISIONS_UNSTRUCTURED, ENV_MISSING, ALREADY_MERGING`).

**`stage_strip.js`:** delete its hand-copied `REMEDIATION_BY_CODE` object entirely; `import { REMEDIATION_BY_CODE, remediationFor } from '../../webhook-server/failure.js'` (or keep `remediationFor` local, backed by the import). Its hover-on-a-stage-pill UI stays exactly as-is — ADR 0074 ("Failed stages show their refusal code + human-readable remediation text on hover") and `CONTEXT.md:967` both explicitly *decided* the stage strip shows the code on hover. That's a different, already-approved surface from the Approve-failure text this ticket is about; not touched.

**`mr_history.js`:** delete the local `REASONS` object and `plainReason`; `import { plainReason } from '../../webhook-server/failure.js'`.

**`mr_review.js`'s `describeApproveFailure`:** rewritten to
1. build the plain sentence without the leading `CODE at STAGE:` — `${body.message}${needsYouOrRetrySuffix}. ${body.remediation ?? ''}`, where the suffix is driven by `body.needsYou` (not `body.action === 'escalate'`) for the "-- needs you" case, and still by `body.action === 'retry'` for the "already retried N times" phrasing (that part isn't wrong today, only the "needs you" trigger is);
2. append `\n\n<details><summary>Technical details</summary>${body.code} at ${body.stage}</details>` — same markup `decisions.js:249` already embeds in text for later extraction.

**`prState.js`:** add one small extractor (`splitTechnicalDetails(text)` → `{ plain, technical }`) using the same shape of regex `SupportTab.jsx:77` already uses for an embedded `<details>` block. Use it to fix the three places that currently inspect the *raw* `errorMessage` string directly:
- line 174 (`/^GITHUB_OUTAGE\b/`) and line 182 (`/^IMAGES_STALE\b/`) — match against the extracted *code* (from the technical block) instead of the leading text of the whole string, since the code no longer leads;
- line 186-188's generic `error` branch — set `detail: plain` (not the raw `errorMessage`) and a new `technical` field on the returned view, for the UI to render collapsed;
- line 182-184's `images-stale` branch — same fix (`detail: plain`, not raw `errorMessage`).

**`MrReview.jsx`:** render `view.technical` (when present) as `<details className="..."><summary>Technical details</summary>{view.technical}</details>`, next to the existing `{view.detail && <p>...}` — visually matching `ProposalsSection.jsx`'s existing toggle styling.

No owner decisions are needed: every choice above (which `needsYou` value per code, including the two genuinely nuanced cases, `CI_PENDING` and `GATE_INFRA`'s sub-causes) is derivable directly from each remediation sentence's own existing wording, not a product preference. I'm not opening a Decisions section.

---

## Tests to write first

From "How we'll try to break it" (one explicit item) plus the misuse categories the section didn't spell out:

1. **(ticket's own case) Unknown code → generic plain line, never the raw code.** `plainReason('WHATEVER')` (and `classifyFailure`/`refusal` payload text) must never equal `'WHATEVER'`; rewrite `mr_history.test.js:86-91`'s `['WHATEVER', 'WHATEVER']` case to assert a fixed generic phrase instead.
2. **Completeness/consistency (acceptance criterion #1 — "a test fails if any refusal code has no plain text"):** a test that enumerates the full 34-code list (hardcoded, matching every `code:`/`refusal('CODE'` literal found by grep) and asserts `FAILURE_TABLE[code]` exists with non-empty `reason`, non-empty `remediation`, and boolean `needsYou` for every one — this is the test that fails the moment a new refusal code is added without a table entry.
3. **No bare code string without opening details (acceptance criterion #2):** for every code in that same list, `describeApproveFailure(500, { code, stage: 'x', message: 'y', remediation: 'z', action: 'escalate' })`'s result, with the `<details>…</details>` block stripped out, must not contain the code substring.
4. **Regression: `CI_PENDING` must not say "needs you."** `describeApproveFailure(500, { code: 'CI_PENDING', ... })` (or the live `assertChecksGreen` → `refused()` path) must not contain `needs you`.
5. **Regression: `GATE_INFRA` sub-causes disagree on `needsYou`.** Disk-full and no-test-command `GATE_INFRA` refusals say "needs you"; database-locked, lost-network, too-many-open-files/out-of-memory `GATE_INFRA` refusals do not.
6. **Malformed/empty input:** `describeApproveFailure(status, null)`, `describeApproveFailure(status, {})`, `describeApproveFailure(status, { code: 'X' })` with `message`/`remediation`/`stage` missing or `''` — never throws, falls back sensibly (keep the existing `Webhook call failed: ${status}` path when `body.code` is absent).
7. **Extraction robustness on adversarial text:** a `message` or `remediation` that itself contains the literal substrings `GATE_INFRA`, `<details>`, or `Technical details` (plausible — stderr tails get embedded in some messages today, e.g. `GATE_INFRA: ...` prefixed detail text) must not confuse `splitTechnicalDetails` into mis-extracting or duplicating content; it must still isolate exactly the appended block.
8. **Huge input:** a `message`/`remediation` at the existing truncation limits (`EVIDENCE_MAX`/`CAUSE_MAX`, already 600/200 chars) still produces a valid, parseable plain+technical split after the reformat — no new unbounded growth introduced by wrapping in `<details>`.
9. **Every dependency failing:** the three consuming files (`stage_strip.js`, `mr_history.js`, `mr_review.js`) each import `FAILURE_TABLE`/`plainReason`/`REMEDIATION_BY_CODE` from `failure.js` — a code added only in `failure.js` must show up correctly through all three without touching the consumers (the actual regression this ticket exists to prevent from recurring).
10. **Person's mistake / partial table entry:** a `FAILURE_TABLE` entry missing one of `reason`/`remediation`/`needsYou` fails test #2 above (schema-shape check), not just existence.
11. **Component-level stale state:** `MrReview.jsx`'s new `<details>` toggle open/closed state doesn't leak across different PR cards on re-render (render two cards with different `technical` content, confirm independent toggle state) — existing `render_smoke.test.jsx` pattern extended.

---

## Task List

1. In `webhook-server/failure.js`: add `FAILURE_TABLE` (34 codes: reason, remediation, needsYou), refactor `RULES` to drop inline remediation duplication and source it from the table, export `plainReason`, add `needsYou` to `classifyFailure()`'s and `refusal()`'s returned payload (with a 6th optional override param on `refusal()`).
2. Fix the two concrete misclassified call sites: `ci_status.js:88-90` (`CI_PENDING` → `needsYou: false`), and `merge.js`'s `GATE_INFRA` refusal plus `failure.js`'s `INFRA_CAUSES` entries (add per-cause `needsYou`, thread into the `refusal()` call instead of the default).
3. In `dashboard/src/lib/stage_strip.js`: delete the hand-copied `REMEDIATION_BY_CODE`; import it (and `remediationFor`) from `webhook-server/failure.js`. No change to `StageStrip.jsx`'s hover UI (ADR 0074 / CONTEXT.md:967 already cover that surface).
4. In `dashboard/electron/main/mr_history.js`: delete the local `REASONS` object and `plainReason`; import `plainReason` from `webhook-server/failure.js`.
5. In `dashboard/electron/main/mr_review.js`: rewrite `describeApproveFailure` to build the plain sentence from `message`/`remediation`/`needsYou` (not `code`/`stage`/`action`-for-needs-you), and append the `<details><summary>Technical details</summary>CODE at STAGE</details>` suffix.
6. In `dashboard/src/lib/prState.js`: add `splitTechnicalDetails()`; fix the `GITHUB_OUTAGE`/`IMAGES_STALE`/generic-`error` branches to match against the extracted code and show only the stripped `plain` text as `detail`, exposing a new `technical` field on the view.
7. In `dashboard/src/components/MrReview.jsx`: render `view.technical` behind a `<details><summary>Technical details</summary>...</details>`, styled like `ProposalsSection.jsx`'s existing toggle.
8. Write/port the tests listed above into `failure.test.js`, `stage_strip.test.js`, `mr_history.test.js`, `pr_state.test.js`, `approve_stream.test.js`, `merge_failover.test.js` — updating the now-stale literal-string expectations in the latter two (`approve_stream.test.js:48`, `merge_failover.test.js:542`) to the new no-leading-code format, and the `pr_state.test.js:39-40` `IMAGES_STALE` fixture to the new embedded-suffix shape.
9. Take 900px and 1440px screenshots of an Approve-failure card (generic error state) and a merged-history row showing a previously-unknown-style code, before/after, per acceptance criterion #3; pin on the PR via `marvin-show`.