# Handoff — Retrospective

## 2026-07-07 — Voice-interface design + MLX benchmark side-quest
**F:** A benchmark script and its logs were written to this session's scratchpad (`/private/tmp/claude-501/.../scratchpad/`) partway through a still-in-progress side-quest. Scratchpads are session-scoped and don't exist in a new session — without manually flagging this in the handoff, the next session would have silently lost that work with no error, since nothing about the scratchpad's existence is visible from outside the session that created it.
**I:** The handoff protocol had no explicit check for this. Added a rule to always check whether the session wrote anything to a temp/scratchpad location that's meant to outlive the session, and if so, name its durable destination in the handoff rather than just noting the loss risk.

## 2026-09-14 — Dashboard mac-mini bring-up + PR #119 review
**F:** A forked `/code-review` agent produced a full 10-finding ranked PR review, but the review existed only in the chat transcript at handoff time — the handoff document itself flagged "not duplicated to a file... worth pasting into a PR comment or scratch note before it's lost to context compression" rather than actually doing it. This is the 2026-07-07 scratchpad-loss pattern recurring in a new shape: not a temp file this time, but transcript-only content from a forked agent.
**I:** Extended the existing scratchpad rule to also cover substantial forked/background-agent output relayed only as a chat message with no backing file — persist it to a durable location (PR comment, `~/.claude/outbox/`, scratch note) while writing the handoff, not just note the risk.

## 2026-10-06 — Resuming finance-os merge-gate thread after laptop death
**S:** Before acting on handoff-2026-10-05-21-44's next steps, the resuming session checked live state and found the prior session (a0753699) still running on the mac-mini, with steps 1–3 and 5 already done (finance-os #8/#9/#10 merged). It made no changes and left the stop-or-continue call to Gil, avoiding duplicate work and two agents editing `~/.agents` at once.
**I:** On Resume only said "read the latest handoff", which quietly treats the handoff as current truth. Added a rule: when resuming, especially cross-machine, first check whether the writing session is still alive and whether its next steps are already done. If it's still running, don't take over work in the same repo.

## 2026-11-02 — Laptop → Mini handoff (portfolio go-live, profile parity, Seal site PR #258)
**F:** The handoff's "Rules for this session" told the next session to show Gil things by opening them in Chrome or Preview. Memory `feedback-open-it-for-gil` (2026-10-30) says the opposite: never Chrome or Finder, review happens inside the dashboard. The handoff didn't mention the conflict, so a resuming session would follow whichever one it read last.
**S:** The handoff's lead line "Verify everything from git and the live site yourself; don't trust these notes" held up. It already recorded that the deploy that went live at 15:01 still had stale facts (3 Palms, 5 "mom" mentions), so the next session can't take "deployed" to mean "correct".
**I:** No skill change; there's only one instance so far (recurrence gate). I flagged the conflict in the memory itself as "ask Gil, then rewrite". If a handoff's rule clashes with a memory again, add a handoff check: "when a session rule contradicts a feedback memory, say which one wins and why."

## 2026-11-10 — Laptop freeze recovery + hardware guardrails (handoff-2026-11-09-21-52)
**F:** The handoff was updated twice after it was first written (open question 2 got a "CLOSED" note, and a "Morning state" section was added) without fixing the earlier text. PR #1199 is listed as "Waiting on Gil's Approve" in Current state, in next step 1 and in the resume prompt, while step 2 and the same resume prompt say it merged. A cold resume would ask Gil to approve a PR that's already merged.
**I:** Second time a handoff has contradicted something (11-02 was a handoff rule against a memory; this one contradicts itself). Added a Rules line: when updating an existing handoff, fix every earlier line the update makes false, the resume prompt included, and check that no PR or ticket is listed as both open and done.
**S:** The memory "Merge failures: disk + main first" already covered missing gitleaks, and this session's merge refusal fit it exactly (gitleaks installed, merge went through). The memory held up, so nothing new to add.
