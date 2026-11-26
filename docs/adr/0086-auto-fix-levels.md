# 0086 — Auto-fix levels: safe loops fix themselves with two-failure downgrade

## Status

Accepted (2026-11-25). Design: `lib/loops.py` and ADR 0083 integration. Builds on [[0083]] (loop registry and fixes).

## Context

Some loops can fix themselves safely with no manual intervention: rebuilding the code graph after a commit, or refreshing the project catalog. Currently, every loop with a manual fix requires human action from the Vitals Loops panel. This added friction and left safe fixes undone while the owner was busy.

The loop registry (ADR 0083) already has a `fix.level` field (`auto`, `one_tap`, `decision`). This ADR uses it.

## Decision

1. **Auto-fix level.** A `fix` with `level: "auto"` runs automatically when the loop is broken, without requiring a button click. Only safe, idempotent, low-cost operations are allowed: `rebuild_graph` and `refresh_catalog`.

2. **Auto-safe allowlist.** Only `rebuild_graph` and `refresh_catalog` kinds may have `level: "auto"`. All other kinds reject it as a registry problem. The allowlist is enforced at load time, never at runtime.

3. **Per-kind timeouts.** Each fix kind has its own timeout: `rebuild_graph` runs for up to 20 minutes (1200 s), `refresh_catalog` for up to 5 minutes (300 s). The registry doesn't specify timeouts; they're in a constant in `lib/loops.py`. The timeout is passed through `run_fix` to the subprocess call.

4. **Two-failure downgrade.** An auto-fix that fails is retried once. After two consecutive failures, it downgrades to `one_tap` (manual button, like `decision` downgrades after the owner doesn't answer). The dashboard shows the loop as "downgraded" with both failure reasons displayed. Downgraded loops stay one-tap until they succeed, at which point the downgrade is cleared.

5. **Required undo reason.** Every auto-level fix must include an `undo` key: a one-line string explaining why a human should intervene if the auto-fix downgrades. This is shown in the loop registry for transparency. Non-auto fixes reject any `undo` key as a registry problem.

6. **Automatic trigger.** `run_due_auto_fixes()` runs in `health_checks._cli()` right after `write_status()`, alongside the alert and disk-first-aid steps. It evaluates every loop and fixes each broken auto-level one, then re-measures via a fresh `status()` read to record the outcome.

7. **Per-machine attempt-state.** Each machine tracks auto-fix attempts in `~/.claude/auto-fix-state.json`: `{loop_id: {attempts: int, reasons: [str, str], downgraded_at: iso}}`. This is not synced (each machine manages its own attempts). The dashboard overlays this state onto status rows, showing the effective `fix.level` and the two most recent failure reasons.

## Consequences

- Loops that can fix themselves fix themselves, no manager required.
- Two consecutive failures trigger a manual review (downgrade), respecting that some problems aren't safe to retry.
- The registry is more explicit: every auto-level fix documents why a human needs to step in if it fails.
- The IPC between dashboard and electron does not need to change. `loops:status` already includes the full row; overlay is computed in `status()`.
- The dashboard shows downgraded loops with their failure reasons, so the owner knows why a normally-automatic fix needs manual attention.

## History

- 2026-11-25: Planned and implemented as the loop-kernel auto-fix tier (marvin #1123).
