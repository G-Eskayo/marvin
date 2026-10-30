# MR Review: answers are the approval (mock-up, marvin#924)

**Status: mock-up for the owner's sign-off.** The real dashboard (`dashboard/src`) is unchanged. Once the look is
signed off, it gets built into `Decisions.jsx`, `prState.js` and the merge path.

A PR that asks for Decisions gets **one button, named by the answers**, instead of Submit decisions and then
Approve & Merge:

| Answers | Button | What happens |
|---|---|---|
| All match what's built | **Merge with these answers** | Saves them and merges in one press, then the merged line and the blue sweep |
| Any one differs from what's built, or a note is typed | **Send back with answers** | Saved; MARVIN rebuilds; the PR comes back as a normal review |
| Mock-up or plan PR (nothing to merge) | **Send answers** | Saved; the card reads like a ballot |
| A required one unanswered (nothing built, nothing picked) | **Answer N more** (off) | Nothing until it's answered |
| Old-format PR (no "built here" markers) | **Submit decisions**, then **Approve & Merge** | Today's two steps |

## Open it

Open `index.html` in Chrome straight from Finder (no server, no build, no libraries). Pick a scene at the top, and
switch Dark or Light. A scene can be linked: `index.html#scene=b&theme=light`. Everything is clickable: pick options,
add a note, type in it, and the button changes as you go. It works narrow (below 900 px) and at phone width.

| Scene | What it shows |
|---|---|
| a | Code done, every answer is what was built: one press merges. A dashed "Mock" link makes the next merge fail, to show the answers stay saved and the merge can be tried again |
| b | Gil picks Dive instead of the Glide that was built: Send back, and the line says what differs |
| c | Every answer matches but a note is typed: Send back, with the reason. A note of only spaces doesn't count |
| d | A mock-up PR: the ballot, Send answers |
| e | A required question with nothing built for it: the button is off, "Answer 1 more" |
| f | An old-format PR: today's two steps |

The dashed controls and the caption line at the top are notes for whoever looks at the mock-up, not dashboard UI.

## How it's made

- `answer_state.js` is the whole rule, with no DOM: `answerState({ decisions, picks, notes, plan, status, failure })`
  returns `{ label, action, reason, missing, picks, unsent, busy }`, where `action` is `merge`, `send-back`, `send`,
  `disabled` or `two-step`. The page calls it on every click, so the mock-up shows exactly what is tested. It is a
  classic script that sets `globalThis.AnswerState`, so it opens from Finder and vitest can import it.
- Tests that try to break it: `dashboard/test/answers_are_approval_proto.test.js` (no markers, a note, a note of only
  spaces, pick-any in any order, optional left empty, all required answered with a choice that isn't built, a plan
  with a stray marker, pressing twice, a merge that fails after the answers saved).
- Rules it follows that the ticket didn't spell out (each is a question below): an untouched question counts as what's
  built; an emptied optional question is no answer, so it changes nothing; answering a question nothing was built for,
  or writing a text answer, is a send back; a pick-one question marked "built here" twice falls back to two steps.
- The merge confirmation borrows the #838 look: one solid brand-blue band (`#198fd9`, with the site's halo) crosses the
  card left to right, then the existing "✓ Merged into main at … by you" line. Reduce Motion skips the band.
- The light theme shows how it would read if the dashboard gets one; the app is dark only today.

## Decisions
<!-- marvin:decisions -->
### label-merge: The button when every answer matches what's built
- [ ] Merge with these answers
- [ ] Merge with my answers
- [ ] Answer and merge

### label-send-back: The button when an answer differs or a note is typed
- [ ] Send back with answers
- [ ] Send back to rebuild
- [ ] Send my answers back

### label-send: The button on a mock-up or plan PR
- [ ] Send answers
- [ ] Send my answers
- [ ] Submit ballot

### label-disabled: The button while a required one is unanswered
- [ ] Answer N more (for example "Answer 1 more")
- [ ] N left to answer
- [ ] Answer the decisions first

### not-yet-sent: How a pre-selected built option shows before it's sent
- [ ] Dashed green outline, lighter fill, and the words "Built here · not yet sent" (solid once sent or picked by you)
- [ ] Solid green like a pick, with only the words "not yet sent"
- [ ] Grey outline with a small "built" dot, no tick, until you pick it

### built-tag: Mark which option was built on options that aren't picked
- [ ] Yes: a small "Built here" under the option, picked or not (as in scene b's Glide)
- [ ] Only on the option while it's pre-selected

### reason-line: The line beside the button that says why it's named that
- [ ] One plain sentence naming the question and the answers (for example: You picked “Dive” for “Hand-off into the start screen”; what's built is “Glide”. MARVIN rebuilds it.)
- [ ] A short tag only, like "1 change" or "1 note"
- [ ] No line: the button's name is enough

### button-colours: The colour of each button
- [ ] Merge blue (like Approve & Merge today), Send back amber outline, Send answers green (like Submit decisions today), off grey
- [ ] All green, like Submit decisions today

### ballot-look: How a mock-up or plan PR's card looks
- [ ] A ballot: titled "Ballot" with a "Mock-up · nothing to merge" tag, numbered questions ("1 of 3"), one option per row with a round mark (square for pick any), one wide button, and the evidence sections hidden
- [ ] The same card as a code PR, only the button differs
- [ ] A ballot, but keep the Images, Test Results and other sections below it

### header-line: What the top right of the PR says, now Approve & Merge is gone from there
- [ ] "Your answers decide it" with "The button under the Decisions names what happens.", and Deny stays
- [ ] Keep an Approve & Merge button at the top too, doing the same as the one button
- [ ] Nothing but Deny

### merge-failed: When the answers saved but the merge failed
- [ ] The line says "Your answers are saved. The merge failed: (why)." and the button reads "Try the merge again"
- [ ] Show today's "The last merge attempt failed" at the top, and keep "Merge with these answers" as the button

### unbuilt-answer: Answering a question that nothing was built for (on a code PR)
- [ ] Send back: MARVIN builds that answer first (scene e after a pick)
- [ ] Merge anyway, and file the answer as a follow-up ticket

### text-answer: A written answer to a "(text)" question on a code PR
- [ ] Send back, the same as a note: MARVIN reads it first
- [ ] Merge, and pass the written answer on as a follow-up

### markers: How the description marks "built here" and a mock-up or plan PR
- [ ] "(built here)" at the end of the option line, and "<!-- marvin:decisions plan -->" in place of the usual marker line for a mock-up or plan
- [ ] "[built]" at the start of the option line, and a "(plan)" flag on the Decisions heading
