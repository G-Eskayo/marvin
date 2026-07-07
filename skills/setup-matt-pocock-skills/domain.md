# Domain Docs

Seed template for `docs/agents/domain.md`. Tells the engineering skills where `CONTEXT.md` and
`docs/adr/` live and how to read them.

```markdown
# Domain Docs

**Layout**: [Single-context | Multi-context]

## Single-context (most repos)

- `CONTEXT.md` at the repo root — the domain glossary. Devoid of implementation details; terms
  and their meanings only.
- `docs/adr/` at the repo root — one file per architectural decision, numbered sequentially.

## Multi-context (typically a monorepo)

- `CONTEXT-MAP.md` at the repo root points to each context's own `CONTEXT.md`.
- Each context has its own `docs/adr/` alongside its `CONTEXT.md` — decisions specific to that
  context live there, not at the root.
- System-wide decisions that don't belong to any single context go in a root-level `docs/adr/`.

## Consumer rules

- `improve-codebase-architecture`, `diagnose`, and `tdd` read `CONTEXT.md` for domain vocabulary
  before proposing names for new modules/concepts — a suggestion using a term not in `CONTEXT.md`
  should either match existing language or trigger adding the new term, not invent parallel
  vocabulary.
- These skills read `docs/adr/` for past decisions in the area being touched, and should not
  re-litigate a settled decision without flagging that they're doing so and why.
- If `CONTEXT.md`/`docs/adr/` don't exist yet, that's fine — `grill-with-docs` creates them
  lazily, only when the first term/decision actually resolves. Don't scaffold empty files
  preemptively.
```
