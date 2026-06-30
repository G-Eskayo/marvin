# marvin-bench

Objective comparison of **base Claude Code** vs the **MARVIN-optimized setup**
(CLAUDE.md + skills + memory + hooks) on identical tasks.

## Why

We keep tuning the agent system but have no baseline. This harness turns "are the
optimizations helping?" into numbers across four metrics:

| Metric | Source |
|---|---|
| Token / context cost | `usage` block (input + output + cache create/read) and `total_cost_usd` |
| Turn / tool efficiency | `num_turns`, count of `tool_use` events |
| Task correctness | rubric: `expect[]` substrings in result text + changed files (v0); LLM-judge later |
| Memory / recall quality | recall tasks whose answer lives only in MARVIN's memory |

## Isolation

Two profiles, selected via `CLAUDE_CONFIG_DIR`:

- **clean** — base Claude Code. Auth (from keychain) + account marker only. No
  CLAUDE.md, skills, hooks, or memory. The control.
- **marvin** — the live `~/.claude` setup, used as-is. The treatment.

Credentials are materialized from the macOS keychain at setup time and never
committed (see `.gitignore`).

## Run

```bash
profiles/setup.sh                       # build the clean profile from keychain
python3 bench.py tasks/task-002-recall  # one task, both profiles
python3 bench.py tasks/*                # whole suite
```

Results print a comparison table and save to `results/<task>-<stamp>.json`.

## Task format

```
tasks/<id>/
  task.json    # {id, type: "fs"|"qa", expect[], cwd?, timeout?}
  prompt.md
  files/       # (fs tasks) seeded into an isolated temp workdir
```

- **fs** tasks run in an isolated temp dir with `--permission-mode bypassPermissions`.
- **qa** tasks run in a fixed `cwd` (default home) so MARVIN's project-scoped
  memory engages; the clean profile loads no memory regardless.

## Known limitations (v0)

- Correctness is substring-based. Add `"judge": true` + an LLM-judge pass for
  semantic grading.
- Single run per task; no variance/repeat averaging yet.
- The marvin profile mutates as you tune it — pin a snapshot for regression runs.
