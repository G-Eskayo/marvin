# 0059 — Every model run goes through the MARVIN launcher, and every producer declares an output contract

## Status

Accepted (2026-10-08). Design session with Gil covering #291, #274, #276. Builds on [[0030]] (headless allowlist) and [[0040]] (the mobile backend drives headless Claude Code).

## Context

A day of investigation (2026-10-08) found the same failure many times: parts that were built but not connected, with the connections assumed rather than checked.

- **What a model run knew depended on the folder it started in.** A live probe showed sessions started from `~` get MARVIN's rules, memory, lexicon, session report and hooks. Sessions started from `~/.agents` or a pipeline worktree (every ticket agent) get only the rules. Hooks live in the home folder's local settings, and memory is stored per launch folder. That had already split 3 notes into a memory nobody read.
- **About 15 call sites start `claude -p` independently** (pipeline planner and executor, digests, reviews, auto-fix, safety verify, handoff writing, notifications, mobile Chat). Each picks its own flags, folder and prompt. The north stars were hand-copied into one prompt and drifted.
- **Claims to agents were unchecked:** "you are in your worktree" was true only by coincidence until a deterministic preflight was added the same day.
- **Background analysts produce output nobody consumes:** 58 suggestions, 70 quarantined items, 157 queue items, 130 daily and 85 research digests. Ticket promotion, the bridge to action, was never wired. About 9% of headless output tokens, with almost no effect on the code. None of the day's real problems were surfaced by them.

Alternatives considered:

- **Fix each call site** (add the missing flags and memory per script). Rejected: it's the same hand-copying that drifted, and the next new feature would repeat it.
- **Give every run everything** (all layers everywhere). Rejected: it works against the north star (minimise tokens) for small Haiku executor runs, and it biases Judges, which must start clean.
- **Rely on prompts** ("you have MARVIN's memory"). Rejected: an unchecked claim is the failure we're fixing.

## Decision

1. **The MARVIN launcher is the only way to start a model run.** The caller names a **launch kind** (Interactive, Ticket planner, Ticket executor, Background analyst, Utility call, Judge; see CONTEXT.md). The launcher assembles that kind's declared layers of MARVIN context (one table in code, mirroring CONTEXT.md), sets the folder and permissions, verifies them deterministically before spending tokens, and records the run for Metrics and Health. Interactive brings in other kinds by **delegating** (starting a run of that kind), never by switching. New features that need a model must use the launcher with an existing or newly declared kind. A test fails on any model invocation outside it.
2. **Every producer declares an output contract:** where its output goes, and who or what acts on it within how long. Output that isn't consumed in time becomes a Health finding. A producer whose output is never consumed is a candidate for removal (the Watts check: thought serving itself).

## Consequences

- **One choke point.** A launcher bug affects every run; it needs strong tests and the per-kind probe. In exchange, "what does this run know?" has one answer, and MARVIN improvements reach every kind at once.
- **Full memory is cheap where it matters:** it means the index (~3k tokens, cached) plus on-demand reads, so the planner and analysts get it. Executors get a derived `work-rule` slice.
- **Existing callers must migrate** (Python scripts, the Node mobile backend, launchd jobs). Until they do, the probe shows which kinds are still wrong.
- **Analysts may shrink.** Once contracts are enforced, some will turn out to have no consumer and should be cut or turned into deterministic checks.
- **Not decided here:** where the single source of north stars lives (#274), and how north stars enter ticket choosing and review (#276). Those follow in this session.
