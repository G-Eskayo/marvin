# Health and metrics redo, 2026-10-21 (WIP: evidence gathered, design not written yet)

Status: work in progress. Paused because the MacBook went to sleep. These are the raw findings so far; the design sections come next.

## Evidence so far (measured 2026-10-21)

- **The Health sweep crashes when it can't reach a Mac.** Mini `jobs/health-check.json`: 3 of the last 20 runs failed (18:23, 21:21, 21:37 UTC), each with an uncaught `TimeoutExpired` from ssh to the MacBook (`check_sync_stuck` -> `_run_sync_log_remote`, `check_pipeline_breaker` -> `_run_failure_breaker_remote`). When a run fails, `health-status.json` isn't written and the tab keeps showing old data. `health-check-error.log` is 3.6 MB with 617 tracebacks, 607 of them the old `metrics_registry` "Extra data" crash.
- **Health on the MacBook is 6 days old.** `com.marvin.health-check` runs on the Mini only (`JOB_PLACEMENT`). The laptop dashboard reads its local `~/.claude/logs/health-status.json`, generated 2026-10-15T19:40Z. The 2012 box copies the Mini's file every 10 min through a systemd timer.
- **The webhook false alarm, root cause:** `_MACHINE_STATE_SCRIPT` runs `ps -o etimes=`, and macOS `ps` doesn't support that keyword ("ps: etimes: keyword not found"). So `ELAPSED` comes back empty and Health says "webhook-server is not running". `etime` exists.
- **`deploy:missing:mac-mini-1:snapshot-deploy` is a false red.** The jobs exit 0 in launchd, but the check looks for `~/.claude/logs/jobs/snapshot-deploy.json`, which those jobs never write.
- **`deploy:missing:macbook-pro-1:snapshot-deploy` is a false red.** It demands the plists on the laptop, but `JOB_PLACEMENT` says snapshot-deploy is Mini-only and must never run on the laptop.
- **`ticket:streak:*` can't fire.** It calls `gh issue list --label claimed:mac-mini,claimed:macbook-pro`, and gh ANDs the labels, so it matches nothing. It produced 0 results in today's status.
- **`tickets:project-tags`** has been stale for 282 h: `project-tags.json` was last written 2026-10-09. **`tickets:hold-revisit`** has never been written on the Mini.
- **The anomaly layer (the thing flooding git) has no consumer.** No dashboard code renders `anomaly`. It compares against one previous snapshot, not a rolling baseline. Today it reports "regressed" for the catalog age going from 1.2 to 1.4 h.
- **Coverage is 6/27 (22%), and the figure is misleading.** It counts Dropbox and Google updater plists, and it only counts `cron:*` log-scan checks, which come from cron_health's hand-listed `JOBS` (6 jobs). That's the same hand-list ADR 0033 rejected.
- **`jobs:placement`** stays yellow on both Macs because of table drift (`machine-resources` is listed as missing; `history-load`, `seal-beta-ingest` and `portfolio-dev-tunnel` aren't in the table).
- **Health is about 30% of the Mini's GitHub calls:** 4,000 of about 13,100 in 24 h (`pr list` 1,955, `issue list` 1,875, missed-purpose 85, graphql budget 85). Most of these come from `dispatch:parallel` and `profile:missing`, which re-derive what the ticket scanner already decided.
- **Sweep duration:** 64–99 s (median about 73 s) every 15 min.
- **`bench/metrics/health-monitor.mac-mini.json`** is 572 KB with 472 snapshots and no cap: each `record()` reads and rewrites the whole file, O(N), with unbounded growth. Readers: health_checks (the anomaly compare), `dashboard/electron/main/metrics.js` (benchmark cards) and `code_sync.py`'s metrics stash-merge special case. That merge code can be deleted once the files leave git.
- **`disk_forecast_notify`** pushes alerts through headless `claude -p` -> PushNotification. That depends on the subscription.
- **Reusable pieces:** ADR 0066's `history_store.events` schema (idempotent content hash, cursor per outbox), the mobile backend's `GET /health` and its `tailscale whois` device gate, and the webhook's `/refresh` relay.
- **Real alarms today (keep them):** main red, Mini disk at 8% free (7-day forecast to the 15 GiB threshold), 2012 GitHub sign-in expired (x640/day; currently only yellow), MacBook "gh down" x33 on approve.

## Next

Write the check audit table, the store design, the peer sharing design, the alerts, migration and phases; build the mock-ups; the outbox HTML page; the draft PR.
