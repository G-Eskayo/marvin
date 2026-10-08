# ADR 0056 — Disk ledger, auto-trim, and headroom forecast

**Date:** 2026-10-08  
**Status:** Accepted  
**Issue:** #243  

## Context

Pipeline disk usage was filling both machines unpredictably. The mac-mini hit 94% capacity (6% free), which triggers aggressive macOS iCloud eviction and background job stalls. The root causes were:

1. No visibility into what disk categories consumed space and how usage changes day-to-day.
2. No automatic cleanup under pressure — human-driven intervention only.
3. No early warning before critical thresholds (10–15% free) are reached.

Existing infra in #130's live health panel and ADR 0033's `health_checks.py` already surface `disk:space` (free percentage) but lack trend and forecast.

## Decision

Build three integrated subsystems, all scheduled as part of the existing daily `cleanup-sweep` job (both machines, 04:15):

### 1. **Disk ledger** (`lib/disk_ledger.py`)

Append-only JSONL ledger (`~/.claude/logs/disk-ledger.jsonl`), one entry per device per day:

```json
{
  "device": "mac-mini",
  "date": "2026-10-08",
  "timestamp": "2026-10-08T10:30:45+00:00",
  "free_kb": 15728640,
  "total_kb": 1048576000,
  "categories": {
    "rebuildable_caches": 250000,
    "build_output": 50000,
    "worktrees": 500000,
    "models": 100000,
    "icloud_cache": 80000,
    "docker": 30000,
    "user_files": 5000000,
    "other": 500000
  }
}
```

- **Rebuildable caches:** npm, pnpm, pip, Homebrew, Electron, SwiftPM — can be recreated via package managers on next use.
- **Build output:** `.build`, `.swiftpm`, `node_modules` (not from worktrees).
- **Worktrees:** all pipeline worktrees under `~/.agents-pipeline-worktrees`.
- **Models:** `.ollama`, `.cache/huggingface`, etc.
- **iCloud cache:** `~/Library/Mobile Documents`.
- **Docker:** from `docker system df`.
- **User files:** Documents, Desktop, Pictures, Downloads, Messages.
- **Other:** remainder.

Same-device-per-day entries overwrite (idempotent on rerun); different days append (true JSONL log). Measured via `du -sk` for each category, with injectable callables for testing.

### 2. **Disk trimming** (`lib/disk_trim.py`)

Explicit allowlist strategy with **deny-first** checking: `NEVER_TRIM` set is checked *before* any allowlist match.

**NEVER_TRIM** (sacred paths):
- `~/Library/Caches/ms-playwright` — required for `lib/portfolio_parity.py` and `lib/portfolio_layouts.py` parity tests (does not rebuild on its own).
- `~/.Trash`
- `~/Library/Mobile Documents` (iCloud cache)
- `~/.ollama`, `~/.cache/huggingface` (ML models)
- Any worktree where `cleanup_sweep.decide_worktree()` says "keep" or "review" (open PR, claimed issue, uncommitted work, or unclassifiable).

**Allowlist** (safe-to-trim):
- npm (`~/.npm/_cacache`)
- pnpm store
- pip cache
- Homebrew cache
- Electron cache
- SwiftPM cache
- Xcode `DerivedData/*` entries older than 7 days (per-entry trim, not whole directory)
- Pipeline worktree build output (`.build`, `.swiftpm`, `node_modules`) older than 3 days, reusing `cleanup_sweep.drop_build_output()` for safety.

Trim only fires when free% < `DISK_YELLOW_BELOW_PCT` (20%, imported from `health_checks.py`, not duplicated). Removals logged to `~/.claude/logs/mr-pipeline-sweep.md` alongside other sweep output.

### 3. **Headroom forecast** (in `lib/health_checks.py`)

Extend `_MACHINE_STATE_SCRIPT` to emit the tail of `disk-ledger.jsonl` (last 14 days). `parse_machine_state()` parses the entries. `forecast_days_to_critical()` computes a simple linear regression (least-squares fit) of free KB over the ledger's day index, forecasts days until the 15 GiB floor (from `config/dispatch.json`'s `min_disk_gb`).

Severity mapping:
- **Green:** ≥30d forecast or insufficient history (< 2 ledger entries).
- **Yellow:** <30d forecast with expansion warning pointing to `docs/plans/storage-and-distribution-2026-10-06.md` item E2 (external SSD).
- **Red:** <7d forecast.

`check_machine_state_everywhere()` adds `disk:headroom@<device>` to the results list (same channel as #130's live panel), keyed by machine ID like every other per-device check.

When red, `health_checks._cli()` calls `disk_forecast_notify.notify_red_headroom()` (three-channel pattern: desktop, push, dashboard), de-duped once per device per calendar day via `~/.claude/logs/disk-headroom-notified.json`.

## Rationale

- **Ledger as JSONL:** append-only, immutable history, simple to rotate/archive, reads well in `tail` for human inspection. Same-day idempotence (overwrite, not duplicate) handles job reruns.
- **Deny-first allowlist:** `ms-playwright` is not a bug or wishful thinking — it's a hard constraint from the parity test suite. Checking `NEVER_TRIM` first makes the constraint visible in the code and prevents any allowlist entry from accidentally overriding it.
- **Reuse `decide_worktree()`:** don't re-derive worktree safety rules; call the existing function. Protects dirty/claimed/open-PR worktrees automatically.
- **Linear regression forecast:** simple, good enough for 14-day trends. Threshold (7d red, 30d yellow) gives time to plan (order external storage, ~2 weeks delivery) before hitting critical.
- **Notifications via existing channel:** `disk_forecast_notify.py` copies `mr_notification.py`'s three-channel pattern (desktop, push, dashboard) and the de-duping logic from notification state. No new infra.
- **Integrated into existing job:** `run_daily_sweep()` now calls `disk_ledger.run_daily_ledger()` and `disk_trim.trim_with_logging()` alongside the existing claim and worktree sweeps. One daily job, one place to look.

## Implementation

- `lib/disk_ledger.py`: measurement + append-only ledger.
- `lib/disk_trim.py`: explicit allowlist trim, gated on free% check.
- `lib/disk_forecast_notify.py`: red-forecast notifications (three-channel).
- `lib/health_checks.py` updates:
  - Extend `_MACHINE_STATE_SCRIPT` to emit ledger tail.
  - Add `parse_machine_state()` parsing of ledger entries.
  - Add `forecast_days_to_critical()` linear regression.
  - Add `disk:headroom` check to `evaluate_machine_state()`.
  - Add `disk:headroom` to `check_machine_state_everywhere()` labels.
  - Add notification trigger in `_cli()`.
- `lib/cleanup_sweep.py`: call new modules in `run_daily_sweep()`.
- Tests:
  - `lib/tests/test_disk_ledger.py`: categorization, same-day idempotence, different-day append.
  - `lib/tests/test_disk_trim.py`: acceptance criterion (ms-playwright untouched), allowlist trim, dry-run, healthy-disk no-op.
  - `lib/tests/test_health_checks.py` (extended): ledger trends crossing 30d/7d forecasts, notification on red transition.

## Compliance

- **#243 acceptance criteria:**
  - ✓ Ledger daily on both machines, tests on saved `du` samples.
  - ✓ Auto-trim touches only allowlisted paths, fixture test with dirty worktree/models/user files.
  - ✓ Health shows headroom in days + trend, per machine.
  - ✓ Expansion warning fires on a fixture trend crossing 30 days.
  - ✓ Complements #130, same health channel (no parallel system).
  - ✓ `ms-playwright` never auto-trimmed (NEVER_TRIM constant with comment).

## Future

- Rotation/archival of 14-day ledger (maintain only recent history to avoid unbounded growth).
- Per-category alerts (e.g., "docker is 50 GiB, consider `docker system prune`").
- Integration with E2 (external SSD) syncing when deployed.
