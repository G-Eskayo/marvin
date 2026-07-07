# CONTEXT.md Format

A domain glossary — nothing else. No implementation details, no architecture, no decisions
(those go in `docs/adr/`, see [ADR-FORMAT.md](./ADR-FORMAT.md)).

```markdown
# [Project Name] — Context Glossary

Domain terms only. No implementation details — see `docs/adr/` for decisions and rationale.

## [Optional section grouping, if terms cluster naturally]

- **Term**: plain-English definition, in the project's own language — not a dictionary
  definition, but what this term specifically means *here*, including any distinctions that
  matter (e.g. "X is not the same as Y — X refers to ..., Y refers to ...").
```

Create the file lazily — only when the first term actually resolves during a grilling session,
not upfront. Update it inline as terms crystallize during the conversation; don't batch updates
to the end.

If the project has multiple bounded contexts (rare), a root `CONTEXT-MAP.md` points to each
context's own `CONTEXT.md` — see SKILL.md's "File structure" section for that layout. Default to
a single `CONTEXT.md` unless the project has already split into multiple genuinely separate
contexts.
