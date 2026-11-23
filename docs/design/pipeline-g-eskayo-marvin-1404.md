## North-star fit

**Reuses:** the existing owner-decisions reply pattern exactly as built in `lib/owner_decisions.py` (the `ADDRESSED_MARKER` = `<!-- marvin:decisions-addressed -->` constant and the "no commit, no reply = waiting on MARVIN" model) and the real precedent on PR #1291 — a comment opening with that marker, a `## Answering …` heading, then prose, posted via `~/.agents/bin/gh pr comment` (never raw `gh`, per [[reference-github-gate]]). The "Earlier answers" checklist format is `lib/supersession.py:131` (`section()`) verbatim — the ticket body already is that function's output; I just resolve each row. No new abstraction, no new file.

**Simplest sufficient approach:** this ticket has no feature to build. `deep-latency`'s chosen option ("Keep it") already matches what PR #1401 ships (holding line + Thread fallback, 24 s cold start unchanged) — zero code change. `deep-tools` has no chosen option (all three boxes unticked) and the owner's attached note is not a question (`question=no` in the issue's own marker) — it's Gil saying out loud he's still shaping what he wants, not asking anything of MARVIN. Manufacturing a fresh Decisions re-ask here would be re-litigating a question he just said he isn't ready to answer — more prompts, not more capability (north star 3). The simplest sufficient action is a status reply: report what was and wasn't carried out, and why, with no code and no new decision forced on him.

**Resources:** spends nothing but one `gh pr comment` call. Saves a 4-hour poll cycle's worth of "waiting on MARVIN" state and the follow-up ticket's own self-close.

**Phone-OS direction:** neutral — this is pipeline hygiene (owner-decisions loop), not a voice/device capability.

**User capability:** leaves Gil with an accurate, legible record of what happened to his decisions and an explicit, honest "this is still open, here's why I didn't force it" rather than silently dropping the unanswered question or nagging him with it again. More capable (clear state), not more passive, not more pestered.

**Judgment call (stated, not escalated to a Decisions section):** I treat `deep-tools` as *reported, not re-asked*. The three original options are still live, unticked, in PR #1401's own description — Gil can answer them there whenever he's ready; a second copy of the same question in a comment, right after he wrote "we are still working on that," would read as pressure, not help. If this call is wrong, it's cheap to reverse (post the re-ask any time).

**One substantive finding worth surfacing (not a code task):** `~/.agents/instance/docs/plans/dashboard-ux-potholes-2026-10-29.md:487` already scopes a "status sentence" feature ("2 things need you; the Mini is low on disk") to ticket #670 — a short human-language summary for the voice/phone/header surfaces, as opposed to naming checks or files. That is close to what Gil's `deep-tools` note describes ("not just telling me alerts by file name"), and PR #1401 doesn't build it (it's absent from both "What it does" and "Not in this PR"). I surface this connection in the reply as context, not as a new forced decision — consistent with the judgment call above.

## Earlier answers to the same question — disposition

All five are **relation hits** (they cite ticket #670, not the `deep-tools`/`deep-latency` decision ids) — `lib/supersession.py` found them by ticket reference, not by a matching `### deep-tools:`/`### deep-latency:` heading. None restates either decision's question, so none needs an "Amendment" note. Each is **kept**, with a stated reason in the reply:

1. `instance/docs/plans/dashboard-ux-potholes-2026-10-29.md:487` — scopes a *different* feature ("status sentence") to #670; not a restatement. Keep — but called out as context for the `deep-tools` note (see above).
2. `instance/docs/plans/marvin-business-plan-2026-10-25.md:53` — risk narrative citing #670–675 re: OpenJarvis; not a decision answer. Keep — different question.
3. `instance/docs/plans/marvin-website-2026-11-02.md:226` — public roadmap table row citing ADR 0075 (status "Proposed") and #670/#672; describes the feature's existence for website copy, not the tool-scope/latency choice. Keep — different question. (Aside, out of scope here: ADR 0075's `Status: Proposed` could arguably move to `Accepted` now that #1401 substantially implements it — not touching it, since no part of this ticket asks for an ADR-status edit.)
4. `~/.claude/projects/-Users-gileskayo/memory/project-homepod-appletv-spike.md` — dependency/status note ("blocked by 670"); not a decision answer. Keep — different question.
5. `~/.claude/projects/-Users-gileskayo/memory/project-investor-demo-plan.md` — milestone-scheduling line; not a decision answer. Keep — different question.

## Tests (verification strategy — no source code changes, so no unit tests)

No file under `dashboard/` or `lib/` changes, so there is no input surface to fuzz and TDD's red-green-refactor loop doesn't apply here — stated explicitly rather than skipped silently, per the ticket's own adversarial checklist:

- **Bad/empty/huge/malformed input, dependency failures, concurrency, wrong permissions, stale state:** not applicable — this ticket produces one GitHub comment, not a code path. 
- **"The notes contradict a chosen option: say so, don't guess."** Checked by hand: the `deep-tools` note doesn't contradict any ticked box (nothing is ticked); `deep-latency`'s "Keep it" doesn't contradict anything it is answering. No contradiction found — stated as such in the reply rather than silently assumed.
- **"The PR changed since the decisions: re-read it before acting."** Done as part of this plan: fetched PR #1401 live (`gh pr view 1401 --json`, `gh pr diff`, and the `voice-endpoint-670` branch content) — no commits landed after the 2026-11-22T19:59:19Z decisions comment; PR is still OPEN. Re-confirm this at execution time (comments/commits may have landed between planning and execution).
- **The one real adversarial surface — the comment itself must pass the merge gate's decisions parser.** Before posting, run the draft comment body through `lib/decisions_check.py` (the same parser `bin/gh` uses) to confirm it does **not** trip `DECISIONS_NOT_ASKABLE` (no bare "## Decisions"/"## Open questions"/"## Choose" heading without a `<!-- marvin:decisions -->` block — my draft avoids those headings entirely, using a plain status heading instead) and does not trip `DECISIONS_UNPARSED`.
- **Mechanical acceptance check:** after posting, run `lib/owner_decisions.py status --repo G-Eskayo/marvin --pr 1401` (or feed the posted comment into `owner_decisions._fresh_status`) and assert `addressed_by == "reply"` — this is the actual code-level definition of "addressed" the merge gate and the hourly scan use, so it's the right thing to assert rather than eyeballing the comment.

## Task List

1. Draft the reply comment body for PR #1401 (plain-text/markdown, no `## Decisions`/`## Open questions`/`## Choose` heading unless paired with a marker):
   - Open with `<!-- marvin:decisions-addressed -->`.
   - `deep-latency`: state "Keep it" is carried out — matches the already-built behavior (holding line, 8 s Siri-doorway wait, Thread fallback for long deep answers); no commit was needed. Note there is no screenshot to retake/pin (backend-only PR, no UI changed; evidence is the CLI/HTTP table already in the PR description).
   - `deep-tools`: state plainly that none of the three options was chosen, the attached note is not a question (so nothing to answer), and that per Gil's own "still working on that," it's being left open rather than re-asked — the same three options remain live, unticked, in the PR description whenever he's ready.
   - Surface the `dashboard-ux-potholes-2026-10-29.md` "status sentence" (#670, S3) connection to the `deep-tools` note, as context/offer, not a forced decision.
   - "Earlier answers" disposition: list the five docs, each marked kept with its one-line reason (per the table above).
2. Validate the draft against `lib/decisions_check.py` locally (no heading trips the gate; marker present).
3. Post the comment on PR #1401 via `~/.agents/bin/gh pr comment 1401 --repo G-Eskayo/marvin --body-file -` (never raw `gh`, never `--no-verify`-equivalent bypass).
4. Verify mechanically: `lib/owner_decisions.py status --repo G-Eskayo/marvin --pr 1401` reports `addressed_by: "reply"` and `built: true`.
5. No edits needed to `instance/docs/plans/*`, the two memory files, PR #1401's source files, or `docs/adr/0075-*` — confirmed above that all five "earlier answer" citations are kept as-is, and no code path carries a chosen, actionable option.
6. No action needed to close ticket #1404 itself — the hourly scan (`lib/owner_decisions.py scan`) closes it automatically once the reply lands (per its own filing code, `lib/owner_decisions.py:390`).