# 0024 — Fixed PR evidence schema for v1, adaptive per-ticket requirements deferred

## Status

Accepted (2026-08-27)

## Context

The MR-review dashboard's detail view (following #71's approve-only MVP) needs to show design,
requirements, tasks, architecture, tests-with-results, and dev-environment evidence for any MR —
whether raised autonomously by `mr_raiser.py` or manually via a live ticket-pickup session (like
#70/#71). Today `mr_raiser.py` only attaches a metrics-comparison table (`lib/mr_raiser.py:60-66`);
manually-raised PRs are freeform prose. Neither produces test pass/fail counts or dev-environment
evidence at all.

Two shapes were considered: (a) one fixed, structured PR-body schema every PR must conform to, or
(b) a per-ticket "what does this ticket actually need" decision — eventually an early n8n
classifier node — that decides which evidence sections are required vs. legitimately blank before
any PR is written (e.g. a pure backend ticket wouldn't need dev-environment evidence).

(b) is the real long-term vision (Gil: "part of the vision is setting up those n8n pipelines so
that one of the first nodes is deciding what the project needs for documentation... but we should
end up with a structured repeatable format for what is provided in the MR"), but the classifier
node itself is unbuilt, undesigned, and explicitly out of scope for the parent PRD (#1, "Out of
Scope": "exact n8n node-by-node topology... separate downstream design/build work").

## Decision

Build the fixed schema now: every MR-pipeline PR (autonomous or manual) uses one structured body
format — metrics comparison, test results, dev-environment evidence, and links back to the
originating ticket/PRD for requirements/design/architecture rather than duplicating them into the
PR. All sections are present on every PR in v1, with one narrow built-in exception: dev-environment
evidence is only required when the ticket touches UI code (checked directly, not via a general
classifier) — headless/backend tickets legitimately show "N/A — no UI." Per-ticket *adaptive*
section requirements (the classifier-node idea) are explicitly deferred to a later iteration.

## Consequences

- The dashboard's detail view has exactly one shape to parse, regardless of how a PR was raised —
  no dual-format branching logic to build or maintain in v1.
- `mr_raiser.py`'s executor/measure contract must be extended to capture real test-suite results
  (pass/fail/total) as a distinct section, and — for UI-touching tickets — drive the app headlessly
  (reusing the `run` skill's Electron/Playwright pattern) to capture a screenshot. This is new
  pipeline work, not just dashboard UI work.
- Manually-raised PRs must also start following this schema, which changes the human/live-session
  PR-writing habit established this session (#70/#71's freeform style stops being the norm).
- Known gap this doesn't resolve: today every ticket gets every applicable section whether it's
  actually useful evidence for that ticket or not. The adaptive classifier that would fix this is
  unbuilt — revisit when the n8n topology work actually starts.
