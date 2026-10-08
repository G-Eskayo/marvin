# 0059 — MARVIN Page Claims Ledger (#281)

## Status

Accepted (2026-10-08)

## Context

The MARVIN portfolio page makes system claims: "it runs on two Macs", "it proves every change with tests before I see it", "it's open source", "it keeps working while I'm away". These claims are assertions about live system state (registered machines, recent test gates, repo visibility, job health). Without a verification mechanism, they can become stale or false without notice.

## Decision

Build a claims ledger as code + data (not prose):
1. **Ledger source**: `brain-map/scripts/claims.py`, a pure functions module like `facts.py`
   - `CLAIMS`: list of `{id, section, text, checker}` — seed four claims from the ticket examples
   - Four pure `check_*` functions: each reads system data, returns `{ok: bool, detail: str}`
   - `collect(gather=None)`: runs all checkers, returns `{claim_id: {ok, detail, section, text, checked_at}}`
   - `scan_for_unchecked_claims(html)`: flag numeric facts in page HTML not in CLAIMS
   - `flag_for_redraft(claim)`: stub that references #269 (the actual redraft trigger, not yet built)

2. **Nightly job** (`com.marvin.claims-ledger-nightly.plist` + `JOB_PLACEMENT["claims-ledger-nightly"] = "mini"`):
   - Runs `claims.py --nightly` once per night, logs via `job_events.job_run()`
   - Writes results to `~/.claude/logs/claims-ledger.json` (local, never published)
   - Calls `flag_for_redraft()` for any failing claim (stub until #269)

3. **Dashboard surfacing** (Portfolio > Content tab):
   - `portfolio.claimsReport()` spawns `claims.py --json`, returns ledger
   - UI displays: claims grid (ok/failed badge + detail) + unregistered-claims list for Gil's review
   - Callable live without requiring a nightly job run (for quick validation)

4. **Layers and seams**: Leave layers 2 & 3 as stubs
   - Layer 1 (facts.json): already live via `facts.py`
   - Layer 2 (use-case cards): stub until #268
   - Layer 3 (redraft-on-trigger): one `flag_for_redraft()` call, replaced by #269 with zero other changes
   - Layer 4 (this ticket): full implementation, calling the seams

## Consequences

- Four named claims are now verifiable: the page can assert them confidently knowing they're checked nightly
- Unregistered claims are surfaced to dashboard so Gil can choose to register or cut them
- The implementation is testable: `collect()` accepts injected `gather()`, each checker is pure
- The redraft trigger (#269) is a one-line stub swap: `flag_for_redraft()` → a real redraft call
- Job health is wired to health_checks.py, so a stale run is visible via Health tab

## Alternatives considered

- Hand-verify claims each week: doesn't scale, claims go unnoticed
- Embed checks in the page-build pipeline: couples the ledger to Hugo/build complexity
- Three pure layers sequentially before doing verification: delays shipping, blocks #269 prep
- Publish the ledger to the live page: creates a dependency on state being current; local-only is safer
