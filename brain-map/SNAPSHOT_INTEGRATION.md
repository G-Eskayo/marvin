# Map v2 Snapshot Integration Guide (#188, ADR 0050)

## Overview

The MARVIN map snapshot is deployed to the portfolio website (`portfolio-website-updater` repo) at `/map-v2/` with:
- **Interactive version** (`index.html`): Full 3D map, clickable, requires WebGL
- **Data layer** (`tree-data.json`): System and code layer data for the interactive view
- **Static fallback image** (`map-snapshot.png`): For browsers without WebGL and for page cards

## File Structure

The `deploy_snapshot.py` script deploys to the portfolio at:
```
wp-content/marvin-map/
  ├── index.html          # Interactive snapshot (WebGL required)
  ├── tree-data.json      # Data for the interactive map
  └── map-snapshot.png    # Static fallback image (generated separately)
```

## Integration Steps

### 1. Portfolio Website Template (portfolio-website-updater repo)

On the MARVIN project page (`/marvin/` or the hero section), implement WebGL detection:

```html
<!-- Example: Hero section with WebGL fallback -->
<div id="map-container">
  <!-- If WebGL is supported, load the interactive snapshot -->
  <iframe id="map-frame" 
          src="/map-v2/index.html" 
          width="100%" 
          height="600"
          style="border: none; display: none;"></iframe>
  
  <!-- Fallback image for no-WebGL browsers -->
  <img id="map-fallback" 
       src="/map-v2/map-snapshot.png" 
       alt="MARVIN system map" 
       width="100%" 
       style="max-width: 100%; height: auto;">
</div>

<script>
  // Detect WebGL support
  function hasWebGL() {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      return !!gl;
    } catch(e) {
      return false;
    }
  }
  
  // Show interactive version if WebGL is available
  if (hasWebGL()) {
    document.getElementById('map-frame').style.display = 'block';
    document.getElementById('map-fallback').style.display = 'none';
  }
</script>
```

### 2. Card Image

For the MARVIN project card (on All Projects and hubs), use the static fallback image:

```json
{
  "url": "/marvin/",
  "thumbnail": "/map-v2/map-snapshot.png",
  "title": "MARVIN",
  ...
}
```

### 3. Snapshot Generation

The `export_snapshot.py` script generates `index.html` and `tree-data.json` automatically.

**Static image generation** is handled separately:
- A Playwright screenshot script can capture the map at a standard viewport size
- This is run as part of the deployment pipeline (scheduled nightly or on-demand)
- The resulting PNG is stored alongside the interactive files

## Feature Flag

The snapshot deployment is controlled by the `MARVIN_SNAPSHOT_ENABLED` environment variable:

```bash
# Enable deployment (set in launchd jobs or manually)
export MARVIN_SNAPSHOT_ENABLED=1
python deploy_snapshot.py

# Bypass the flag if needed
python deploy_snapshot.py --force
```

## Health Checks

Deployment status is recorded in `~/.claude/health/snapshot-deploy.json`:

```json
{
  "timestamp": "2026-10-07T15:30:00+00:00",
  "status": "ok",
  "message": "deployed to /map-v2/"
}
```

The Health tab monitors this file and alerts if:
- Status is "error" (privacy leak or deployment failure)
- Deployment hasn't succeeded in the last 24 hours (for nightly job)

## Privacy & Security

The snapshot goes through multiple validation gates:

1. **allowlist-based code filtering**: Only files tracked in `G-Eskayo/marvin` at the deployed commit
2. **Private project locking**: Non-PUBLIC projects show as locked nodes (named but not openable)
3. **Privacy scanning**: Refuses to deploy if it contains:
   - Home directory paths (`/Users/...`)
   - Private IPv4 addresses
   - Email addresses
   - Token patterns (sk-ant-, gh_*, etc.)
4. **Machine anonymization**: Device hostnames are replaced with kind + count (e.g., "Mac mini 2")

## Deployment Schedule

- **Nightly (02:00 UTC)**: `com.marvin.snapshot-deploy-nightly.plist` — full rebuild and deploy
- **Hourly reactive (every :00)**: `com.marvin.snapshot-deploy-reactive.plist` — check if system tree changed; deploy only if so

Both jobs log to `~/.claude/logs/deploy-snapshot*.log`.

## Troubleshooting

### "Portfolio dev site not running"
The deployment requires the portfolio's Docker container (`portfolio-website-updater-wpcli-1`) to be running.
```bash
# Start the portfolio dev site (from portfolio-website-updater repo)
docker-compose up -d
```

### Privacy leak detected
The snapshot export failed privacy validation. Check the error log:
```bash
tail ~/.claude/logs/deploy-snapshot-error.log
```
Common causes:
- Untracked files in the repo (add to `.gitignore`)
- Private project listed in the system tree but not in the catalog (remove or mark as private)
- Test files with hardcoded paths (add exclusion to `scan_for_leaks()`)

### Snapshot not updating on the website
1. Check if the nightly job ran: `launchctl list | grep snapshot-deploy`
2. Check the log for errors: `tail ~/.claude/logs/deploy-snapshot-nightly-error.log`
3. Force a deployment: `MARVIN_SNAPSHOT_ENABLED=1 python deploy_snapshot.py --force`
4. Verify files were deployed: check `wp-content/marvin-map/` in the dev site

## Future Work

- [ ] Automatic PNG screenshot generation via Playwright
- [ ] Cache busting strategy for the snapshot on the portfolio (etags or CDN invalidation)
- [ ] Open source the snapshot on static hosts (GitHub Pages, etc.)
