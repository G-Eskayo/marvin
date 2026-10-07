# MARVIN ticket triage — 2026-10-07 (APPLIED)

Repo: G-Eskayo/marvin, 97 open issues. Evidence gathered from GitHub issues/PRs, the dashboard source
(board.js, components/), lib/ (health_checks.py, dispatch_concurrency.py) and the installed app build.

## Outcome (applied 2026-10-07, approved by Gil: "do all")

- Open issues: 97 → 74. Closed 24 (16 done/superseded, 8 merged into keepers); 21 put on `hold`; 1 new ticket (#213).
- **#213** — Holds come back: an "On hold" group on the board, a `Revisit by:` line, and a `revisit` agent.
  Until #213 ships, find held tickets on GitHub with `label:hold` (they sit in Backlog as "On hold" on the board).
- Every hold has a comment ending in `Revisit by: <date> — <condition>` (the format #213 will parse).
- #174 → ready-for-human (only the manual sleep/wake check is left). #94's stale `claimed:macbook-pro` released.
- #62's promotional comment hidden as spam. The `hold` label didn't exist on the repo; it was created.
- Brain-map question (#30, #31, #45) still open: held until Map v2 ships (by 2026-10-31), then keep or close as not planned.

## Revisit schedule (holds)

| Revisit by | Tickets | Condition |
|---|---|---|
| 2026-10-26 | #93, #94, #97, #102 | After clarity-captions ships; do in working sessions (doc-first), not the pipeline |
| 2026-10-31 | #30, #31, #45 | Or when Map v2 (#178–#181) ships; decide keep vs not planned |
| 2026-11-01 | #28, #38 | Retry-storm design work; do in a working session |
| 2026-12-01 | #44 (with #51), #47, #48, #49, #50, #51, #52, #56 (or when Mobile Voice ships), #65, #66, #67, #68 | Parked research |

## Key findings

- PR #140 "Board accuracy" (merged 2026-10-06) already fixed most of #139 and #127, but used `Refs`, not `Closes`,
  so both stayed open. Installed MARVIN Metrics.app was rebuilt 2026-10-07 09:57, after the merge, so the fix is live.
- What the board now calls "blocked" is mostly **"Pipeline failed"** — tickets the pipeline retried until it gave up.
  Failure-comment counts: #28 = 1,644 · #30 = 1,247 · #94 = 456 · #31 = 280 · #102 = 119 · #97 = 114 · #38 = 13 · #93 = 8.
  Last ones 2026-10-01..06. These are design/research-shaped tickets the verifier can't measure ("verdict: unchanged").
- #62 has a third-party promotional comment ("Try Sendmux", user roshanjonah).

## A. Close — already done or superseded
| # | Title | Why |
|---|---|---|
| 1 | MR pipeline PRD | All 10 split-out children done; remaining follow-ups stand alone |
| 109 | PRD: Activity Board + mac-mini migration | #110–#117 done; only #118 left, stands alone |
| 127 | Activity tab only shows MARVIN's tickets | Fixed in PR #140 |
| 139 | Boards show a misleading picture | PR #140: hold, not-planned, progress chip, merged-PR evidence, freshness; stale-claim sweep already existed |
| 128 | Pipeline: check what exists, respect a hold | Hold + merged-PR scanning landed in PR #140 |
| 132 | Disk-space guard | dispatch_concurrency `min_disk_gb: 15` + Health disk yellow/red at 20%/10% |
| 136 | Desktop background sometimes not shown | Duplicate of Map v2 #174–#177 (#177 records #136's cause) |
| 195 | Parallel dispatch: scan fills free slots | Built directly, commit 702274d |
| 120 | Worktree paths break Vite (# in dir) | Paths are now `pipeline-g-eskayo-marvin-N`, no `#` |
| 33 | WhatsApp/Telegram companion | Superseded by MARVIN Mobile PRD #152 |
| 42 | Decision: automatic profile routing | Decided: auto-route hook (ADR 0023) |
| 58 | Self-hosted tunnel research | Decided: ngrok static domain + Tailscale |
| 64 | SCRUM-master orchestration agent | Covered by to-tasklist skill, #93/#94, ADR 0052 dispatch |
| 69 | Automated design-doc pipeline | Overlaps #93/#94 + ticket agents |

## B. Verify, then close (verified 2026-10-07: #72 and #121 closed, #174 → ready-for-human)
| # | Title | Check |
|---|---|---|
| 72 | MR-review detail + deny | MrDetail.jsx + Deny modal exist; confirm the PR evidence schema |
| 121 | Portfolio review tab | Portfolio tab exists with screenshots + apply-to-dev; only "approve → production" may be missing → narrow or close |
| 174 | DesktopLive logs why it did/didn't draw | Built; only Gil's manual sleep/wake check left → ready-for-human |

## C. Put on `hold` — retry-storm tickets (stop them showing as blocked)
#28 Hard/ambiguous bench task design · #30 Brain-map same-category pass · #31 Brain-map semantic-similarity pass ·
#38 Bootstrap redundancy sweep · #93 Persisted design doc per ticket · #94 Task list from design doc (also drop stale
`claimed:macbook-pro`) · #97 VERSION + CHANGELOG bump · #102 Suggestions tab.
Follow-up: the pipeline needs a "stop after N failures and hold" rule so this can't recur (fold into #73).
Question: are the brain-map passes (#30, #31, + decision #45) still wanted after Map v2? If not → not planned.

## D. Merge duplicates
| Keep | Fold in | Topic |
|---|---|---|
| 63 n8n as external nervous system | 59, 60, 61 | n8n's role in MARVIN |
| 130 Machine resources panel | 131, 135 | Disk/memory/CPU in Health; reclaim via existing cleanup sweep |
| 96 code-review as second merge gate | 92, 34 | Second reviewer at merge time |
| 57 Terry feasibility | (new: Health + tool-usage feeds as inputs) | Terry |

## E. Park research spikes with `hold` (untouched since 2026-08-27)
#47 FastMCP caching · #48 Live RAG · #49 TensorRT/vLLM · #50 KV/flash/paged attention · #51 ChromaDB benchmark ·
#52 JEPA · #56 voice profile · #65 prompt distillation · #66 Haiku probing · #67 harness-creation reframe ·
#68 Vertus · #44 HNSW vs IVF.
Keep active: #53 cloud agents, #54 research↔colony, #55 concept clustering, #57 Terry.

## F. Housekeeping
- #62 Recruiter/email + bill-parsing: hide the promotional comment as spam.

## Leave as is
Mobile (#152–#167), Map v2 (#175–#189), parallel dispatch (#196–#199), onboarding #150, #149, #126, #118, #96, #81,
#73, #89, #39, #40, #27, #36, #133, #134, #192.
