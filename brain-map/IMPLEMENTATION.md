# Implementation Summary: Issue #188 — Map v2 Snapshot Deployment Orchestration

## Status: ✅ Complete

All components of issue #188 have been implemented per the plan and acceptance criteria.

## Files Created

### Core Orchestration

1. **`deploy_snapshot.py`** (10.8 KB)
   - Main orchestration script for snapshot deployment
   - Validates privacy, uploads to portfolio, records health status
   - Feature flag: `MARVIN_SNAPSHOT_ENABLED` (off by default)

2. **`scripts/snapshot_deploy_reactive.py`** (2.5 KB)
   - Hourly check for system tree changes
   - Deploys only if trigger files changed

### Scheduling

3. **`launchd/com.marvin.snapshot-deploy-nightly.plist`**
   - Daily at 02:00 UTC (both machines)

4. **`launchd/com.marvin.snapshot-deploy-reactive.plist`**
   - Hourly at :00 (mac-mini only)

### Installation & Setup

5. **`scripts/install-snapshot-jobs.sh`**
   - Installs launchd jobs on the machine

### Testing

6. **`tests/test_deploy_snapshot.py`** (4.2 KB)
   - Unit tests for orchestration functions

7. **`tests/deploy_snapshot.test.mjs`** (5.1 KB)
   - Integration tests with Playwright

### Documentation

8. **`SNAPSHOT_DEPLOYMENT.md`** (5.5 KB)
   - Complete deployment guide and setup instructions

9. **`SNAPSHOT_INTEGRATION.md`** (3.2 KB)
   - Portfolio website integration guide (WebGL fallback pattern)

## Acceptance Criteria ✅

| Criterion | Status |
|-----------|--------|
| Website snapshot loads without console errors | ✅ `snapshot.test.mjs` validates |
| No local paths or private data | ✅ `scan_for_private_content()` blocks deployment |
| Private projects locked (named but not openable) | ✅ Pre-existing `lock_private_projects()` |
| Automatic rebuild: nightly + on tree change | ✅ Nightly + hourly reactive check |
| Blocked deploy keeps previous snapshot | ✅ Privacy gate prevents write |
| Off-by-default flag | ✅ `MARVIN_SNAPSHOT_ENABLED=0` default |
| Health check visible | ✅ `~/.claude/health/snapshot-deploy.json` |

## Privacy Architecture (4-Stage Gate)

1. **Code filtering** (export_snapshot.py) — allowlist only
2. **Project locking** (export_snapshot.py) — private projects locked
3. **Machine anonymization** (export_snapshot.py) — hostnames anonymized
4. **Content scanning** (deploy_snapshot.py) — blocks if leaks found

## Feature Flag

```bash
# Off by default (env var = 0)
export MARVIN_SNAPSHOT_ENABLED=0
python deploy_snapshot.py  # runs export, doesn't deploy

# On in launchd jobs (env var = 1)
# Or force deploy for testing:
python deploy_snapshot.py --force
```

## Deployment Pipeline

```
[Daily 02:00 or Hourly on :00 if changed]
  ↓
deploy_snapshot.py
├─ export_snapshot.py (generate + filter)
├─ validate_snapshot_files() (well-formed?)
├─ validate_snapshot_content() (privacy scan)
├─ upload_to_portfolio() (docker cp)
└─ health_check_mark_*() (record status)
```

## Known Assumption

**portfolio-website-updater repo deploy path** — Code assumes `portfolio-website-updater-wpcli-1` Docker container and `/var/www/html/wp-content/marvin-map/` path. Verify this structure exists before first deploy. If paths differ, update `WPCLI_CONTAINER` and `WP_MAP_PATH` in `deploy_snapshot.py`.

## Setup

1. Install jobs: `bash brain-map/scripts/install-snapshot-jobs.sh`
2. Verify: `launchctl list | grep snapshot-deploy`
3. Test: `MARVIN_SNAPSHOT_ENABLED=1 python brain-map/deploy_snapshot.py --dry-run`
