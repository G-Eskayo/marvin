# README templates by kind of project

Each template is an order of sections, with what to *show* in each. Delete a section that has nothing true to say; do not
fill it with filler.

## Common header (all kinds)

```markdown
# Name

One sentence: what it is, for whom, and why they would want it. (<= ~120 characters, plain words.)

<picture or screenshot / diagram: the single most convincing visual. Alt text says what it shows.>

**Status:** stable | in use | experimental | planned. One line on what works and what does not yet.
```

## App (desktop, iOS, web)

1. Header (screenshot of the main screen above the fold)
2. **What it does**: 3-5 bullets, each with the user's benefit, not the feature name
3. **See it work**: 2-3 screenshots or a short recording, each with one sentence on what to notice
4. **Install / run**: exact commands or the download link; requirements
5. **How it works**: one architecture diagram (Mermaid) and a paragraph
6. **Docs** (links), **Roadmap/status**, **Contributing**, **License**

## Library or CLI

1. Header
2. **Install**
3. **Usage**: the smallest real example *with its actual output*
4. **More examples** (link to `examples/`), **API** (link)
5. **Contributing**, **License**

## Claude Code skill or agent tooling

1. Header (a short real transcript is the visual)
2. **What it does for you**: the situations it triggers in, in plain words
3. **Install** (the exact path or command), **Use** (example prompts and what comes back)
4. **How it works** (diagram of the steps), **What it touches** (files, network, permissions), **Limits**
5. **Contributing**, **License**

## Research or coursework project

1. Header (the figure that carries the result)
2. **The question** and why it matters (two sentences)
3. **Method**: a diagram of the pipeline, not a paragraph
4. **Result**: the chart / table, with one line on what it means; the report link
5. **Reproduce**: environment, data source, the commands, expected runtime and output
6. **License**, **Citation** if relevant

## Infrastructure or system (MARVIN-like)

1. Header (architecture diagram)
2. **The problem it solves** (what hurt before)
3. **Quickstart on a clean machine** (every command run and verified)
4. **Architecture**: components, data flow, what runs where
5. **Docs map**: CONTEXT.md, the ADR index, per-subsystem docs
6. **Status**: what is built, what is deliberately not, what is next
7. **Operating it**: health, logs, how it fails and recovers
8. **Contributing**, **License**
