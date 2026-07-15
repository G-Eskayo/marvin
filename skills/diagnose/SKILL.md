---
name: diagnose
description: Disciplined diagnosis loop for hard bugs and performance regressions. Reproduce → minimise → hypothesise → instrument → fix → regression-test. Use when user says "diagnose this" / "debug this", reports a bug, says something is broken/throwing/failing, or describes a performance regression.
tags: [domain:debugging, intent:debug, intent:fix, intent:diagnose, type:skill]
---

# Diagnose

A discipline for hard bugs. Skip phases only when explicitly justified.

When exploring the codebase, use the project's domain glossary to get a clear mental model of the relevant modules, and check ADRs in the area you're touching.

## Phase 1 — Build a feedback loop

**This is the skill.** Everything else is mechanical. If you have a fast, deterministic, agent-runnable pass/fail signal for the bug, you will find the cause — bisection, hypothesis-testing, and instrumentation all just consume that signal. If you don't have one, no amount of staring at code will save you.

Spend disproportionate effort here. **Be aggressive. Be creative. Refuse to give up.**

### Ways to construct one — try them in roughly this order

1. **Failing test** at whatever seam reaches the bug — unit, integration, e2e.
2. **Curl / HTTP script** against a running dev server.
3. **CLI invocation** with a fixture input, diffing stdout against a known-good snapshot.
4. **Headless browser script** (Playwright / Puppeteer) — drives the UI, asserts on DOM/console/network.
5. **Replay a captured trace.** Save a real network request / payload / event log to disk; replay it through the code path in isolation.
6. **Throwaway harness.** Spin up a minimal subset of the system (one service, mocked deps) that exercises the bug code path with a single function call.
7. **Property / fuzz loop.** If the bug is "sometimes wrong output", run 1000 random inputs and look for the failure mode.
8. **Bisection harness.** If the bug appeared between two known states (commit, dataset, version), automate "boot at state X, check, repeat" so you can `git bisect run` it.
9. **Differential loop.** Run the same input through old-version vs new-version (or two configs) and diff outputs.
10. **HITL bash script.** Last resort. If a human must click, drive _them_ with `scripts/hitl-loop.template.sh` so the loop is still structured. Captured output feeds back to you.

Build the right feedback loop, and the bug is 90% fixed.

### Iterate on the loop itself

Treat the loop as a product. Once you have _a_ loop, ask:

- Can I make it faster? (Cache setup, skip unrelated init, narrow the test scope.)
- Can I make the signal sharper? (Assert on the specific symptom, not "didn't crash".)
- Can I make it more deterministic? (Pin time, seed RNG, isolate filesystem, freeze network.)

A 30-second flaky loop is barely better than no loop. A 2-second deterministic loop is a debugging superpower.

### Non-deterministic bugs

The goal is not a clean repro but a **higher reproduction rate**. Loop the trigger 100×, parallelise, add stress, narrow timing windows, inject sleeps. A 50%-flake bug is debuggable; 1% is not — keep raising the rate until it's debuggable.

### When you genuinely cannot build a loop

Stop and say so explicitly. List what you tried. Ask the user for: (a) access to whatever environment reproduces it, (b) a captured artifact (HAR file, log dump, core dump, screen recording with timestamps), or (c) permission to add temporary production instrumentation. Do **not** proceed to hypothesise without a loop.

Do not proceed to Phase 2 until you have a loop you believe in.

## Phase 2 — Reproduce

Run the loop. Watch the bug appear.

Confirm:

- [ ] The loop produces the failure mode the **user** described — not a different failure that happens to be nearby. Wrong bug = wrong fix.
- [ ] The failure is reproducible across multiple runs (or, for non-deterministic bugs, reproducible at a high enough rate to debug against).
- [ ] You have captured the exact symptom (error message, wrong output, slow timing) so later phases can verify the fix actually addresses it.

Do not proceed until you reproduce the bug.

## Phase 3 — Hypothesise

Generate **3–5 ranked hypotheses** before testing any of them. Single-hypothesis generation anchors on the first plausible idea.

Each hypothesis must be **falsifiable**: state the prediction it makes.

> Format: "If <X> is the cause, then <changing Y> will make the bug disappear / <changing Z> will make it worse."

If you cannot state the prediction, the hypothesis is a vibe — discard or sharpen it.

**Check Stack Overflow for the specific error signature** (exact exception message, stack trace shape, or symptom) before finalizing the ranked list — not instead of it. If the signature matches a well-corroborated SO answer (accepted, high-voted, version-consistent with your stack), fold it in as a ranked hypothesis with a note on its source; it doesn't skip Phase 1/2 or get treated as confirmed until it survives your own feedback loop. A generic search for the bug's *symptom* rather than its exact signature is usually noise — narrow the query to what makes this failure specific.

**Show the ranked list to the user before testing.** They often have domain knowledge that re-ranks instantly ("we just deployed a change to #3"), or know hypotheses they've already ruled out. Cheap checkpoint, big time saver. Don't block on it — proceed with your ranking if the user is AFK.

**MARVIN-specific gotcha classes** — check these early when the symptom fits, before deeper instrumentation:
- *Script works manually, fails/no-ops silently under launchd or cron*: the scheduled job's PATH doesn't include the interactive shell's additions. A script that shells out to a CLI (e.g. `claude`) can resolve to nothing and have its error swallowed into the very output it's supposed to produce — confirmed 2026-07-02, where this masked a broken daily-digest cron for days because the "digest" was literally the error string.
- *A hook fires on unrelated files/edits repo-wide*: Claude Code hook matchers key on tool name (Write/Edit), not path — they do not scope by file location unless the hook script does its own path filtering. Confirmed 2026-07-02 on `rebuild-manifest.py`, which ran on every Write/Edit anywhere until path-scoped explicitly.
- *Derived state (manifest, index, cache) goes stale after a raw deletion*: hooks only fire on tool calls (Write/Edit), not on `rm` or other out-of-band filesystem changes — a manual `rm` on a tracked file leaves derived state pointing at something that no longer exists until a manual resync runs. Confirmed 2026-07-02: `manifest.json` stayed stale after deleting a skill file, with no hook to catch it.
- *A trust/config flag in `~/.claude.json` won't stick despite correctly re-accepting the dialog*: a long-running `claude` process loads that file into memory at startup and periodically flushes its own state back to disk on its own schedule — this silently clobbers any out-of-band change (manual edit, or a dialog accepted in a *different* session) with the stale in-memory snapshot. The fix is ending the long-running session so a fresh process reads the current file, not repeating the accept dialog. Confirmed 2026-07-03, root-caused via PID/timeline correlation while debugging why `claude remote-control` workspace trust wouldn't persist.
- *A deploy/install script silently drops files it should have copied*: a copy step built around a glob like `dir/*` only reaches what's inside that one subdirectory — sibling top-level files and symlinks are missed with no error. Files `cp`'d rather than symlinked to their git-tracked original also drift silently and stop feeding cross-machine sync. Confirmed 2026-07-03 setting up a second machine — `install_skills()` missed `brain-map/`, `retrospective-log.md`, and resume-tailor's deps entirely; `retrospective-log.md` on the deployed machine was also a bare `cp` outside git until fixed to a symlink.
- *A background/menu-bar app briefly flashes visible despite requesting `.accessory` activation policy*: if it's a bare compiled binary rather than a proper `.app` bundle, `NSApplication.setActivationPolicy(.accessory)` runs too late — macOS has already registered the process under the default policy by the time the runtime call executes. Fix is a real `.app` bundle with `LSUIElement` set in `Info.plist`, not a runtime workaround. Confirmed 2026-07-03 on DesktopLive.
- *A scheduled `claude -p` script produces a report that reads like a narrated failure ("I tried to write X but couldn't...") instead of the intended output*: an unrestricted `claude -p` call for a read-only reporting/generation task can still attempt a Write or Edit, get silently denied by the harness, and then narrate that denial into the very stdout it's supposed to produce as clean output. Fix: pass `--disallowedTools "Write,Edit"` (or the minimal tool set actually needed) on any non-interactive `claude -p` invocation whose job is to *produce* text, not modify files. Confirmed 2026-07-06 in both `daily_digest.py` and `research_digest.py` — same root cause hit twice independently, fixed identically in both.
- *Building anything (eval harness, client, integration) against a local model server's "OpenAI-compatible" API*: compatibility is usually partial, not full — check which specific params are actually implemented before designing around the assumption. Confirmed 2026-07-07: `mlx_lm.server` has no `echo` support at all, which `lm-eval`'s `local-completions` backend needs for log-likelihood tasks (`leaderboard_mmlu_pro`); the whole server-based harness was a dead end, discovered only after building it. Fix was dropping the HTTP layer and writing a small in-process adapter wrapping the library directly instead of assuming the server exposed everything the eval tool expected.
- *A regex parses one log/state-file entry using a greedy `.+` under `re.DOTALL`*: DOTALL makes `.` match newlines too, so the greedy `.+` keeps consuming past the intended entry boundary and bleeds into the next entry — corrupting every entry after the first, often silently. Confirmed 2026-07-14 in `check_sync_log()`: a greedy header regex under DOTALL swallowed subsequent log entries. Fix: use a negated-newline class (`[^\n]+`) for any field that should stay single-line, reserving DOTALL-sensitive greediness for the part of the pattern that actually needs to span lines.
- *A monitoring check scans a log's text for a keyword (e.g. "CONFLICT") to detect an ongoing problem*: once written, the keyword persists in the log forever, so the check keeps firing as a false positive long after the problem was resolved — text logs are a historical record, not current state. Confirmed 2026-07-14 building the SessionStart hook's conflict detector: `sync-log.md` still contained "CONFLICT" from an already-resolved merge, and a real stray stash from that old conflict was found sitting unresolved. Fix: query the live authoritative source directly (`git status --porcelain` conflict codes, `MERGE_HEAD` existence, `git stash list`) instead of grepping historical logs for keywords.
- *A prose checklist in CLAUDE.md/SKILL.md gets converted into a deterministic hook that runs the same checks*: leaving the old step-by-step prose in place alongside the new hook causes the model to re-perform checks the hook already ran and injected into context — wasted tool calls/context, and a real risk of silent disagreement between the hook's output and the model's own recheck. Fix: collapse the prose to a one-line pointer + an explicit "don't re-perform these by hand" instruction, and move full step rationale to a separate reference doc that tells editors to update it in the same commit as the script. Confirmed 2026-07-14 converting MARVIN's 11-step session-start checklist into `session_start_report.py`.

## Phase 4 — Instrument

Each probe must map to a specific prediction from Phase 3. **Change one variable at a time.**

Tool preference:

1. **Debugger / REPL inspection** if the env supports it. One breakpoint beats ten logs.
2. **Targeted logs** at the boundaries that distinguish hypotheses.
3. Never "log everything and grep".

**Tag every debug log** with a unique prefix, e.g. `[DEBUG-a4f2]`. Cleanup at the end becomes a single grep. Untagged logs survive; tagged logs die.

**Perf branch.** For performance regressions, logs are usually wrong. Instead: establish a baseline measurement (timing harness, `performance.now()`, profiler, query plan), then bisect. Measure first, fix second.

## Phase 5 — Fix + regression test

Write the regression test **before the fix** — but only if there is a **correct seam** for it.

A correct seam is one where the test exercises the **real bug pattern** as it occurs at the call site. If the only available seam is too shallow (single-caller test when the bug needs multiple callers, unit test that can't replicate the chain that triggered the bug), a regression test there gives false confidence.

**If no correct seam exists, that itself is the finding.** Note it. The codebase architecture is preventing the bug from being locked down. Flag this for the next phase.

If a correct seam exists:

1. Turn the minimised repro into a failing test at that seam.
2. Watch it fail.
3. Apply the fix.
4. Watch it pass.
5. Re-run the Phase 1 feedback loop against the original (un-minimised) scenario.

## Phase 6 — Cleanup + post-mortem

Required before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop)
- [ ] Regression test passes (or absence of seam is documented)
- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix)
- [ ] Throwaway prototypes deleted (or moved to a clearly-marked debug location)
- [ ] The hypothesis that turned out correct is stated in the commit / PR message — so the next debugger learns

**Then ask: what would have prevented this bug?** If the answer involves architectural change (no good test seam, tangled callers, hidden coupling) hand off to the `/improve-codebase-architecture` skill with the specifics. Make the recommendation **after** the fix is in, not before — you have more information now than when you started.
