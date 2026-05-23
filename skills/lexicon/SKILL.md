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

## Reviewing

When asked to review the lexicon: read `~/.claude/lexicon.md`, flag any entries that have drifted, become unused, or contradict each other. Propose updates.

## Sections

Current sections in lexicon.md:
- **Meta** — terms about the skill/agent system itself
- Add new sections as concepts cluster into domains
