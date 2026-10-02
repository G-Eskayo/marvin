---
name: variable-tracker
description: Track Python variable definitions, uses, and scope across files
tags: [domain:code-navigation, intent:analysis, type:skill]
---

# Variable Tracker Skill

Find where a Python variable is defined, where it's used, and what scope it belongs to — without reading the whole file.

## Triggers

Load this skill when you're:
- "track this variable" / "where is X defined/used"
- Starting work on an unfamiliar Python file
- Asking "what's the state of X" — did we mutate it, is it stale?
- Debugging variable shadowing or scope issues

## CLI usage

```bash
# After running install.sh:
track-vars <path> [<path>...]                    # scan file(s) or dir(s)
track-vars <path> --name X                       # find variable X only
track-vars <path> --since HEAD~1                 # only files changed since commit
track-vars <path> --format json                  # JSON output for piping
```

## Output format

Default text output: compact, inline-friendly, meant to paste into conversation:

```
cfg    [module]    lib/config.py    (dict)
  def    L12    cfg = load_config()
  use    L15    return cfg["timeout"]
  use    L30    log_config(cfg)
```

Columns: variable name, scope, file, inferred type (if annotated).  
Each var tracks definitions (assignments, parameters, for/with targets) and uses (loads).

Same variable name in different scopes (e.g., `x` in module vs `x` in `func1()`) tracked separately — shadowing isn't conflated.

JSON output (`--format json`) suitable for tool chaining:

```json
[
  {
    "name": "cfg",
    "scope": "[module]",
    "file": "lib/config.py",
    "definitions": [
      {"line": 12, "kind": "assign", "snippet": "cfg = load_config()"}
    ],
    "uses": [
      {"line": 15, "snippet": "cfg[\"timeout\"]"}
    ]
  }
]
```

## Extraction logic

Python-only (v1). Walks the AST:
- **Definitions**: assignments, annotated assignments, augmented assignments (+=), for/with targets, function parameters, global/nonlocal declarations
- **Uses**: Name nodes in Load context (reading a var)
- **Scope**: module-level or function name; same var in different scopes tracked as separate records

Type annotations from `x: int = 10` are captured.

## Filters

- `--name X`: return only variable X across all scanned files/scopes
- `--since <git-ref>`: restrict scan to files changed since `<ref>` (via `git diff --name-only`)

## Directory traversal

Recursively scans `.py` files; skips `venv`, `node_modules`, `.git`, `__pycache__`, `.venv`.

## Install

```bash
bash ~/.agents/skills/variable-tracker/install.sh
source ~/.zshrc
```

Then use `track-vars` from anywhere in the repo.
