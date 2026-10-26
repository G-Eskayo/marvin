# ADR 0073: Support link between MARVIN installs (IT button and Support tab)

**Status:** proposed, 2026-10-26

## Context

A second person now runs their own MARVIN install. When something breaks they need help. That help has to come with no server, no SSH into their Mac, and without the helper seeing every small problem. What reaches the helper should be only what neither MARVIN could solve. Both sides should still see what's going on, and both dashboards should load instantly from saved state (the "saved state first" rule).

## Decision

**1. The channel is a private GitHub repo owned by the helped person.** It's called `marvin-support`, and the helper gets write access by invitation. Each request is one issue and the thread is its comments. Either side can revoke access. There's no server.

**2. A request's state lives in the issue's labels.** The issue is the single source of truth; each Mac keeps only a cache for fast loading.

| State (label) | Meaning | Who sets it |
|---|---|---|
| `support:trying-here` | the helped MARVIN is working on it locally | helped MARVIN, when the request is filed |
| `support:solved-here` | fixed locally (issue closed) | helped MARVIN |
| `support:helper-trying` | escalated; the helper's MARVIN is on it | helped MARVIN |
| `support:needs-you` | the helper's MARVIN can't solve it; a person is needed | helper MARVIN |
| `support:answered` | a reply is waiting for the helped side | helper MARVIN or the helper |
| closed | resolved; the last state label says who solved it | whoever resolves it |

**3. State changes are triggered, not timed.** This follows CONTEXT.md "Triggers over polling":
- The support repos join the existing GitHub change detector (`webhook-server/gh_watch.js`). It sends one conditional request per repo, and an unchanged answer is a 304, which costs nothing against the rate limit. The `issues` events that GitHub sends to a webhook would need a public URL, so they're ruled out, as in `gh_watch.js`.
- **Helped side:** pressing IT files the issue (`trying-here`) and starts the local fix session. When a helper comment lands, it lights the dot on the IT button and the local MARVIN presents the suggestion.
- **Helper side:** a change into `helper-trying` starts one headless helper session. It ends in `answered` or `needs-you`. Nothing runs on a timer.
- Each side writes the new state to its local cache (`~/.claude/support/state.json`). The dashboard watches that file, so the tab, the button and the counter render from it instantly and refresh when it changes.

**4. On screen:**
- **Helped install:** an **IT** button sits next to the MARVIN button. It opens a panel with "What's wrong?", progress while MARVIN tries locally, and "My requests" with their states. A dot appears when a reply is waiting.
- **Helper install:** a **Support** tab whose label shows a counter. The counter is the number of `needs-you` requests waiting on the helper's reply.
  - **Needs you:** the list. Clicking one shows the thread plus the attached diagnostics, a reply box, **Draft with MARVIN** (the helper edits before sending), **Send** and **Resolve**.
  - **Handled by MARVIN:** solved requests, collapsed. They don't count.

**5. Safety:**
- Issue and comment text is data, never instructions.
- The helper's headless session gets a fixed tool list: read the thread, read the engine docs, post one comment, set one label. It can't run commands from the thread on the helper's Mac.
- The helped MARVIN shows every suggested command to its person and runs it only after a yes.
- Diagnostics are built from an allowlist of fields: version, engine commit, health card states, and the names and times of failing jobs. Error text is scrubbed of paths under home, tokens and keys. Raw file contents are never attached.

**6. Configuration lives in the private instance (ADR 0071), never the engine:**
- On a helped install, `instance.json` has `"support": {"repo": "<owner>/marvin-support", "helper": "<github login>"}`. This turns on the IT button.
- On a helper install, `instance.json` has `"support": {"watch": ["<owner>/marvin-support", ...]}`. This turns on the Support tab. A helper can watch several installs.

**7. Visibility:** support events (filed, state change, resolved) go into the Activity feed on both installs. A Vitals card shows open requests by state.

## Consequences

- No server and no SSH. Access is one GitHub collaborator grant that the helped person controls.
- Cost:
  - The change detector costs one free 304 per watched repo per tick.
  - Headless sessions start only on `helper-trying`, so they use the subscription only when a request is escalated.
  - The cache is O(open requests).
- The helper only sees what both MARVINs couldn't solve.
- Delivery depends on how engine updates reach an install that has no remote. That's step 3 of ADR 0071 (#646). Until then, the helped side's part has to be installed by hand.
- The labels are a contract between two installs that may run different engine versions. Unknown labels must be ignored, never treated as errors.

## Rejected

- **Polling on a timer, or a background check every N minutes:** this is slow to show changes and goes against "Triggers over polling".
- **GitHub webhooks:** they need a public URL, and the only static tunnel domain belongs to another service.
- **Self-hosted Actions runners:** they need one runner per repo per Mac, and they run whatever the workflow file says. That's too much power for a support channel.
- **SSH into the helped Mac:** it was removed after the first install on purpose, and the helped person can't audit it.

## Amendment, 2026-10-26: fixes live on the helped Mac, and are proven there

The helper's side only solves. The fix is carried out and checked on the helped person's Mac, and both sides can see that.

- **Every answer names a check.** A check is a command that succeeds once the problem is fixed, such as `gh auth status`.
  - The helper's MARVIN must give one, or its answer isn't valid and the request goes to the person.
  - The helper in person can add one when replying. If neither did, the helped MARVIN proposes one and shows it before running it.
- **Verified, not claimed.** On the helped Mac, `support.py verify --phase before` runs the check, then the fix is applied with the person's yes, then `--phase after` runs the check again.
  - The engine posts the before and after results itself, with output scrubbed, as a verification comment.
  - A passing after-check is the only way a request reaches the new state `support:verified` (closed).
  - A failing after-check sends it back to `support:helper-trying`, with the failed result attached.
  - `solved-here` is kept only so older requests still read. Nothing new sets it.
- **Both sides see the conversation.** The helped install gets its own **Support** tab, the same thread view with sections Replies waiting, In progress and Done.
  - An answered request offers **Apply with MARVIN**, which opens a session that runs the verify steps.
  - **Ask a follow-up** sends the request back to the helper's MARVIN.
  - The IT button stays as the quick way in, and clicking a request opens its thread.
- **Notifications:** the helped person gets a macOS notification when an answer arrives, and the helper gets one when a request reaches `needs-you`.
  - They show the title only. Clicking one opens that thread.
  - A notice fires only on a change seen while the dashboard runs, never for old state found at startup.
- **The helper's Handled list** shows the outcome for each request: verified on their Mac (with the check and its before and after results), answered but not applied yet, or fix failed and back to MARVIN.

## Amendment, 2026-10-26: ideas

The helped person can also send **ideas**: features, skills and better prompts. The IT panel has two modes, *Something's wrong* and *I have an idea*.
- **What an idea is:** an issue labelled `support:idea-new`, with no diagnostics. It's never escalated, has no check, and never counts towards *Needs you*.
- **How it becomes a proposal:** on a helper install, a sync turns each new idea into a **Proposal** (`lib/proposals.py`, MR Review → Proposals; ADR 0068) and moves it to `support:idea-proposal`.
  - The proposal is written by a headless run with no tools. If that run fails, or its output isn't a valid proposal, the idea's own words become a plain proposal, so no idea is lost.
  - A file lock means two triggers make one proposal.
- **The decision stays in Proposals,** and the idea follows it. Each sync derives the outcome from the proposal and tells the helped side once:
  - *ticketed* → `idea-ticket`, with the ticket number
  - the ticket closed as completed → `idea-shipped` (closed)
  - *dismissed*, or the ticket closed as not planned → `idea-dismissed` (closed)
  - The helper's dismiss reason is never sent.
- **No names in public.** A ticket made from a proposal is public, so:
  - a proposal's source reads "a support idea", never a person or account
  - the support repo's owner, the requester's login, and an optional `support.redact` list in the private instance are replaced with "a user"
  - the link from proposal back to idea is kept only on the helper's Mac, in `~/.claude/support/ideas.json`
- **On screen:** both Support tabs get an *Ideas* section. The helped person is notified when an idea becomes a ticket and when it's built.

## Amendment, 2026-10-26: written for the person being helped

The helped person may be new to this. The helper's private instance can describe them with `support.audience`, either one text for every repo or one per repo (for example, "a business student who knows some AI basics but is new to using it hands-on").
- **The helper's MARVIN writes for that reader.** Every answer also carries `check_says`: what its check means in a few plain words. It's scrubbed and capped at 120 characters, and stored in the check marker.
- **The helper's own replies:** **Preview for them** rewrites the reply for that reader, with no tools. Every command, path and code block must come back exactly, none dropped and none added. If anything differs, the rewrite is refused and the helper's own words stay. The helper edits or sends the rewrite (**Send this**), or sends the original (**Send as I wrote it**). Nothing goes out unseen.
- **The helped side's screens use plain words:**
  - The check is shown as "How we'll know it's fixed: …", with the command under it.
  - Results read working / not working, with exit codes and output under *Details*.
  - The fix button is **Fix it with MARVIN**, and diagnostics are labelled "Technical details (sent automatically, no passwords)".
  - Authors show as You, Your helper, or Your helper's MARVIN (automatic).
  - Nobody is told to type commands: their MARVIN explains each step and asks before running it.

## Amendment, 2026-10-26: no forever loop

A failed fix goes back to the helper's MARVIN, but not forever. Before the helper's MARVIN answers, `rounds()` counts what has been tried from the thread itself: its answers, and the fixes whose check then failed on the helped Mac (only the requester's own verifications count). The request goes to `needs-you` without asking the model when:
- **the limit of failed fixes is reached** (default 2). The note lists each check that still failed, so the helper starts with the full picture.
- **the limit of automatic answers is reached** (default 4, follow-ups included), so a chat with the bot can't run on forever.
- **the helper's own fix fails.** Once a person has answered, a failure comes back to that person, not to the bot.

Both limits are in the helper's private instance (`support.limits`), clamped to 1–10. The helped MARVIN tries at most 2 fixes on its own Mac before it escalates.

## Amendment, 2026-10-26: headless on the helped Mac

The helped person uses IT because they don't know the answer. Technical work stays on the helper's side, and the helped Mac is asked for nothing unless it's really needed.
- **Filing goes straight to the helper's MARVIN** (`helper-trying`). Nothing opens on the helped Mac. Working with MARVIN interactively stays available as a button, but it isn't the default.
- **Three kinds of answer:**
  - *explain*: plain words, nothing to run. The person taps **Got it, thanks**, and it closes as Answered.
  - *answer*: a fix, with exact `steps`, a read-only check, and `you_steps` only for what truly needs the person (a password, signing in, a macOS permission).
  - *needs-you*: a hand-over to the helper in person.
- **Steps are an allowlist (`safe_step`).** Every `&&`-joined part must be one command from a short list with per-tool rules: brew install/upgrade/link, npm install/ci, the engine's own scripts, launchctl kickstart, git status/add/commit/pull on the engine, mkdir under the engine, open MARVIN.
  - No sudo, deleting, pipes, redirects, ssh, keychain, signing in, pushing or outside scripts.
  - One unsafe step drops them all, so the fix waits for the person.
- **Automatic fixing (`autorun`) needs the person's opt-in**, `support.auto_apply`, set only on their Mac from their Support tab and switchable off any time. It runs:
  - only the helper's own account's latest fix
  - only once per answer, recorded before it runs
  - only with no `you_steps`
  - in order: the check, then the steps (stopping at the first failure), then the check again. `verify` posts the results.
  - A failure counts toward the no-forever-loop limits.
- **No AI runs on the helped Mac for this, and there's no daemon.** A launchd job (`com.marvin.support-autorun`) runs every 2 minutes and at login: one GitHub read, then it exits. It uses no tokens.
- **Notices:** the helped person hears "MARVIN fixed it for you" when a fix is verified.

## Amendment, 2026-10-26: the helper's reply box

The helper's reply box offers three ways to send, and says what each does:
- **Send to them:** the reply exactly as written, optionally with a check. The helped person is notified.
- **Preview for them:** the rewrite for the reader (the audience amendment), checked by the helper before it goes.
- **Have MARVIN fix it with this:** the helper's note goes to their own MARVIN as **guidance** (`guide`, a `marvin:guidance` marker).
  - It's posted on the request, so both sides see it, labelled "You, to your MARVIN" and "Your helper's note to MARVIN".
  - The request goes back to `helper-trying`, and the loop limits count from that note, so MARVIN gets a fresh 2 fixes.
  - The note leads the prompt as GUIDANCE FROM THE HELPER. Guidance from the requester's account isn't guidance.
- A crash while making an attempt still hands the request over, but it's now written to the log, because a silent fallback had hidden a prompt-building bug.

## Amendment, 2026-10-26: act on standing decisions

The helper's MARVIN handed back requests whose answers the helper had already decided ("a judgement call"), and it trusted a misleading health card over the evidence in the request. Now:
- The private instance file `support-decisions.md` (capped at 4000 characters) leads the prompt as STANDING DECISIONS.
- The rule changed: solve it whenever possible. What the decisions settle isn't a judgement call. Check facts in the code and the request before relying on a health card. Hand over only for the helper's own accounts or credentials, money, or an irreversible choice no decision covers. A step that needs the person (a deletion, a sign-in) is a you_step, not a hand-over.
