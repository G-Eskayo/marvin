# Handoff — Retrospective

## 2026-07-07 — Voice-interface design + MLX benchmark side-quest
**F:** A benchmark script and its logs were written to this session's scratchpad (`/private/tmp/claude-501/.../scratchpad/`) partway through a still-in-progress side-quest. Scratchpads are session-scoped and don't exist in a new session — without manually flagging this in the handoff, the next session would have silently lost that work with no error, since nothing about the scratchpad's existence is visible from outside the session that created it.
**I:** The handoff protocol had no explicit check for this. Added a rule to always check whether the session wrote anything to a temp/scratchpad location that's meant to outlive the session, and if so, name its durable destination in the handoff rather than just noting the loss risk.
