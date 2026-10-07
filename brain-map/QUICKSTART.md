# Quick Start: Map v2 Snapshot Deployment (#188)

## What This Does

Automatically exports the MARVIN system map as a privacy-filtered, interactive snapshot for the portfolio website. Runs nightly and hourly (when the system tree changes).

## Files Added

```
brain-map/
├── deploy_snapshot.py                          # Main orchestration
├── scripts/
│   ├── snapshot_deploy_reactive.py              # Hourly change check
│   └── install-snapshot-jobs.sh                 # Job installer
├── launchd/
│   ├── com.marvin.snapshot-deploy-nightly.plist       # Daily 02:00
│   └── com.marvin.snapshot-deploy-reactive.plist      # Hourly
├── tests/
│   ├── test_deploy_snapshot.py                  # Unit tests
│   └── deploy_snapshot.test.mjs                 # Integration tests
├── SNAPSHOT_DEPLOYMENT.md                       # Full guide
├── SNAPSHOT_INTEGRATION.md                      # Website integration
├── IMPLEMENTATION.md                            # Summary
└── QUICKSTART.md                                # This file
```

## Setup (5 minutes)

### 1. Install Launchd Jobs

```bash
cd ~/.agents
bash brain-map/scripts/install-snapshot-jobs.sh
```

This installs two scheduled jobs:
- **Nightly**: Every day at 02:00 UTC (both mac-mini and MacBook)
- **Hourly**: Every hour on the hour (mac-mini only, if system tree changed)

### 2. Verify Installation

```bash
launchctl list | grep snapshot-deploy
```

You should see:
```
com.marvin.snapshot-deploy-nightly
com.marvin.snapshot-deploy-reactive    (only on mac-mini)
```

### 3. Test (Optional)

```bash
# Dry-run (export only, no deploy)
MARVIN_SNAPSHOT_ENABLED=1 python ~/.agents/brain-map/deploy_snapshot.py --dry-run

# Check logs
tail ~/.claude/logs/deploy-snapshot.log
```

## How It Works

1. **Export** — Runs `export_snapshot.py` to build the tree and apply privacy filters
2. **Validate** — Checks that files are well-formed and contain no private data
3. **Deploy** — Copies files to the portfolio website via Docker
4. **Health** — Records success/failure status for monitoring

### Privacy Checks

Before deployment, the snapshot is scanned for:
- Home directory paths (`/Users/...`)
- Private IP addresses
- Email addresses
- API tokens

If any leaks are found, deployment is blocked and the previous snapshot is kept.

## Status

The snapshot deployment status is saved in `~/.claude/health/snapshot-deploy.json`:

```json
{
  "timestamp": "2026-10-07T02:00:00+00:00",
  "status": "ok",
  "message": "deployed to /map-v2/"
}
```

The Health tab in the dashboard reads this file and shows:
- ✅ Last deployment: [timestamp]
- ⚠️ Snapshot deployment failed: [reason]

## Troubleshooting

### Jobs not running?

```bash
# Check if jobs are loaded
launchctl list | grep snapshot

# If missing, reinstall
bash ~/.agents/brain-map/scripts/install-snapshot-jobs.sh

# Check logs
tail ~/.claude/logs/deploy-snapshot-nightly-error.log
```

### "Portfolio dev site not running"

The portfolio Docker container must be running:
```bash
cd ~/portfolio-website-updater
docker-compose up -d
```

### "Privacy scan failed"

The snapshot export found a leak. Check the error:
```bash
tail ~/.claude/logs/deploy-snapshot-error.log
```

Common fixes:
- Verify private projects are marked in the catalog
- Check for hardcoded paths in tree data
- Ensure no secrets are in the manifest

### Snapshot not updating on website

1. Check Docker: `docker ps | grep portfolio`
2. Force a test: `MARVIN_SNAPSHOT_ENABLED=1 python ~/.agents/brain-map/deploy_snapshot.py --force`
3. Check website: `/map-v2/index.html` should be accessible

## Feature Flag

The snapshot deployment is **off by default**. To enable:

```bash
export MARVIN_SNAPSHOT_ENABLED=1
```

The launchd jobs have this flag enabled in their plist files, so they deploy by default. The flag exists for safety: manual runs won't deploy unless you explicitly enable it.

## Next Steps

1. [x] Install jobs
2. [ ] Verify installation
3. [ ] Check that portfolio dev site runs (`docker-compose up -d`)
4. [ ] Wait for first nightly run at 02:00
5. [ ] Check logs and website

For more details, see:
- `SNAPSHOT_DEPLOYMENT.md` — Complete setup and troubleshooting guide
- `SNAPSHOT_INTEGRATION.md` — Website integration details
- `IMPLEMENTATION.md` — Technical summary

## Related Issues

- **#187** — Map v2 (merged, prerequisite)
- **#136** — DesktopLive self-healing
- **ADR 0049** — Map v2 architecture
- **ADR 0050** — Snapshot design
