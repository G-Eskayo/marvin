---
name: lexicon
description: Add, update, or review entries in the shared lexicon at ~/.claude/lexicon.md. Run autonomously when a new concept crystallises, a term is used repeatedly with consistent meaning, or an image/metaphor is coined that compresses shared understanding. Also run when user says "add that to the lexicon", "remember that term", or "let's define that".
tags: [domain:language, intent:define, intent:vocabulary, intent:document, type:skill]
---

# Lexicon

Shared vocabulary between Giles and Claude. Compressed mental models.

## When to Run Autonomously

- New concept coined mid-conversation that will recur
- Term used 2+ times with stable meaning → worth formalising
- Image or metaphor that captures something complex in few words
- Existing entry is wrong or needs sharpening based on usage

## Adding an Entry

Edit `~/.claude/lexicon.md`. Append under the most relevant section heading, or create a new section if concept belongs to a new domain.

Format:
```
- **term** — definition. Image or usage context if helpful.
```

Rules:
- Definition = shortest accurate statement
- Include the *image* if the term works visually (a metaphor, a shape, a dynamic)
- No synonyms for existing terms — update the existing entry instead
- If a term shifts meaning, update + note the shift
- Only words MARVIN and Gil use with a meaning of their own. A general glossary of someone else's field (MCP, OAuth, ...)
  goes in `~/.agents/best-practices/<topic>-glossary.md`, with a line under **Elsewhere** pointing at it
- The whole lexicon is pasted into every session, capped at 2,500 characters (`LEXICON_MAX` in
  `lib/session_start_report.py`, PR #1124). Past that the tail is cut, so keep entries short

## Reviewing

When asked to review the lexicon: read `~/.claude/lexicon.md`, flag any entries that have drifted, become unused, or contradict each other. Propose updates.

## Sections

Current sections in lexicon.md:
- **Meta** — terms about the skill/agent system itself
- **Elsewhere** — pointers to glossaries kept outside the lexicon (MCP: `~/.agents/best-practices/mcp-glossary.md`)
- **Added terms** — new terms land here until they cluster into a section
- Add new sections as concepts cluster into domains
