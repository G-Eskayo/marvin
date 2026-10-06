# A ticket for the owner says exactly what to do

A ticket labelled `ready-for-human` is handed to a person, so it must not make them ask what it wants. Its body has a `## Your task`
section with four bold fields, each non-empty:

```markdown
## Your task
**What I need from you:** the single thing, in one sentence ("the list of speech languages your iPhone supports").
**Where:** the exact place: which device, which app and screen, which file or URL, which command and in which folder.
**How:** numbered steps a person can follow without knowing the codebase. Include what you should see at each step, and what to do if it
does not appear.
**What to send back:** the exact form of the answer ("paste the copied text as a reply on this ticket"; "a yes or no and the language
you picked"; "the file at ~/...").
```

Why each field exists:

- **What I need** stops the ticket being a vague "confirm X".
- **Where** and **How** stop the owner having to ask for the steps. If a step needs code to exist first (a screen that shows the
  list), that code is a separate ticket for the agent, and this ticket is blocked by it: a task is only the owner's once it is
  doable without writing code.
- **What to send back** makes the answer something the dashboard's Reply box can take and the next ticket can use.

The rule is enforced in two places:

- `lib/ticket_policy.py` (`human_task_gaps`): triage will not label a ticket `ready-for-human` without all four fields; it goes to
  `needs-info` and says which are missing.
- The dashboard's ticket view (`src/lib/human_task.js`): shows the task up front, or says in red that the ticket does not explain
  itself.

Answering: use the Reply box on the ticket (ADR 0037).
