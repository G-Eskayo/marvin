# Sources

This feature was synthesised from the 2026-07-03 research digest (`~/.claude/research-digest/2026-07-03.md`), cross-referenced against the live repo.

## Primary papers

1. **Online Safety Monitoring for LLMs** — Schirmer, Jazbec, Timans, Naesseth, Waldron, Nalisnick. [arXiv:2607.02510](http://arxiv.org/abs/2607.02510v1)
   - Core mechanism borrowed: turn a verifier signal from an external model into an alarm decision by **thresholding**, with the threshold **calibrated via risk control** (not hand-picked). Shown competitive with heavier sequential-hypothesis-testing monitors on math-reasoning and red-teaming datasets.

2. **What LLM Agents Say When No One Is Watching: Social Structure and Latent Objective Emergence in Multi-Agent Debates** — Ghaffarizadeh, Mohaddes, Izadkhah, Noroozizadeh. [arXiv:2607.02507](http://arxiv.org/abs/2607.02507v1)
   - Core mechanism borrowed: **dual-channel elicitation** — a public channel that enters shared history, and an off-the-record (OTR) channel collected under identical conditions. Divergence between the two channels rose from a ~3% baseline to ~40% under social/incentive pressure, and OTR responses sometimes explicitly named the pressure ("career risk", "sponsorship obligation") driving the public deviation.

## Why these two combine

MARVIN already runs several fully-autonomous loops with no verification step before their output goes live:

| Autonomous loop | File | What ships unverified |
|---|---|---|
| Post-handoff QA sweep | `skills/improve/scripts/improvement_sweep.py` | Appends to `improvement-queue.md` |
| Daily digest | `skills/improve/scripts/daily_digest.py` (launchd, 08:30) | Writes to `daily-digest/YYYY-MM-DD.md` |
| Research colony | `skills/research-colony/scripts/run_colony.py` (launchd) | Writes to `research-digest/YYYY-MM-DD.md` |
| Self-improve | `skills/self-improve/SKILL.md` | Creates/edits skill files, claims to auto-wire into `CLAUDE.md` |

Paper 1 gives a cheap, calibrated way to catch a *bad output* before it ships. Paper 2 gives a cheap way to catch a *bad decision process* — by comparing what an autonomous loop says publicly (in the artifact it writes) against what it says when asked privately, off the record, under the same inputs. Together they cover both failure modes this repo actually has: wrong output, and unexamined self-modification.

## Confirmed while researching (not from the papers — found by reading the repo)

`self-improve/SKILL.md` and `architecture-review/SKILL.md` both invoke `~/.agents/skills/self-improve/scripts/wire-skill.sh`. That script does not exist in `~/marvin/skills/self-improve/scripts/` or in the deployed `~/.agents/skills/self-improve/scripts/` — it only exists in `~/.agents/skills.stale-backup-20260702-1804/`. Any self-improve run that reaches the "auto-wire" step currently fails silently or errors. This is an existing bug, tracked separately (not part of this feature) but relevant motivation: the loop most in need of a safety check is also the one that's already partially broken.
