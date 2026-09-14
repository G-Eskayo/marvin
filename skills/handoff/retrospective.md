# Handoff — Retrospective

## 2026-07-07 — Voice-interface design + MLX benchmark side-quest
**F:** A benchmark script and its logs were written to this session's scratchpad (`/private/tmp/claude-501/.../scratchpad/`) partway through a still-in-progress side-quest. Scratchpads are session-scoped and don't exist in a new session — without manually flagging this in the handoff, the next session would have silently lost that work with no error, since nothing about the scratchpad's existence is visible from outside the session that created it.
**I:** The handoff protocol had no explicit check for this. Added a rule to always check whether the session wrote anything to a temp/scratchpad location that's meant to outlive the session, and if so, name its durable destination in the handoff rather than just noting the loss risk.

## 2026-09-14 — Dashboard mac-mini bring-up + PR #119 review
**F:** A forked `/code-review` agent produced a full 10-finding ranked PR review, but the review existed only in the chat transcript at handoff time — the handoff document itself flagged "not duplicated to a file... worth pasting into a PR comment or scratch note before it's lost to context compression" rather than actually doing it. This is the 2026-07-07 scratchpad-loss pattern recurring in a new shape: not a temp file this time, but transcript-only content from a forked agent.
**I:** Extended the existing scratchpad rule to also cover substantial forked/background-agent output relayed only as a chat message with no backing file — persist it to a durable location (PR comment, `~/.claude/outbox/`, scratch note) while writing the handoff, not just note the risk.
