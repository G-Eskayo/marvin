# Retrospective Log

Cross-skill pattern index. One line per self-improve run. Written by the self-improve skill.

| Date | Skill | Type | Summary |
|------|-------|------|---------|
| 2026-07-02 | diagnose | I | Added two verified gotcha classes (cron/launchd PATH loss; hook matchers not path-scoped) from the MARVIN feature-inventory audit |
| 2026-07-03 | diagnose | I | Added a third gotcha class (raw deletions bypass hooks, leaving derived state like manifest.json stale) from live-tested brain-map/hook work |
| 2026-07-03 | diagnose/self-improve/write-a-skill | I/S | Added 3 gotchas (claude.json clobbered by long-running session's own state flush; deploy-script glob/copy gaps; menu-bar app needs a real .app bundle for LSUIElement); closed the 2026-07-02 empty-log F with the new background reviewer + integrity checker; added an autonomy-claim verification item to write-a-skill's checklist
| 2026-07-06 | diagnose | I | Added gotcha: unrestricted `claude -p` in scheduled scripts can silently attempt Write/Edit, get denied, and narrate the failure into report output — fix via `--disallowedTools`; hit independently in both daily_digest.py and research_digest.py, confirming recurrence within one session |
| 2026-07-07 | diagnose/handoff | I/F | Added diagnose gotcha: local model servers' "OpenAI-compatible" APIs are usually partially compatible (mlx_lm.server lacks `echo`, breaking an lm-eval harness built assuming full compat) — fix is an in-process adapter, not an HTTP layer; added handoff rule to flag session-scratchpad artifacts needing a durable home, from a benchmark script that would've been silently lost otherwise |
| 2026-07-08 | n8n-workflow-architect | I | Added 3 verified gotchas from the shipped Marlin automation: Structured Output Parser unreliable on small local models (use plain JSON + Code node parser instead); Telegram node has no true plain-text mode (must set parse_mode:HTML + escape); Ollama numCtx/numPredict defaults are pure unused-allocation overhead, tuning down cut latency ~33% |
