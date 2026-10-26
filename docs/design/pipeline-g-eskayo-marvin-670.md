## North-star fit

**Reuses, before adding anything new:**
- `dashboard/mobile-backend/chat_api.js` (`createChatApiRouter`) — the router-factory + ndjson-stream + thread-store-append pattern the new `/voice` route copies almost verbatim.
- `dashboard/mobile-backend/session_runner.js` (`runSession`) — the deep brain *is* this, unchanged; I only pass the `permissionHookPath` argument it already accepts but no caller currently supplies.
- `dashboard/mobile-backend/permission_hook.js` + `pending_actions.js` + `permission_api.js` — the plan-and-confirm / Face-ID gate (ADR 0005/0043) already exists and is already tested; wiring it in is the entire side-effect-safety requirement, not new logic.
- `dashboard/mobile-backend/thread_store.js` — `source: 'voice'` is already a valid value (`validSources`), and `findByClientId` (currently only used by `offline_batch_api.js`) is the existing idempotent-retry primitive, reused for voice's repeat-request case.
- `dashboard/mobile-backend/rotation_policy.js`, `post_json.js` pattern (raw `http`/`https`, no new deps) for the Ollama call.
- `lib/model_registry.py` — confirms the "warm local 3b" the ADR refers to is `qwen2.5:3b` (Ollama, already registered, `local-extract-small`), not something to invent.
- `dashboard/mobile-backend/index.js`'s router-chaining style (`handled = await xApiRouter(req,res); if (handled) return`) for wiring the new router in.
- `docs/agents/decisions-format.md` for the one open question below.

Nothing new is added for device-identity/auth (the existing Tailscale allowlist in `index.js` already gates every request) or for endpoint/ability modeling (CONTEXT.md's "Endpoints and the brief" section explicitly leaves *how* endpoints register as still open — so this ticket treats `device`/`abilities` as caller-declared input, not a new registry).

**Simplest sufficient approach:** six small, independently-testable pure-ish modules (sanitizer, sentence-splitter, brain-chooser, fast-brain HTTP client, latency logger) plus one router that composes them the same way every other `*_api.js` router composes `runSession`/`threadStore`. No new npm dependency, no new auth mechanism, no new persistence format.

**Tokens:** spends nothing extra per turn beyond one local Ollama call (free, on-box) for the fast path, and reuses the existing `claude -p` session for the deep path — same cost as Chat already incurs. Saves tokens/latency whenever the fast brain alone answers (no Claude session spun up at all).

**Phone-OS direction:** this is the one spoken doorway all three future surfaces (Siri, Mac loop, iPhone Voice) share — directly OS-shaped (general, one mechanism, reachable from anywhere).

**Capability vs passivity:** purely infrastructure — it makes MARVIN answerable by voice without doing anything *for* Gil he'd rather do himself; no north star argues against it.

## Decisions
<!-- marvin:decisions -->
### brain-routing: How should the endpoint choose fast brain vs. deep brain for v1?
- [ ] A: Always deep brain for v1 (the fast-brain Ollama path is built and unit-tested but not wired as the live router default). Avoids ever mis-routing a side-effect request to a tool-less model; tune the split once there's real voice traffic — same phased-rollout shape ADR 0023 used for `route.py`.
- [ ] B: Reuse `route.py`'s classifier output directly: zero keyword hits → fast brain, any hit → deep brain. Couples voice routing to a classifier tuned for a different purpose (which Claude *profile* handles a coding/research task), at a documented ~70% accuracy with a known-weak off-topic signal (ADR 0023).
- [ ] C: A new, separate lightweight heuristic just for voice (e.g. message length / question-word pattern) — decoupled from `route.py`, but is a second hand-tuned classifier to maintain.

## Tests written first

Mirrors the existing one-file-per-module test convention (`chat_api.test.js`, `pending_actions.test.js`, `rotation_policy.test.js`, `session_runner.test.js`). Every async call in these tests gets an injected fake (fake `spawnFn`, fake HTTP-call fn, fake clock) with explicit small timeouts, following `pending_actions.test.js`'s pattern (`timeoutMs: 100-5000`) — never a real network/process call and never vitest's unmocked defaults, which is the most likely cause of the prior attempt's 1200s automated-verification timeout.

**From the ticket's "Tests try to break it":**
1. `voice_api.test.js` — a deep-brain turn whose mocked `runSession` requests a non-read-only tool call is never reported as executed/succeeded without a resolved pending action; with `permissionHookPath` wired, a real but fast (`HOOK_TIMEOUT_MS` tiny) run of `permission_hook.js` denies-by-timeout and the router surfaces a refusal, never a hang or a silent allow.
2. `voice_api.test.js` — `device: "chromecast"` (and `device` missing) → `400`/`403` refusal, no brain called, nothing appended to the Thread.
3. `to_speakable.test.js` — markdown (`**bold**`, `` `code` ``, `# heading`, `[text](url)`) and bare URLs are all stripped/flattened; `voice_api.test.js` — asserts the sanitizer runs on *every* reply path (fast-brain reply and deep-brain reply), even when the mocked brain itself returns markdown/a URL.
4. `voice_api.test.js` — fast-brain call fn rejects → spoken fallback sentence, not silence/hang; mocked `runSession` yields an `error` event (session_runner's existing shape) → same: a plain spoken fallback, not silence.

**Additional misuse coverage the ticket's list didn't name:**
5. Empty/whitespace-only `text` → `400`, no brain invoked (parity with `chat_api`'s `message` validation).
6. Oversized `text` (e.g. 100 KB) → rejected with a clear `400`, not a crash or multi-second hang.
7. Malformed JSON body → `400` (same code path chat_api already proves; confirm parity, don't reinvent).
8. Case-insensitive `device` (`"iPhone"` vs `"iphone"`) accepted, matching `device_gate.js`'s existing case-insensitive match style.
9. Repeat: same `clientId` sent twice → second call is a no-op (reuses `threadStore.findByClientId`, exercised today only by `offline_batch_api.js`), no double Thread entry, no second brain call.
10. Concurrency: two overlapping `/voice` calls for two different turns don't share mutable module-level state (pure functions / per-call locals only) — a cheap regression guard, not an attempt to fix the pre-existing `--resume`-same-session race already shared with `chat_api`.
11. Stale state: a turn arriving right after a rotation (`pendingSummary` set) prepends and then consumes the summary exactly once — same scenario `chat_api.test.js` already proves, written again for the voice path since it shares `rotation_policy`.
12. `sentence_stream.test.js` — pure unit tests: splits on `.`/`!`/`?` boundaries, holds back an incomplete trailing fragment, flushes it on stream end, handles zero input and input with no sentence boundary at all (huge single run-on string).
13. `fast_brain.test.js` — pure unit tests with an injected call fn: non-streaming mode returns one string; streaming mode yields incremental chunks; a malformed/non-JSON response line is skipped, not thrown.
14. `brain_router.test.js` — unit tests for whichever option the Decision above resolves to, plus: empty string and a string with no recognizable words both resolve to a defined (not `undefined`/throwing) choice.
15. `voice_latency.test.js` — logs one line per stage per turn to the injected path; a turn with a missing/zero stage timestamp doesn't throw; concurrent turns' log lines don't interleave into a single malformed JSON line (each `appendFileSync`/newline call is atomic per write).
16. `voice_api.test.js` — `GET /voice/thread`-style parity isn't needed (existing `GET /thread` already serves all sources including `voice`) — test instead that a completed voice turn's user+assistant messages are retrievable via the *existing* `GET /thread` route with `source: 'voice'`, proving no parallel thread/storage was built.
17. `index.js` wiring: a focused test (or inline assertion in `voice_api.test.js`) that `runSessionFn` is invoked with a non-empty `permissionHookPath` pointing at the real `permission_hook.js`, not merely that the option is *accepted*.

## Task List

1. `dashboard/mobile-backend/to_speakable.js` — `toSpeakable(text)`: strip Markdown emphasis/headers/lists/code fences, convert `[text](url)` → `text`, strip bare URLs, collapse whitespace. Write its tests first (item 3).
2. `dashboard/mobile-backend/sentence_stream.js` — a small stateful accumulator: `push(deltaText) -> string[]` (complete sentences), `flush() -> string|null` (trailing fragment). Tests first (item 12).
3. `dashboard/mobile-backend/fast_brain.js` — `callFastBrain({ text, postFn, stream })`: POST to Ollama's `/api/chat` (`model: 'qwen2.5:3b'`), default `postFn` using raw `http`/`https` (no new dependency, mirrors `post_json.js`); streaming mode reads newline-delimited JSON chunks the same way `session_runner.js` reads CLI stdout. Tests first (item 13).
4. `dashboard/mobile-backend/brain_router.js` — `chooseBrain(text, opts)` implementing whichever option the Decision resolves to (provisional default: Option A, always deep, pending the owner's answer). Tests first (item 14).
5. `dashboard/mobile-backend/voice_latency.js` — `logStage(turnId, stage, tsMs, { path })`, appends one JSON line to `~/.claude/logs/voice-latency.jsonl` by default. Tests first (item 15).
6. `dashboard/mobile-backend/voice_api.js` — `createVoiceApiRouter({ threadStore, runSession, callFastBrain, chooseBrain, logStage, permissionHookPath })`:
   - `POST /voice` — validate `text` (non-empty, size-capped), `device` (case-insensitive enum: homepod/mac/iphone/watch), optional `abilities`, optional `clientId`, optional `stream` (default `true`).
   - Dedup via `threadStore.findByClientId`.
   - Append user message (`source: 'voice'`).
   - `chooseBrain` picks fast or deep; deep path calls `runSession({ ..., permissionHookPath })` exactly as `chat_api.js` does (rotation/summary handling copied, not reinvented); fast path calls `callFastBrain`.
   - Every emitted chunk and the final reply passes through `toSpeakable`/`sentence_stream`.
   - `logStage` calls at: received, routed, first token, first sentence.
   - On any brain being unreachable, emit a plain spoken fallback sentence, never silence/hang.
   - Append assistant message (`source: 'voice'`) same as chat.
   - Tests first (items 1, 2, 4–11, 16, 17), written before this file.
7. `dashboard/mobile-backend/index.js` — construct `voiceApiRouter` with `permissionHookPath: path.join(__dirname, 'permission_hook.js')` (new `__dirname` via `fileURLToPath(import.meta.url)`, matching `session_runner.test.js`'s idiom) and splice it into the router chain.
8. `dashboard/mobile-backend/README.md` — document `POST /voice` in the same contract style as `POST /offline-batch` and the "Permission bridge" section, including the fallback-on-unreachable and refusal-on-unknown-device behaviors.
9. Manual-only (not part of `npm test`/CI, to avoid repeating the prior timeout): once merged, a one-off smoke check against the real Ollama `qwen2.5:3b` on the Mini, logging actual stage latency, to sanity-check the <1s budget against real hardware — recorded as a follow-up note, not a blocking step here.