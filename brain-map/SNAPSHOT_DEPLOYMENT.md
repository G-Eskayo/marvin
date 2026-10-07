# Map v2 Snapshot Deployment (#188, ADR 0049, ADR 0050)

## Overview

The MARVIN brain-map v2 (ADR 0049) is a 3D, interactive system tree served locally for the wallpaper, dashboard, and network. The snapshot export (ADR 0050) creates a privacy-filtered, public version for the portfolio website, automatically rebuilt nightly and when the system tree changes.

## Implementation

### Modules

1. **`export_snapshot.py`** (existing) — Generates privacy-filtered snapshot
   - Runs the tree generator from `generate.py`
   - Applies privacy filters (allowlist, lock private projects, anonymize machines)
   - Scans for leaked paths, tokens, emails
   - Outputs `snapshot/index.html` and `snapshot/tree-data.json`

2. **`deploy_snapshot.py`** (new) — Orchestrates export and deployment
   - Runs `export_snapshot.py`
   - Validates files and content
   - Deploys to portfolio via wp-cli (or dry-run)
   - Records health check status
   - Controlled by `MARVIN_SNAPSHOT_ENABLED` flag (off by default)

3. **`scripts/snapshot_deploy_reactive.py`** (new) — Hourly check-and-deploy
   - Tracks last deployed commit
   - Checks if system tree files changed
   - Runs `deploy_snapshot.py` only if needed (no log spam)
   - Deployed via `com.marvin.snapshot-deploy-reactive.plist`

4. **Launchd Jobs** (new)
   - `com.marvin.snapshot-deploy-nightly.plist` — Rebuilds at 02:00 daily (both machines)
   - `com.marvin.snapshot-deploy-reactive.plist` — Checks hourly (mac-mini only)

### Acceptance Criteria Status

| Criterion | Status | How |
|-----------|--------|-----|
| Website snapshot loads with no console errors | ✓ | `snapshot.test.mjs` validates load and SNAPSHOT=true |
| No local paths or private data in snapshot | ✓ | `export_snapshot.py` scans + `deploy_snapshot.py` validates before deploy |
| Private projects shown as locked (not openable) | ✓ | `export_snapshot.py`'s `lock_private_projects()` |
| Automatic rebuild: nightly + on system tree change | ✓ | Nightly job + hourly reactive check |
| Blocked deploy keeps previous snapshot | ✓ | Privacy validation gate; only success updates files |
| Off-by-default flag | ✓ | `MARVIN_SNAPSHOT_ENABLED=0` (default), set to 1 in launchd jobs |
| Health check visible | ✓ | `~/.claude/health/snapshot-deploy.json` + Health tab integration |

## Deployment Pipeline

```
[02:00 daily OR :00 hourly if changed]
  ↓
snapshot_deploy_reactive.py (checks for changes)
  ↓
deploy_snapshot.py
  ├─ export_snapshot.py (generate tree + filters)
  ├─ validate_snapshot_files() (HTML/JSON well-formed)
  ├─ validate_snapshot_content() (SNAPSHOT=true, privacy scan)
  ├─ upload_to_portfolio() (docker cp to /map-v2/)
  └─ health_check_mark_*() (record status)
```

## Setup Instructions

### 1. Install Launchd Jobs

On **both machines** (mac-mini-1 and macbook-pro-1):
```bash
cd ~/.agents
bash brain-map/scripts/install-snapshot-jobs.sh
```

This installs:
- `com.marvin.snapshot-deploy-nightly.plist` (both machines, 02:00 daily)
- `com.marvin.snapshot-deploy-reactive.plist` (mac-mini-1 only, hourly)

### 2. Enable the Feature Flag

The jobs are installed with `MARVIN_SNAPSHOT_ENABLED=1` in the plist, but you can control it manually:

```bash
# Enable
export MARVIN_SNAPSHOT_ENABLED=1

# Disable
export MARVIN_SNAPSHOT_ENABLED=0

# Test (requires portfolio dev site running)
python brain-map/deploy_snapshot.py --dry-run
```

### 3. Verify Installation

```bash
# Check jobs are loaded
launchctl list | grep snapshot-deploy

# Check logs
tail -f ~/.claude/logs/deploy-snapshot*.log

# Force a deployment (testing only)
MARVIN_SNAPSHOT_ENABLED=1 python brain-map/deploy_snapshot.py --force
```

## Privacy & Security

The snapshot export goes through three gates before deployment:

### Gate 1: Code Layer Filtering (`export_snapshot.py`)
- Only files tracked in `G-Eskayo/marvin` at the target commit
- Removes `borrowed` (shared) code outside the allowlist
- Filters edges if both ends don't survive filtering

### Gate 2: Project Locking (`export_snapshot.py`)
- Non-PUBLIC projects: set `locked=true`, remove `path`, `openable`, `code`
- PUBLIC projects: keep as-is, remain openable
- Visibility determined by catalog

### Gate 3: Content Scanning (`export_snapshot.py` + `deploy_snapshot.py`)
Refuses to deploy if it finds:
- Home directory paths: `/Users/username`
- IPv4 addresses (non-loopback)
- Email addresses
- Token patterns: `sk-ant-`, `gh_*`, `AKIA`, `xox*`, Bearer tokens

### Gate 4: Machine Anonymization (`export_snapshot.py`)
- Device hostnames replaced with kind (e.g., "Mac mini" instead of "macbook-pro-1")
- Count added if >1 of same kind ("Mac mini 2", "Mac mini 3")
- Tailscale addresses removed

## Testing

### Unit Tests
```bash
# Python unit tests for orchestration functions
python -m pytest brain-map/tests/test_deploy_snapshot.py -v
```

### Integration Tests
```bash
# Node.js tests with Playwright (requires Chrome)
# Validates export_snapshot.py + privacy filtering
node --test brain-map/tests/snapshot.test.mjs

# Validates deploy_snapshot.py + health checks
node --test brain-map/tests/deploy_snapshot.test.mjs
```

### Manual Testing

1. **Export only** (no deployment):
   ```bash
   python brain-map/export_snapshot.py
   ```

2. **Dry-run deployment** (validates without uploading):
   ```bash
   MARVIN_SNAPSHOT_ENABLED=1 python brain-map/deploy_snapshot.py --dry-run
   ```

3. **Force deployment** (ignores feature flag):
   ```bash
   MARVIN_SNAPSHOT_ENABLED=1 python brain-map/deploy_snapshot.py --force
   ```

4. **Check reactive trigger**:
   ```bash
   python brain-map/scripts/snapshot_deploy_reactive.py
   ```

## Troubleshooting

### "Portfolio dev site not running"
Portfolio Docker container must be running:
```bash
cd ~/portfolio-website-updater
docker-compose up -d
```

### "Privacy scan failed — refusing to export"
The export found a privacy leak. Review the error:
```bash
python brain-map/export_snapshot.py
# Read stderr for leak details
```

Common fixes:
- **Home paths**: check for repo-local vs. system-global paths in generated data
- **Tokens**: secrets shouldn't be in the tree data (check manifest.json generation)
- **Private projects**: verify they're marked non-PUBLIC in the catalog

### Snapshot not deploying automatically
1. Check if jobs are loaded: `launchctl list | grep snapshot-deploy`
2. Check logs: `tail ~/.claude/logs/deploy-snapshot-nightly*.log`
3. Verify feature flag is enabled in the plist files
4. Force a test: `MARVIN_SNAPSHOT_ENABLED=1 python deploy_snapshot.py --force`

### Snapshot not updating on website
1. Check Docker: `docker ps | grep portfolio`
2. Verify files in container: `docker exec portfolio-website-updater-wpcli-1 ls /var/www/html/wp-content/marvin-map/`
3. Check web server is serving them (browser dev tools, network tab)

## Future Work

- [ ] Static PNG screenshot (Playwright) for WebGL-less fallback
- [ ] CDN cache invalidation after deploy
- [ ] Integration with GitHub Pages for open-source snapshot hosting
- [ ] Real-time update path (push notifications, server-sent events)
- [ ] Analytics on snapshot views (opt-in, privacy-preserving)
