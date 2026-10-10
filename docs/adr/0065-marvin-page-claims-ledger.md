# ADR 0065: MARVIN page claims ledger — every claim is checked against system truth

**Status:** Accepted (2026-10-10, issue #281). Supersedes the orphan 0059-candidate (c244169, found not to pass verification).

## Context

The MARVIN page describes how MARVIN works: "it runs on two Macs", "it proves every change with tests before I see it", "it's open source", "it keeps working while I'm away." These are factual claims. When the system changes (a machine is added, main fails, a job breaks, the repo visibility changes), the page becomes untrue and needs redraft.

Earlier attempt (#281 orphan): built a new parallel check framework (claims.py with its own shape, IPC endpoint, dashboard card), duplicating machinery that already exists (health_checks.py's check registry, project_catalog.py's visibility fetch, portfolio_content.py's findings model).

## Decision

**Reuse existing infrastructure:**

1. **Checks:** `health_checks.check_main_health()`, `project_catalog`, `job_events.status_of()`, and hand-written checks for machine count and visibility.
2. **Framework:** One small pure-functions module (claims.py, mirroring facts.py's pattern): `collect()` runs all checks nightly, writes one JSON file.
3. **Integration:** `portfolio_content.evaluate()` reads that file (for marvin slug only) and folds claim failures into the page's existing `findings` list, keyed by `role` so the Content tab's per-page findings already render claim issues with no new UI.
4. **Delivery:** Nightly launchd job (02:30 UTC on mini, same host as the dashboard), JSON ledger cached locally.

**Claim tracking:** Four seed claims from the page copy, stored verbatim in the ledger:
- "it runs on two Macs" → `check_two_machines()` → reads machine registry
- "it proves every change with tests before I see it" → wraps `check_main_health()` → reads merge gate state
- "it's open source" → `check_repo_visibility()` → reads catalog or gh repo view
- "it keeps working while I'm away" → `check_jobs_recent()` → reads job status across the registry

**Unchecked sentence detection:** Drafted sections are scanned for sentences that state facts without a ledger entry and listed for Gil to either back with a check or cut (stub seam: `flag_for_redraft()` is a stub, pending #269 for implementation).

**No new dashboard infrastructure.** The Content tab's existing per-page findings count and list are used as-is.

## Consequences

- Every claim carries an implementation: a pure check function that reads the system once nightly. **Layer 1 (displayed numbers on the page) always come from facts.json; layer 4 (truth checks) never recompute them** — the ledger is the permanent source of truth for claims.
- The ledger is a JSON file, durable and visible to CI/scripts/other sessions, not hidden in logs.
- A failing claim marks its section untrue on the Portfolio tab immediately (no redraft until #269); an unchecked sentence is flagged for human review.
- The same check infrastructure underpins the Health tab (via health_checks.py) and the claims ledger, so a machine count check that's wrong gets the same visibility as a job health check.
- Drafting new copy without checks backs it with a seam (stub function: `flag_for_redraft()`) until a real check is added — the page can't claim something without infrastructure to verify it.
