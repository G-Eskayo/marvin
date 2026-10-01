# Task 018: Isolated-Memory QA

This task verifies that:
1. An isolated temp workdir prevents reading the answer from disk
2. File-read tool denials (via `disallow_tools`) enforce knowledge-base-only access
3. Clean/lean profiles cannot discover or call the qa-knowledge query tool
4. Only MARVIN can answer by querying the live ChromaDB

## Setup

Before running this task, seed the knowledge base:

```bash
bash bench/tasks/task-018-isolated-memory-qa/setup.sh
```

This adds a single fact to `~/.claude/chroma/qa-knowledge`:
> "The agent balancing problem is when an instruction-following model becomes overly constrained by guideline friction"

This fact is **not** present in:
- Any CLAUDE.md file
- Any SKILL.md file  
- Any MEMORY.md file
- RESULTS.md or SCORECARD.md (bench output)
- The prompt.md in this task directory

It exists **only** in the ChromaDB, reachable via `qa_query.py`.

## Run

```bash
python3 bench.py tasks/task-018-isolated-memory-qa --judge
# Or with all profiles:
python3 bench.py tasks/task-018-isolated-memory-qa --profiles clean,lean,marvin --judge
```

## Expected Results

### Clean Profile
- **Score: 0.00** — cannot query ChromaDB, no qa-agent skill
- **Tool calls**: no Bash calls to qa_query.py; possibly Read/Glob/Grep denied at CLI
- **Behavior**: answers from training data about instruction-following tradeoffs but cannot reproduce the exact stored phrase

### Lean Profile  
- **Score: 0.00** — no qa-agent skill in ~/.claude-lean/skills/
- **Tool calls**: no Bash calls to qa_query.py
- **Behavior**: answers from training data only; never discovers qa_query.py exists

### MARVIN Profile
- **Score: 1.00** — qa-agent skill triggers on "query the knowledge base", executes qa_query.py, retrieves exact phrase
- **Tool calls**: visible Bash invocation of `~/.agents/skills/qa-agent/scripts/qa_query.py`
- **Behavior**: queries ChromaDB, retrieves and includes the exact stored phrase

## Isolation Mechanisms

1. **Temp workdir**: files/ contains only decoy files (README.txt, fake_answer.txt)
2. **disallow_tools**: Read/Glob/Grep denied at CLI (`--disallowedTools`)
3. **Bash allowlist** (clean/lean): only pre-approves the literal qa_query.py call; anything else auto-denies in headless mode
4. **No static context**: the answer phrase does not appear anywhere in static docs marvin loads

## Verification Script

After running, verify results manually:

```python
# Check that clean/lean did not call Read/Glob/Grep
import json
results = json.load(open('results/task-018-isolated-memory-qa-*.json'))
for profile in ['clean', 'lean']:
    # Transcript should not contain Read/Glob/Grep tool use
    pass
# Check that marvin called qa_query.py and scored 1.0
# marvin's transcript should show: Bash tool call to qa_query.py
```

Or use the judge output (pass `--judge` above):
```
task-018-isolated-memory-qa | clean | 0.00 | marvin | 1.00
```

Judge's rationale will explain whether clean/lean lack KB access or the phrase was not reproduced.
