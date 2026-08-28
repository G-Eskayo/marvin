# 0030 — Headless dispatch uses `dontAsk` + an explicit allowlist, not `bypassPermissions`

## Status

Accepted (2026-08-28)

## Context

A live test (ticket #20, dispatched via `dispatch_ticket.sh`) failed completely: every `gh`/`curl`/
`env` call was denied with "This command requires approval," with no one present to grant it.
Root cause, confirmed against Claude Code's actual documented behavior: non-interactive `-p` mode
has no TTY to show a permission prompt, so anything not already pre-authorized hard-denies
immediately rather than hanging. `--permission-mode acceptEdits` (what was used) only auto-approves
file edits plus a few basic filesystem commands (`mkdir`, `rm`, `cp`, `mv`, `sed`) inside the
working directory — not `gh`, not `git commit`/`push`, not general Bash.

Two documented ways to actually authorize a fully unattended session: `--dangerously-skip-permissions`
(`bypassPermissions` — skips essentially everything, including protected-path writes) or
`--permission-mode dontAsk` combined with an explicit `--allowedTools` list (auto-denies anything
*not* listed; everything listed runs without prompting). `bypassPermissions` is documented as
intended for container/VM isolation specifically because it removes guardrails that have nothing
to do with git state — arbitrary file access, arbitrary network calls — none of which would show
up in a PR diff for later review, since it never touches git at all.

Git-worktree isolation ([[project-marvin-cross-machine-sync]]'s "Sandbox isolation" note,
`sandbox_orchestration.py`) was never intended as OS-level sandboxing — it protects repo-state
integrity (can't corrupt `main`, can't lose interactive work, every change gets reviewed before
merge), not system access generally. On the bare host (no container), `bypassPermissions` removes
protection for exactly the part worktree isolation doesn't cover.

## Decision

Headless dispatch (`sandbox_orchestration._default_executor`'s planning and execution calls, and
any other unattended `claude -p` invocation in the pipeline) uses `--permission-mode dontAsk` with
an explicit `--allowedTools` list scoped to what that phase actually needs — not
`bypassPermissions`. Planning: `Read,Grep,Glob,Bash(gh issue view*),Bash(gh issue list*)` (already
correct, just needed `dontAsk` added). Execution: file edit tools plus the test/build commands this
repo already uses — `Bash(git status*)`, `Bash(~/.agents/venv/bin/python -m pytest*)`,
`Bash(npm test*)`, `Bash(npm install*)`, `Bash(npx vitest run*)`. `git commit`/`push`/`gh pr create`
stay out of the allowlist entirely — those happen in `mr_raiser.py` as plain `subprocess.run()`
calls from the orchestrating Python process, not from inside a nested Claude session, so they were
never subject to this wall in the first place (confirmed: `ticket_pipeline.py` itself successfully
ran `gh issue list`/`gh issue edit` when dispatched directly as a plain script).

## Consequences

- A ticket whose build/test process needs a command outside the allowlist hard-denies rather than
  running — the allowlist needs to grow as new kinds of tickets appear; not self-expanding.
- `dispatch_ticket.sh` (the older manual-precedent script, now largely superseded by #95's rewire)
  still uses the unfixed `acceptEdits`-only invocation — not updated by this ADR; a manual dispatch
  through it will hit the same wall #20 did until/unless it's updated too.
- Does not change anything about project-level `.claude/settings.json` (e.g. `~/.agents/.claude/
  settings.json`'s graphify hook-guard) — confirmed those don't apply in `-p` mode without the
  folder being explicitly trusted, which headless dispatch never triggers. Only user-level
  `~/.claude/settings.json`/`settings.local.json` and the per-invocation flags decided here apply.
