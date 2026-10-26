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