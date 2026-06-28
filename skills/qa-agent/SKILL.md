---
name: qa-agent
description: QA code agent — scans projects and captures session learnings into a searchable best-practices ChromaDB. Builds knowledge of libraries, tools, patterns, what worked/failed. Run on any project; query anytime.
tags: [intent:qa, intent:review, intent:knowledge, intent:scan, type:agent]
calls: [self-improve]
---

# QA Code Agent

Builds and queries a searchable knowledge base of best practices, library patterns,
tools, and session learnings. Storage: ChromaDB `qa-knowledge` collection at
`~/.claude/chroma/`.

## Triggers
- "qa", "scan project", "code quality", "best practices for X"
- "what worked", "what failed", "patterns in this codebase"
- Starting a new project (query first for relevant prior practices)
- End of a significant code session (auto-capture learnings)

---

## Commands

### 1 — Scan a project (auto-extract patterns)
```
~/.agents/venv/bin/python ~/.agents/skills/qa-agent/scripts/qa_scan.py /path/to/project
```
Extracts: stack, dependencies, imports, TODO/FIXME/HACK markers, config files.
Each finding stored as a ChromaDB entry with metadata.

### 2 — Query the knowledge base
```
~/.agents/venv/bin/python ~/.agents/skills/qa-agent/scripts/qa_query.py "chromadb best practices"
~/.agents/venv/bin/python ~/.agents/skills/qa-agent/scripts/qa_query.py "python async" --n 10
~/.agents/venv/bin/python ~/.agents/skills/qa-agent/scripts/qa_query.py "what failed" --category failed
```

### 3 — Capture a pattern manually
```
~/.agents/venv/bin/python ~/.agents/skills/qa-agent/scripts/qa_capture.py \
  --content "Always use PersistentClient for ChromaDB — EphemeralClient loses data on restart" \
  --category anti-pattern \
  --library chromadb \
  --tags "chromadb,persistence"
```

---

## Sub-agent usage
Other skills query the KB inline to enrich their output:

```python
import subprocess, json
result = subprocess.run(
    ["~/.agents/venv/bin/python",
     "~/.agents/skills/qa-agent/scripts/qa_query.py",
     "topic", "--json"],
    capture_output=True, text=True
)
entries = json.loads(result.stdout)
```

---

## Data schema
ChromaDB collection: `qa-knowledge`

| Field | Values |
|---|---|
| document | Natural language description of the pattern/practice |
| category | `pattern` · `anti-pattern` · `library` · `tool` · `worked` · `failed` · `config` |
| source | `project-scan` · `manual` · `session` |
| project | project name or path |
| language | `python` · `javascript` · `all` · etc. |
| library | library name if applicable |
| tags | comma-separated keywords |
| confidence | `high` · `medium` · `low` |
| created_at | ISO timestamp |

---

## Behaviour rules
- Always query the KB before starting a non-trivial task on an unfamiliar library.
- After scanning a project, print a summary: N entries added, top libraries found.
- Dedup: before inserting, check if near-identical content already exists (cosine > 0.95).
- Never store secrets, tokens, or personal data in the KB.
