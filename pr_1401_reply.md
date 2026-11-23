**deep-latency** — Addressed. "Keep it" is already built in commit `9b94ec7d`/`session_runner.js` (the holding line "Checking." that starts within ~230 ms, covering the 24 s to deep brain first word). No new commit needed.

**deep-tools** — Open. No option was chosen (`"choices": []`), only your note attached: *"I want it to be interactive like a lab assistant so be able to report on anything but in like a human understandable form, not just telling me alerts by file name but we are still working on that."* That note is the start of a bigger question (what "report on anything, human-understandably" means concretely) that isn't settled yet. I'm not inventing an implementation for an unanswered question — it stays open in the PR description until you're ready.

**Earlier answers** — Five earlier mentions of ticket #670 ('Voice endpoint: words in, a spoken reply out, in the Thread; actions confirmed on the phone') in CONTEXT.md, docs/, and design/: each marked kept. They mention the voice endpoint feature but don't restate either decision's question or answer.

**Screenshots** — None retaken. This PR has no UI surface (backend API + tests only).

<!-- marvin:decisions-addressed -->
