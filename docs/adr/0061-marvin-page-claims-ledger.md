# ADR 0061: MARVIN page claims ledger — layer 4

**Status:** Proposed (2026-10-10)

**Related:** ADR 0057 (map snapshot auto-publishes), #268 (use-case cards), #269 (story redrafts on architecture triggers)

## Context

The MARVIN page has four layers of freshness (ADR 0057 extension, layer 4 from `docs/plans/living-marvin-page-2026-10-08.md`):

1. **Facts** (auto-generated): counts, lists, numbers from the system
2. **Use-case cards** (auto-generated): one per functional tool, from the map tree + reviewed use-case lines
3. **Story sections** (drafted on architecture triggers): narrative text, approved by Gil
4. **Truth verification** (nightly): every factual claim is checked against system state

Layers 1–3 keep the page up to date; layer 4 proves what it says. Without verification, a claim can drift silently (e.g. a job goes stale, a feature ships, the architecture changes) and the page becomes wrong on the live site. This ADR defines layer 4.

## Decision

A **claims ledger** registers each factual sentence on the page with a check function that reads the system:

- "MARVIN runs on two Macs" → `check_machine_registry()` reads `machine_profile.NETWORK_PATH` (`.claude/marvin-network.json`), counts devices where value is `True`
- "MARVIN is open source" → `check_repo_visibility()` checks GitHub API with injected `run=` callable; missing `isPrivate` key returns "unknown"
- "MARVIN keeps working while you're away" → `check_scheduled_jobs()` reads job logs via `job_events.status_of()`: "failed"/"crashed"/"never" → "untrue", "running" checks prior run for staleness
- "MARVIN proves every change with tests before merge" → `check_merge_gate()` reads `~/.claude/logs/main-health.json` directly (fields: `ok`/`failed`/`checked_at`/`sha`/`summary`); checks both truth (`ok: false` → "untrue") and freshness (stale `checked_at` → "untrue")

**Nightly job** (`com.marvin.claims-ledger-nightly`, running on mini 23:30 after snapshot-deploy-nightly):

1. Loads the claims registry (seed source: Gil's literal claim texts, hardcoded in `_load_seed_registry()`)
2. Runs all checks
3. Writes status atomically to `~/.claude/portfolio/marvin-page-claims.json` using `_write_json_atomic()` helper (fcntl.flock on sibling .lock file)
4. Scans the MARVIN page's `content/longform/marvin.json` for unbacked claims (keyword-matching with inflections: "run(s)?", "prove(s|n)?", etc.)
5. Queues redraft requests to `~/.claude/portfolio/claims-redraft-queue.json`: recomputed from scratch every run (never diffs against previous), one entry per section with "untrue" claims (excludes "unknown")

**Status representation** (never collapses "unknown" into true/false):
- `status: "true"` — claim verified, still accurate
- `status: "untrue"` — claim failed verification, page copy is now false (triggers redraft queue entry)
- `status: "unknown"` — couldn't reach external system (API down, file missing), indeterminate (not queued for redraft)

**Dashboard integration** (Portfolio tab, Claims subtab):

- `api.portfolio.latestClaims()` / `api.portfolio.runClaims()` expose the status and trigger a fresh check
- Status shows per-claim results grouped by status, with `claim_id`/`detail`/`checked_at` for transparency
- Sections with failed (untrue) claims appear in the redraft queue

**Out of scope:**
- `check_facts_delegation`: facts.json numbers are auto-generated, no ledger entry needed
- Copy accuracy (spelling, brand names): Gil's responsibility
- Draft-time gate (when a section is redrafted, scan for new unbacked facts): future work per `draft-gate` decision

## Decisions needed to ship

- `subtab`: location of Claims tab in Portfolio UI (added after Content, before Evaluation)
- `draft-gate`: future ticket for scanning new copy at draft time

## Consequences

- A claim that fails marks its section **untrue** on the dashboard, queuing it for redraft (layer 3)
- Redrafts never silently leave a false claim on the page — either the claim is re-verified and passes, or the page is reworded
- The nightly job's run log appears in the dashboard's Activity tab (via `job_events.reported()`)
- Scope of layer 4: only system state that would be checked anyway (machine count, job recency, API visibility); copy accuracy remains Gil's responsibility
- New checks can be added by adding a `Claim` to the registry seed and a corresponding check function
- STATUS_DIR = `~/.claude/portfolio` (shared with portfolio_eval.py, not a new `~/.claude/health/`)
- Redraft queue is written every run, even if empty (never conditionally deleted)
- Unbacked claims scan degrades gracefully on iCloud hangs via `readable_guard.readable_within()`

## Implementation notes

- `_write_json_atomic()` helper: fcntl.flock on sibling .lock file, write to .tmp, atomic replace
- `build_redraft_queue()`: recomputed from scratch every run, groups only "untrue" status by section
- `scan_unbacked_claims()`: keyword patterns include inflections; guards against "two" in "network" via word boundaries; degrades to skip HTML stripping if `portfolio_content._visible_text()` unavailable
- `check_scheduled_jobs()` falls back to prior run when newest is "running"; normalizes naive timestamps to UTC before staleness check
