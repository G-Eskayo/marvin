# Pipeline visibility and retry-storm guard — 2026-10-07

Owner session: WezTerm tab "MARVIN · Pipeline stages" (Mac mini). Started from the 2026-10-07 triage session.

## Why

- PR #209 could not be merged from the dashboard for hours. The Approve-time merge-order check got the raw PR list
  (no `sentBack`), so #209 said "Merge #208 first" while #208 was refused as sent back. Fixed in 20632f3, but finding
  it took SSH and log archaeology, because dashboard-side refusals are never recorded and webhook error lines have no
  PR URL or time.
- Gil wants GitLab-style pipeline indicators: see at a glance which stage a ticket/PR is in and where it failed.
- Retry storms (#28 failed 1,644 times) were ~70% of output tokens. Goal of the whole system: minimal paid LLM use.
  The model only plans and writes code; everything after (tests, gate, rebase, order, merge) is deterministic.

## Design stance (decided with Gil)

One shared pipeline + a per-project profile (like GitLab's one runner + `.gitlab-ci.yml`), not a pipeline per
project. Stages are generic; a profile decides which checks run inside a stage. Visuals are derived from the stage
logs, never stored separately.

## Tickets, in order

1. **#216** Ticket stage logs keyed by project + ticket number (bug; foundation for the strip)
2. **#215** Record every merge refusal with its PR, stage and time (dashboard and webhook)
3. **#218** Stop retry storms: hold a ticket after N failed pipeline runs (uses #213's `Revisit by:` convention)
4. **#217** Pipeline stage strip on PR and ticket cards (blocked by #215, #216)

Related: #213 (holds come back), #126 (real screenshots in UI PRs), #73 (re-engagement pipeline).

## Working rules for the session

- `ready-for-agent` was removed from #215–#218 so the automatic pipeline doesn't race this session; claim each with
  `claimed:mac-mini` while working it.
- Work in a separate worktree/branch per ticket, not the shared `~/.agents` checkout (auto-sync commits there).
- TDD (red → green), full dashboard suite (`npx vitest run`) + relevant pytest before each PR; PR body uses the
  evidence schema and `Closes G-Eskayo/marvin#N`.
- Docs: decisions go into CONTEXT.md / an ADR, plans here. Not in outbox.
- Merge through the dashboard's Approve button where possible: it exercises the 20632f3 fix and #215's logging.
