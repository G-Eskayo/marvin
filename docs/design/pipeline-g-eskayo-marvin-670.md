I have what I need. Here's the plan.

## North-star fit

Reuses, before adding anything: the mobile backend's whole request pipeline (`dashboard/mobile-backend/index.js`'s Tailscale device gate, already enforced on every route — no new gate needed for "unknown device"); `chat_api.js`'s turn pattern (thread append → run → backfill session → rotate) and its `createChatApiRouter(opts)` dependency-injection shape; `session_runner.js`'s `runSession()` for the deep brain, unchanged, including the `permissionHookPath` wiring that already makes side effects wait for Face ID approval via `pending_actions.js`/`permission_hook.js` (ADR 0005/0043 — already built, not re-invented); `thread_store.js`, which already accepts `source: 'voice'` (someone anticipated this); `route.py`'s `resolve_intent()`/`classify()` for brain routing (ADR calls for "the existing route classifier," not a new one); and `dashboard/electron/main/timing.js`'s `appendTiming()` JSON-lines pattern for the per-stage latency log the ticket asks for, instead of inventing a new logger.

Simplest sufficient approach: the endpoint is text-in/text-out (the ticket's own "Input: what was said, as text" — STT/TTS stay in the Siri doorway and Mac-loop tickets that consume this one). That means no audio handling, no Pipecat, no faster-whisper/Kokoro in this ticket — just routing, a speakable-text filter, and the Thread write, on top of infrastructure that already exists.

Spends tokens on: a genuinely new piece — the fast-brain local-model call (direct Ollama HTTP, no subprocess, no framework) — because the ADR explicitly rejects OpseeJarvis-as-dependency and nothing else in the repo talks to Ollama from JS yet. Saves tokens everywhere else by reusing session_runner/permission_hook/thread_store as-is.

Leaves the user more capable: this is the one seam three different ways of talking to MARVIN will share, so building it once here means the Siri doorway and Mac voice loop tickets add a client, not a brain.

## Decisions

<!-- marvin:decisions -->
### classifier: Voice brain routing — keyword-only or embedding classify, given the <1s-to-first-sound budget?
`route.py` already has two ways to pick an intent: a zero-I/O keyword scan, and the embedding classifier (ADR 0023, 87.5% validated accuracy) which costs an Ollama embed call plus a ChromaDB query before routing even starts. I can't benchmark real latency on the Mini from this worktree, and the 1s budget is a hard number you set, not mine to trade away quietly.
- [ ] A: Keyword-only now — safest for the budget, accept lower routing accuracy until #675 tunes the fast brain
- [ ] B: Embedding classifier now — more accurate, spends part of the 1s budget before the fast/deep brain even starts answering
- [ ] C: Try embedding with a short timeout (~150ms), fall back to keyword-only if it doesn't return in time

## Tests written first

**From "Tests try to break it" in the ticket:**
1. A side-effect tool call with no phone confirmation is never executed — mock `runSession` to emit a `tool_use` event and never resolve it; assert the voice response never reports the action as done and the pending action stays `pending` (reuses `chat_api.test.js`'s `createMockRunSession` shape).
2. An unknown `from` value (not `homepod`/`mac`/`iphone`/`watch`) is refused with 400, independent of the Tailscale gate.
3. A reply containing Markdown (`**bold**`, `` `code` ``, `[text](url)`) or a bare URL comes back through `toSpeakable()` with none of that syntax and no raw URL.
4. Fast brain unreachable (Ollama fetch rejects) *and* deep brain unreachable (`claude` spawn fails) still returns a non-empty plain-text reply, never an empty/hanging response.

**Misuse the section didn't name:**
5. Empty string / missing `text` field → 400 (mirrors `chat_api.js`'s missing-`message` check).
6. Missing `from` field → 400.
7. Malformed JSON body → 400 (mirrors chat_api's `JSON.parse` catch).
8. Oversized `text` (e.g. >4000 chars — a stuck mic or garbled STT) → 400, not silently truncated into a bad answer.
9. Route classifier subprocess fails/times out → falls back to deep brain (safer default than guessing fast), not an error.
10. Fast brain fails but deep brain succeeds → deep brain's answer is returned, not the canned apology (apology is last resort only).
11. Two voice turns in flight at once (concurrency) → each gets its own Ollama/claude process; no crash. (Does **not** fix `thread_store`'s single `currentSessionId`/no-lock design — that's `chat_api.js`'s existing limitation too, out of scope here.)
12. Same text sent twice (repeat) → two independent Thread entries; the ticket's Input shape carries no client idempotency key, so this is expected, not a bug.
13. `appendTiming` throwing (disk full, bad permissions) never breaks or delays the actual voice turn — it's fail-soft by its own existing contract; test that a throwing `record` fn doesn't propagate.
14. A stale/rotated session id passed in still works — `runSession` already handles `--resume` failures via its existing error path; assert the voice router surfaces that as the plain-fallback reply, not a crash.
15. `speakable.js` unit tests: nested/mixed Markdown, multiple URLs, empty string, string that's only a URL, nothing-to-strip passthrough.
16. `route.py --json` flag: valid JSON on stdout for both keyword and embed paths, and for the explicit intent-override flags.

## Task List

1. [ ] Add a `--json` output flag to `skills/route/scripts/route.py` (machine-readable `{intent, method, score_or_hits}`) — test first in `lib/tests/test_route.py`. No existing caller parses the current human-readable `print_routing` output, so this is additive only.
2. [ ] Write `dashboard/mobile-backend/speakable.js` (`toSpeakable(text)`: strip Markdown syntax and URLs, enforce a short-reply length cap) — tests first in `dashboard/test/speakable.test.js`, modeled on `docs_text.js`'s `plain()` regex approach.
3. [ ] Write `dashboard/mobile-backend/device_abilities.js` (static `homepod`/`mac`/`iphone`/`watch` → abilities map from CONTEXT.md's show/touch/listen/speak vocabulary, plus a `isKnownDevice()` guard) — tests first.
4. [ ] Write `dashboard/mobile-backend/voice_api.js` (`createVoiceApiRouter(opts)`, `POST /voice`): validates input (tests 5–8); calls the route classifier per the Decision's answer (test 9); calls fast brain (Ollama `/api/generate`, injectable `fetchFn`) or deep brain (`runSession`, injectable like `chat_api.js`) per the intent→brain mapping; streams sentences as they finish; runs every reply through `toSpeakable()`; falls back deep→canned on failure (tests 4, 10); appends both turns to `threadStore` with `source: 'voice'`; logs per-stage timing via `appendTiming` (received/routed/first-token/first-sentence/complete) (test 13) — tests first in `dashboard/test/voice_api.test.js`, reusing `chat_api.test.js`'s `MockRequest`/`MockResponse`/`createMockRunSession` pattern (tests 1, 11, 12, 14).
5. [ ] Wire `voiceApiRouter` into `dashboard/mobile-backend/index.js` the same way `chatApiRouter` is wired (after the permission/actions routers, before the 404 fallthrough) — it rides the existing device gate, no new gate code.
6. [ ] Document `POST /voice` in `dashboard/mobile-backend/README.md` (request/response shape, error codes), matching the existing per-route doc convention.
7. [ ] Add a CONTEXT.md note under "MARVIN Mobile" recording what got built (brain-routing mapping, latency-log location, text-in/text-out scope vs. the Siri doorway/Mac loop tickets that will add audio) — ADR 0075 states intent, CONTEXT.md should state what's real.
8. [ ] `npm test` (vitest) in `dashboard/` — full suite green, no regressions.