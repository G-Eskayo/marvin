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
| Task correctness | v0: `expect[]` substring matching (always); v1: LLM judge via `--judge` (semantic) |
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
profiles/setup.sh                             # build the clean profile from keychain
python3 bench.py tasks/task-002-recall        # one task, both profiles
python3 bench.py tasks/*                      # whole suite
python3 bench.py tasks/* --repeat 5          # 5 runs each; table shows mean ± σ
python3 bench.py tasks/* --judge             # LLM semantic grading alongside substring
python3 bench.py tasks/* --repeat 3 --judge  # both
python3 bench.py tasks/* --profiles clean,marvin  # specific profiles only
```

Cost validation (marvin#645, Run 31 in RESULTS.md):

```bash
bash cost_validation.sh                       # the whole comparison, N=3, judged, budget-stopped
python3 bench.py tasks/task-004-caveman --profiles marvin --prompt-prefix "Caveman mode. " --tag caveman
python3 bench.py tasks/* --stop-above 0.75   # stop before a task once plan usage passes 75%
~/.agents/venv/bin/python cost_report.py results/<dir> --base clean --treat marvin   # $ per successful task
```

A task.json `"check": {"files": "check"}` names hidden pytest files that are copied into the
workdir after the run, so a coding task is graded by whether the code works, not by a substring.
Run bench.py with `~/.agents/venv/bin/python` so the hidden checks have pytest.

Working folders (PR #1125): by default each (task, cell) gets one stable folder under the temp area
(`$TMPDIR/marvin-bench-work/<task>--<profile>--<model>[--<prefix hash>]`), emptied before and after every
run, with that folder's Claude Code auto memory cleared, as a person working in one repo has. Under Claude
Code 2.1.318 a fresh folder per run made plain Claude Code rewrite its whole prompt every run, which flattered
MARVIN. `--workdir fresh` restores the old one-temp-folder-per-run behaviour (Run 31 and before); each run's
JSON records `workdir_mode`, so results from the two modes are never pooled by mistake.

Results print a comparison table and save to `results/<task>-<stamp>.json`.
`--repeat N` saves all N raw runs to JSON; the table shows mean ± σ across them.
`--judge` calls claude as an LLM judge after each run; failing runs print the
judge's rationale inline. Both substring and judge scores are shown side by side.

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

## Known limitations

- Substring grading (v0) is always active. LLM-judge grading (v1) is opt-in via `--judge`.
- The marvin profile mutates as you tune it — pin a snapshot for regression runs.
- No hard/ambiguous tasks yet — all current tasks score 1.00 across all profiles on
  correctness. Need tasks where clean fails to show when MARVIN earns its overhead.
