# Triage Labels

The `triage` skill moves an issue through five canonical roles. Each maps to a real label on
this repo (created 2026-08-19, `setup-matt-pocock-skills` first run) — no overrides from the
default naming. Colours are auto-created by `project_onboard apply` (ticket #146) and should
not be manually changed.

| Canonical role    | This repo's label | Colour   | Meaning                                          |
|--------------------|--------------------|----------|---------------------------------------------------|
| `needs-triage`    | `needs-triage`     | #d4c5f9  | Maintainer needs to evaluate                       |
| `needs-info`      | `needs-info`       | #ffd700  | Waiting on reporter for more detail                |
| `ready-for-agent` | `ready-for-agent`  | #90ee90  | Fully specified — an AFK agent can pick this up with no further human context |
| `ready-for-human` | `ready-for-human`  | #ffb6c1  | Needs human implementation, not agent-suitable     |
| `wontfix`         | `wontfix`          | #808080  | Will not be actioned                               |

## Consumer rules

- `triage` only ever applies one of these five — if a case doesn't clearly fit one, that's a sign
  the issue needs more information (`needs-info`), not a reason to invent a sixth label.
- `ready-for-agent` specifically means "no further human context needed" — don't apply it to an
  issue that's well-written but still assumes tribal knowledge only a human maintainer has.
- `ready-for-human` specifically means the ticket tells the person exactly what to do: a `## Your task` section with what is needed, where,
  how, and what to send back (`human-task-template.md`). Triage enforces it; a person-ticket without it is `needs-info`.
- Category roles (`bug` / `enhancement`) already exist as GitHub's stock labels on this repo —
  use those as-is, don't create duplicates.
