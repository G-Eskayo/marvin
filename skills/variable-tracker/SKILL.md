---
name: variable-tracker
description: Dev tool — tracks variable declarations and uses in active files, surfaces state mid-session. Works on Python (precise AST) and text files (approximate regex). Inline output for quick context-grabbing.
tags: [intent:debug, intent:dev-tool, type:utility, dev-mode:mid-session]
---

# Variable Tracker

A dev-session utility for tracking variable declarations, assignments, and uses within the file(s) you're actively working on. Solves the "lost track of what X is set to" problem mid-refactor or in long branchy coding sessions.

## Triggers
- "track variables", "what's X set to", "lost track of state"
- Long or branchy coding sessions where state mutates across multiple scopes
- Narrowing down where a variable gets reassigned or shadowed

---

## How to Use

### Quick start (inline during coding)

```bash
~/.agents/venv/bin/python ~/.agents/skills/variable-tracker/scripts/track_vars.py <file-path>
```

Outputs a compact, scope-grouped table — copy/paste directly into your next response:

```
## module scope

- **count** (int, declared L2) → used: L5, L8
- **unused_var** (unknown, declared L3) → unused
```

### Filter to one variable

```bash
~/.agents/venv/bin/python ~/.agents/skills/variable-tracker/scripts/track_vars.py <file-path> --var name
```

When you only care about tracking a single piece of state, use `--var` to focus the output:

```
## module scope

- **name** (str, declared L1) → used: L4, L7, L12
```

### JSON output (structured consumption)

```bash
~/.agents/venv/bin/python ~/.agents/skills/variable-tracker/scripts/track_vars.py <file-path> --json
```

For programmatic use or piping:

```json
{
  "module": {
    "count": {
      "declared_line": 2,
      "type": "int",
      "uses": [5, 8]
    }
  }
}
```

### Multiple files

```bash
~/.agents/venv/bin/python ~/.agents/skills/variable-tracker/scripts/track_vars.py file1.py file2.py --json
```

Track variables across multiple files at once.

---

## What It Detects

### Python files (`.py`) — Precise via AST

- **Declarations:** `x = ...`, `x: int = ...`, `x += ...`, `for x in ...`, `with ... as x`, function parameters `def foo(x):`
- **Uses:** every name load in expressions, function calls, etc.
- **Scopes:** module-level and per-function (shows when a local `x` shadows a module-level `x`)
- **Types:** infers from annotations (`x: int`) when present, falls back to `unknown`

### Non-Python text files (`.js`, `.ts`, `.tsx`, `.jsx`, etc.) — Approximate via regex

- **Declarations:** `const x = ...`, `let x = ...`, `var x = ...` (declaration only, no type inference)
- **Uses:** word-boundary scans for the variable name (prone to false positives; marked "regex-detected")
- **Limitation:** no scope awareness — treats entire file as one scope

**Trust the Python output completely; treat text-file output as a search hint, not ground truth.**

---

## Integration in a Session

When you're mid-refactor or debugging state flow:

1. Call the tracker on your active file(s)
2. Paste the compact table directly into your next Claude prompt
3. Reference specific use-sites by line number when asking for clarification

Example:
```
The count variable gets declared at L2, but I'm seeing issues at uses L5 and L8.
Can you trace why the value is different there?

## module scope
- **count** (int, declared L2) → used: L5, L8
```

This gives Claude immediate context without hunting through source code.

---

## Output Format

### Compact table (default)

```
**module scope**

- **name** (type, declared L5) → used: L7, L10, L15
- **unused** (unknown, declared L3) → unused
```

Sorted by declaration order, scope-grouped. One line per variable. Copy/paste directly into a response.

### JSON

Full structured data:

```json
{
  "file.py": {
    "module": {
      "var_name": {
        "declared_line": 1,
        "type": "str",
        "uses": [3, 5, 7]
      }
    },
    "function:main:10": {
      "local_var": {
        "declared_line": 11,
        "type": "unknown",
        "uses": []
      }
    }
  }
}
```

Each scope is keyed as `module` or `function:<name>:<lineno>`.

---

## Limitations and Notes

- **Python precision:** Tracks *names*, not values — doesn't evaluate `x = 5 + foo()`; marks both `5` and `foo` as uses of external names.
- **Text-file regex:** No AST, so can't distinguish declarations from uses correctly, and can't see scopes. Treat as a preliminary hint; verify in code.
- **Scope definition:** "session" in the acceptance criteria means the file(s) currently being edited, not raw `.jsonl` session transcripts (parsing those for state would require privacy-sensitive transcript inspection and is out of scope).
- **No value tracking:** This tool shows *where* variables are declared and used, not *what* they contain. Use `print()` or a debugger for runtime state.

---

## Why This Exists

Mid-session debugging often requires quick context-gathering: "What scopes does this variable exist in? Where was it last written? Is it used after that write?" Rather than asking Claude to read the whole file and manually trace, this tool surfaces that information instantly and in a copy-paste-friendly format.
