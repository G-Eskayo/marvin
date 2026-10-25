# ADR 0065: MARVIN page claims ledger—track portfolio facts over time

**Status:** Accepted (2026-10-10, #281). Outcome of ticket #281's planning.

## Context

The MARVIN portfolio page (and the system behind it) make dozens of factual claims: "MARVIN built clarity-captions", "daily-digest runs successfully", "#281 reached done stage". These facts are verifiable against concrete evidence (portfolio content, job event logs, ticket stage history), but today they're never checked—they live in prose and documentation, trusted but unverified. When a claim turns false (a portfolio page loses a required image, a job starts crashing, a ticket stalls), nobody discovers it until a human reads the page or the logs.

Gil wanted this surfaced as a scalable, persistent check rather than manual audits, wired to the dashboard so claims failures become visible immediately, not weeks later.

## Decision

**A claim is a structured fact** about the system, paired with a check function that returns true/false and optional detail:
- **Example:** "Clarity Captions page links to MARVIN" → check portfolio content for the link
- **Example:** "Daily digest job's last run passed" → check job_events log
- **Example:** "Ticket #281 reached done stage" → check ticket_stages history

**Claims are verified from three evidence sources:**
1. `portfolio_content`: portfolio pages (template coverage, copy quality, reciprocal MARVIN links)
2. `job_events`: background job health (daily-digest, research-colony, etc.)
3. `ticket_stages`: ticket pipeline progress (stage completion, cost tracking)

**Collection and storage:**
- `claims.py --nightly` runs at 02:30 local time daily on mini (via launchd), collecting all claims into an atomic JSON file (`~/.claude/logs/claims-ledger.json`) and recording the run in the job_events dashboard.
- Each claim's result includes: pass/fail, detail, timestamp. The report includes all results and any unregistered claims found in the portfolio.
- No caching: each run re-gathers all evidence (portfolio, job logs, ticket stages) and re-checks all claims fresh.
- Claims ledger data is per-machine, not synced (job logs and stage files are local).

**The MARVIN page wires the ledger:**
- Dashboard backend (`portfolio.js::claimsReport()`) loads the claims ledger from disk; **if the file doesn't exist, is missing/unparsable/in the future timestamp, or is stale (>25h), the section renders empty and the error is visible** (never silent failure).
- The PortfolioHub's Content section shows:
  - A grid of claims with status badges (✓/✗), rule name, detail, timestamp
  - List of any unregistered claims detected in visible text (scan_for_unchecked_claims: bare #123 patterns not in CLAIMS, word-boundary matched, excluding ADR/PR refs)
- If claims report fails to load, the section shows the error, not a blank.

**Unregistered claim detection:**
- `scan_for_unchecked_claims()` extracts visible text (no HTML/code blocks) from portfolio pages
- Finds all bare #NNN patterns using word boundaries, but skips ADR/PR prefixes
- Returns ticket identifiers (e.g., marvin-281) not already in the CLAIMS list
- Wired into `collect()` to scan portfolio content and include results in the report's `unregistered` field

**Philosophy (per ADR 0051's "show don't tell"):**
- Claims are data, not narrative—no marketing copy, no overclaiming.
- If a portfolio page says "built with MARVIN", we verify it links back. If it's false, we say so.
- Claims failures are *not* failures of MARVIN itself—a stale ledger or a real job crash are separate facts.

## Consequences

- Portfolio facts are now verifiable, discoverable, and tracked over time. Falsehoods surface immediately.
- The ledger is honest: a failed claim is a data point, not a reason to disable the ledger. Failed claims stay in the report.
- New claims are easy to add (one function + one line in CLAIMS list).
- The dashboard sees one integration point (load the JSON file); claims logic is all in claims.py.
- If a source (portfolio, jobs, tickets) is unavailable, checks gracefully return false rather than crashing.
