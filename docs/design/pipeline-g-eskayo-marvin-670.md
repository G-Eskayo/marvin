## North-star fit

**Reuses before adding anything:**
- `dashboard/mobile-backend/thread_store.js` — `createThreadStore()` already accepts `source: 'voice'` (line 32's `validSources`) and needs **zero changes**. This is "the one Thread" requirement, already built.
- `dashboard/mobile-backend/session_runner.js`'s `runSession()` — the deep brain, reused as-is; today only `chat_api.js` calls it, and *without* `permissionHookPath`, so the plan-and-confirm hook (ADR 0005/0043) exists in code (`permission_hook.js` + `pending_actions.js` + `permission_api.js`) but isn't wired into any live traffic yet. Voice wires it for the first time rather than inventing a new guardrail.
- `dashboard/mobile-backend/rotation_policy.js` (`shouldRotate`/`summarize`) — reused unchanged for voice's session rotation, same as chat.
- `dashboard/mobile-backend/chat_api.js` — the structural template (NDJSON-streaming router shape, body-read/JSON-parse/validate pattern) for the new `voice_api.js`.
- `skills/route/scripts/route.py`'s `resolve_intent()` — ADR 0075 point 5 names this explicitly ("the existing route classifier picks the brain"); reused via a minimal additive `--json` flag rather than a new classifier.
- `dashboard/electron/main/index.js`'s `AGENTS_PYTHON = join(homedir(),'.agents','venv','bin','python')` + `execFileAsync(AGENTS_PYTHON, [script, ...args])` pattern — reused to shell out to `route.py` (per memory: the venv python, or the classifier silently degrades to tag matching).
- `dashboard/mobile-backend/index.js`'s router-chain style (`handled = await xApiRouter(req,res); if (handled) return`) — `voice_api.js` slots in the same way.
- `dashboard/mobile-backend/post_json.js` — pattern reused for a small new fast-brain HTTP client (`local_model.js`), not a new abstraction.
- Logging: `com.marvin.mobile-backend.plist` already redirects stdout to `~/.claude/logs/mobile-backend.log`; per-turn timing is a `console.log(JSON.stringify(...))` line, no new log file/schema.

**New, because nothing fits:** a markdown/URL → speakable-text transform, a device→abilities lookup (homepod/mac/iphone/watch), and a fast-brain HTTP client for the warm local model — none of these exist anywhere in the repo (confirmed by search).

**Simplest sufficient approach:** this ticket is the *endpoint* only — text in, text out — not STT/TTS/Pipecat (those are explicitly "Next: Siri doorway; Mac voice loop"). Scoping to text keeps this a small, composable service the mobile backend absorbs, per the ticket's own instruction.

**Tokens:** spends a few tokens adding one Python flag and ~5 small JS modules; saves tokens everywhere else by reusing the chat pipeline's session/rotation/confirm machinery instead of rebuilding it, and by routing small talk to a free local model instead of the paid session.

**User capability:** leaves Gil more capable — he gets a voice-first way into the same full MARVIN (tools, memory) from any room, with side effects still gated behind his own Face ID tap, not a passive "it just talks back" toy.

**Judgment calls made (not blocking, noted here rather than guessed silently):**
- Brain-routing mapping: `recall`/`research` intents (confident match) → fast brain; `coding`/`architecture` (including the no-match default) → deep brain. Pure chit-chat with zero keyword/embedding hits currently falls to the `architecture` default and thus to the deep brain — a known soft spot in reusing a dev-task classifier for conversational routing, left as-is because the ADR explicitly says to reuse this classifier; sharpening chit-chat detection belongs with #675's model tuning, not here.
- Fast-brain model name is an env var (`MARVIN_VOICE_FAST_MODEL`) with a placeholder default, since the ADR itself defers the exact model to #675.
- Device abilities table (homepod/mac/iphone/watch → show/touch/listen/speak) derived directly from CONTEXT.md's "Endpoints and the brief" definitions — an internal capability flag passed into the deep-brain's prompt context, not new UI.

No Decisions section: everything the ticket needs is already pinned down by ADR 0075/0043/0005 and the acceptance criteria; nothing here requires Gil to pick between named options.

## Tests to write first

1. `toSpeakable()` strips Markdown (`**bold**`, `` `code` ``, headers, bullets) and both inline (`[text](url)`) and bare URLs, leaving plain readable text — ticket's explicit break-it case.
2. Unknown `device` value (not one of homepod/mac/iphone/watch) is refused (403), no session run, no thread append — ticket's explicit break-it case.
3. A side-effecting tool call from the deep brain, with no phone resolution, never executes: `voice_api.js` must call `runSession(...)` with a non-null `permissionHookPath`; a pending action is created and the turn surfaces "waiting on your phone," not a false success — ticket's explicit break-it case (and the thing most likely to have been the prior attempt's missed wiring).
4. Fast-brain unreachable (connection refused) → a plain spoken fallback sentence is emitted, never an empty/silent stream — ticket's explicit break-it case.
5. Deep-brain spawn failure (same failure mode `session_runner.js` already yields as `{type:'error'}`) → `voice_api.js` converts that into a spoken fallback sentence too, not a dropped error event — same break-it case, other brain.
6. Missing/empty `text` field → 400, no session run.
7. Missing `device` field entirely → refused, same path as unknown device.
8. Oversized payload (e.g. >100KB text) → rejected with 400, not a crash or hang.
9. Malformed JSON body → 400 (mirrors existing `chat_api.js`/`actions_api.js` pattern).
10. `route.py --json` subprocess failing/missing (dependency failure) → falls back to deep brain (safe default), request still completes.
11. Two identical/repeated voice requests that each trigger the same side-effecting tool call create two independent pending actions; neither executes without its own explicit phone resolution (repeats are safe by the confirm-gate's existing design — characterize it for voice specifically).
12. Two concurrent voice requests from different devices with no existing session both get a fresh session id and both get correctly appended to the Thread in call order, with no dropped writes (characterizes existing `thread_store.append`'s synchronous-write safety under this new caller).
13. For a deep-brain-routed request, a placeholder "here's what I'm doing" speak event is emitted *before* the deep-brain stream is awaited — ordering proxy for the <1s-to-first-sound budget (not a wall-clock assertion).
14. Sentence streaming: a deep-brain reply arriving as several small text deltas is re-chunked into complete sentences as they finish, not emitted token-by-token or only at the very end.
15. `route.py --json`: new flag returns machine-readable `{intent, method, hits/score}` for a sample of inputs across all four intents, matching today's human-readable output's classification (regression guard on the existing classifier behavior).
16. Thread append uses `source: 'voice'` for both the user line and the assistant reply (characterizes the "one Thread" requirement end-to-end against the real `thread_store.js`, not a mock).

## Task List

1. `skills/route/scripts/route.py`: add a `--json` flag that prints `{"intent":..., "method":..., "score":...}` from `resolve_intent()`; add `skills/route/scripts/tests/test_route.py` covering it (test 15).
2. `dashboard/mobile-backend/speakable.js`: `toSpeakable(text)` (strip Markdown + URLs) and `createSentenceStreamer()` (incremental sentence chunking); `dashboard/test/speakable.test.js` (tests 1, 14).
3. `dashboard/mobile-backend/voice_devices.js`: `DEVICE_ABILITIES` map (homepod/mac/iphone/watch) + `isKnownDevice(device)`; `dashboard/test/voice_devices.test.js` (test 2).
4. `dashboard/mobile-backend/brain_router.js`: `classifyBrain(text, opts)` shelling out to `route.py --json` via the venv-python pattern, mapping intents to `fast`/`deep`, falling back to `deep` on subprocess failure; `dashboard/test/brain_router.test.js` (tests 10, 15-integration).
5. `dashboard/mobile-backend/local_model.js`: `streamLocalModel({ prompt, model, baseUrl, fetchFn })` async generator over Ollama's streaming HTTP API, yielding `{type:'text', text}`/`{type:'error'}`; `dashboard/test/local_model.test.js` (test 4, with injected `fetchFn`).
6. `dashboard/mobile-backend/voice_api.js`: `createVoiceApiRouter(opts)` implementing `POST /voice` — validates `text`/`device` (tests 2, 6, 7, 8, 9), classifies the brain (step 4), runs fast or deep brain, passes `permissionHookPath` into `runSession` (test 3), converts any error event from either brain into a spoken fallback (tests 4, 5), emits a placeholder before awaiting deep-brain completion (test 13), streams speakable sentences via `speakable.js` (tests 1, 14), appends user+assistant turns to `threadStore` with `source:'voice'` (test 16), applies `rotation_policy.js` exactly as `chat_api.js` does, and logs a per-turn timing line (`routingMs`, `firstTokenMs`, `firstSentenceMs`, `firstReplyMs`). `dashboard/test/voice_api.test.js` (tests 3, 5, 6, 7, 8, 9, 11, 12, 13, 16), reusing the `MockRequest`/`MockResponse` harness from `chat_api.test.js`.
7. `dashboard/mobile-backend/index.js`: wire `voiceApiRouter` into the existing router chain alongside `chatApiRouter`, passing the real `threadStore` and a real `permissionHookPath` pointing at `permission_hook.js`.
8. `dashboard/mobile-backend/README.md`: document `POST /voice` (request/response shape, device values, confirm-gate behavior, fallback-on-unreachable-model behavior) in the same style as the existing `/chat` section.
9. Run the full `dashboard` test suite to confirm no regressions in `chat_api`, `session_runner`, `thread_store`, `permission_hook` consumers.