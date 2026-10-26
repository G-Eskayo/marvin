# ADR 0075: Voice — one endpoint, three ways in; MARVIN replaces Siri as the voice in the house

Date: 2026-10-26
Status: Proposed
Related: [[0001]]–[[0005]] (the July voice client), [[0039]]–[[0046]] (MARVIN Mobile), [[0043]] (Face ID gate),
G-Eskayo/marvin#651 (HomePod and Apple TV spike)

## Context

The owner wants MARVIN, not Siri, to be the assistant he talks to on the HomePods and around the house, then a
conversation with MARVIN on the Mac, then the Voice surface on the iPhone (decided 2026-10-26, in that order).

Facts that shape it (checked 2026-10-26):

- **A HomePod's microphone answers only to Siri.** No third-party assistant can listen on it, and the hobbyist
  jailbreak (checkm8 over a hidden port) risks bricking the speaker. A HomePod can still *play* anything over AirPlay 2,
  and Siri can hand a request to a Shortcut ("personal requests") that calls MARVIN over Tailscale.
- **The M4 Mac mini has no microphone.** The MacBook has one; the Mini needs a USB or Bluetooth mic, or another device
  listening for it.
- **OpenJarvis (Stanford, Apache-2.0) has a basic voice loop:** record until silence, Whisper, answer, speak. It has no
  wake word, no barge-in and no streaming, and its roadmap calls a real voice interface research-stage. Its speech code
  is a thin wrapper over open libraries MARVIN can use directly: faster-whisper (speech to text) and Kokoro (text to
  speech), both local.
- **Seal Speak already does live on-device speech recognition**, so Apple's on-device recognizer is proven in-house.

## Decision

1. **One voice endpoint on the mobile backend.** Words in, a short reply written to be spoken out. Every exchange lands
   in the one Thread (CONTEXT.md, MARVIN Mobile), so a question asked on a HomePod shows up on the phone. Every way in
   below calls this endpoint; none has its own agent.
2. **Three ways in, built in this order:**
   1. **The Siri doorway** (HomePod, iPhone, Watch, CarPlay): "Hey Siri, MARVIN" runs a Shortcut that sends what was
      said and speaks MARVIN's answer, then keeps listening until "that's all", so one Siri call becomes a whole
      conversation. Siri only opens the door; MARVIN does the thinking. Days of work, and it reaches the HomePods.
   2. **The Mac voice loop** — the real replacement for Siri: MARVIN's own wake word ("Hey MARVIN"), local speech to
      text, local voice out, and interrupting MARVIN mid-sentence. Its voice plays through the HomePods over AirPlay, so
      MARVIN listens and answers and the HomePod is only the speaker.
   3. **The iPhone Voice surface** in MARVIN Mobile, on the same endpoint.
3. **Actions by voice follow [[0005]] and [[0043]].** Questions and look-ups run freely. Anything with a side effect is
   said aloud as a plan, and its confirmation goes to the phone behind Face ID, because a HomePod or a Mac speaker
   cannot check who is talking.
4. **Use the speech libraries directly, not OpenJarvis as a dependency.** It adds a large framework for a small loop.
   Local first, so voice keeps working after the subscription ends.

5. **Two brains, streamed, against a latency budget** (added 2026-10-26). The full MARVIN session (Claude, tools,
   memory) is too slow to be the first thing you hear: a tool call takes seconds. So:
   - **Fast brain:** a small local model, already warm, answers small talk and simple look-ups by itself, and for
     anything bigger says what it's doing ("checking the board") within a second.
   - **Deep brain:** the MARVIN session in the Thread does the real work; its answer is spoken when ready, or sent to
     the phone if it's long. The route classifier decides which brain takes a turn.
   - **Streaming at every stage:** speech to text streams, the reply streams, and the voice starts at the first
     finished sentence. Turn-taking uses a turn-detection model (smart-turn), not a fixed silence timer, so MARVIN
     neither cuts you off mid-thought nor waits 1.5 s after you stop.
   - **Budget:** under 1 s from the end of your sentence to MARVIN's first sound, measured per stage and logged, so a
     slow stage is found, not guessed at.
   - The Mac loop is built on **Pipecat** (open-source voice pipeline framework, BSD-2), whose all-local Mac example
     (Silero VAD, smart-turn, MLX Whisper, a 4B local model, Kokoro) reports under 800 ms voice to voice, rather than
     on OpenJarvis's turn-based loop.

## Consequences

- The HomePods work with MARVIN within days, before the Mac loop exists, and nothing has to be jailbroken.
- "Hey Siri" stays as the first word on a HomePod until the owner chooses to put a mic-equipped device beside it
  for the Mac loop; that is the price of Apple locking the HomePod's microphone.
- The endpoint, its Thread and its confirmation path are written once and shared by all three ways in.
- The Siri doorway cannot stream (a Shortcut waits for the whole reply), so it uses the fast brain's first answer and
  sends the deep brain's result to the phone when it takes longer than a few seconds.
