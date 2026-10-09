# Decisions: asking the owner to choose

**Rule (owner, 2026-10-09):** if a PR or ticket needs the owner to choose something, it gives him the options to
answer, and it can't be approved until the required ones are answered. Asking in prose ("A, B or C?", a "Choose" or
"Open questions" heading, a checklist item ending in "?") is **too vague**: the dashboard shows *Too vague: needs
options*, hides Approve, and the merge server refuses it (`DECISIONS_UNSTRUCTURED`).

Put every question the owner must answer in one **Decisions** section:

```markdown
## Decisions
<!-- marvin:decisions -->
### dance: Which launch animation?
- [ ] A: Clap & wiggle
- [ ] B: Balance a bubble
- [ ] C: Belly slide & wave

### handoff: Hand-off into the start screen
- [ ] Glide
- [ ] Dive

### mix: Mix parts of several? (pick any) (optional)
- [ ] A's clap
- [ ] B's bubble

### character: Any changes to the character? (text) (optional)
```

- The `<!-- marvin:decisions -->` line marks the section. It runs until the next `#` or `##` heading.
- Each question is `### <id>: <question>`. The id is lowercase letters, digits, `-` or `_`, and unique.
- Options are task-list items (`- [ ]`), at least two per choice question. Make each option self-explanatory, and put
  any image it refers to above the section (the PR detail shows images first).
- Flags go at the end of the question line:
  - none: **one** answer, **required**.
  - `(pick any)`: several answers allowed.
  - `(text)`: a written answer, with no options.
  - `(optional)`: not required for approval.
- Don't answer the questions yourself, and don't pre-tick a box unless it records an answer the owner already gave.

## How it's answered

In the dashboard's PR detail (or ticket page), the section shows as big option buttons, a note box per question and
text boxes for `(text)` questions. **Submit decisions** writes the answers into the description itself:

- the chosen boxes are ticked (`- [x]`)
- `> **Answer:** ...` goes under a `(text)` question and `> **Note:** ...` under any question with a note

Then a *Decisions from the owner* comment is posted as the record, with the answers in a `marvin-decisions` JSON block.
The description is the source of truth: the card, the merge gate and GitHub all read it.

- **PRs:** Approve stays disabled (*Answer the decisions first*), and the merge server refuses (`DECISIONS_PENDING`),
  until every required question is answered.
- **Tickets:** a ticket labelled `needs-info` with a Decisions section moves to `ready-for-agent` once every required
  question is answered.

Code: `dashboard/webhook-server/decisions.js` (parser, pure), `decisions_gate.js` (merge-server check),
`dashboard/electron/main/decisions_submit.js` (submit), `dashboard/src/components/Decisions.jsx` (the form).
