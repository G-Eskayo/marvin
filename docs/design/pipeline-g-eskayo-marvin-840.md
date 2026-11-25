I now have everything needed to write the plan.

## North-star fit

This is a content-authoring task, not a build: it reuses the `portfolio-page` skill end-to-end (`~/.agents/skills/portfolio-page/SKILL.md`), the existing `system` content template (`templates/content/system.json`), the current `content/longform/marvin.json` as the base to edit in place, and the `lib/portfolio_*.py` toolchain (`portfolio_longform.py`, `portfolio_sync_dev.py`, `portfolio_eval.py`, `portfolio_diagrams.py`) already built for exactly this job. No new tooling, template, or component is needed — the GUIDE.md's "shape of every Project Page" and the evaluator already cover it. It is the simplest sufficient approach: edit the JSON content source, regenerate/reshoot the figures that drifted, re-author, re-evaluate. It spends tokens/time on fact-verification (grep/gh/CONTEXT.md reads) rather than guessing, which is cheaper than shipping unverifiable claims that get sent back. It leaves Gil more capable: an accurate page he can point recruiters at without having to fact-check it himself, which is the whole point of the ticket (the current page silently drifted).

Checked the ticket's own framing against the code: it's correct — `content/longform/marvin.json` is real and detailed-looking, but verifiably stale in at least two ways: (1) `dashboard/src/lib/tabs.js:1-9` has 7 tabs (Metrics, **Workshop**, MR Review, Health, Docs, Activity, Portfolio), while the page's "The dashboard" section still describes "Six tabs" and never mentions Workshop; (2) the page never mentions phone or voice at all, though `docs/adr/0039–0046` (MARVIN Mobile) and `docs/adr/0001-0005, 0075` (MARVIN Voice) are real, substantial efforts the ticket explicitly asks to cover.

## Decisions
<!-- marvin:decisions -->
### narrow-viewport: How should the "860 px" acceptance criterion be satisfied?
- [x] **A: PROCEEDING** — Manual headless-Chrome screenshot at 860 px (Gil's Mini width). No code change.
- [ ] B: Add 860 px to the evaluator's shared viewport list in `portfolio_rules.py`

### machine-count: How many machines does "several Macs" cover on the page?
- [ ] A: Keep "two Macs" (Mini + MacBook) if mac-mini-2012 is still pull-only/in-design
- [x] **B: PROCEEDING** — Three machines. ADR 0082 (2026-10-30) granted mac-mini-2012 memory/handoff; now operational.

### mobile-voice-status: How to phrase MARVIN Mobile and MARVIN Voice given they may not be shipped
- [x] **A: PROCEEDING** — Brief mentions of both as in-progress/private-beta. Neither currently shipped.
- [ ] B: Voice gets full section if daily use; Mobile stays one line

## Tests (written first)

Since this is a content/authoring ticket, not application code, "tests" are the pipeline's own automated and scripted checks that gate the page, run before any claim is called done:

1. **Fact-trace test**: for every claim kept in the rewritten `marvin.json`, a one-line source note (file, PR #, or command output) exists in the build log — mirrors "a claim with no source is removed."
2. **Evaluator pass — standard widths**: `portfolio_eval.py` run against the dev site returns 0 findings for the MARVIN page (layout, media, content checks) — covers 1440/1100/390 px per `portfolio_rules.py`.
3. **Evaluator pass — narrow width**: per the Decision above, either a 4th evaluator pass at 860 px or a manual headless screenshot at 860 px shows no horizontal overflow and no clipped/overlapping elements (mirrors "Narrow layout checked on the Mini").
4. **Privacy test**: every new/retaken screenshot run through the existing blur pass, then visually re-checked for phone numbers, emails, clearance text, private project names (see CONTEXT.md "Private projects" section or the instance/ folder for the denylist), tokens, and credential paths before authoring — mirrors GUIDE.md's privacy pass and `feedback-no-private-names-in-public-repos`.
5. **Staleness test**: every screenshot's capture timestamp is this week (≤7 days before authoring) — catches a reused old image passing review by accident.
6. **Stale-numbers test**: every `data-fact` span (`skills`, `tests`, `prs_merged`, `agents`, `decisions`, `machines`, `counted_on`) is recounted from the live repo/GitHub/`facts.json` pipeline at build time, not left as the old typed values — catches the exact failure mode this ticket exists to fix.
7. **No-AI-phrasing / no-em-dash test**: re-read against the writing-style avoid list — the evaluator's content check plus a manual pass, since the tool can't catch every phrase.
8. **Link-integrity test**: "Built with MARVIN" links (Resume Tailor, Paper Dive, Clarity Captions, this site) still resolve and still link back to the MARVIN page; any add-on page link (Voice/Mobile) added this round also resolves or is omitted if it doesn't exist yet.
9. **Rollback-safety test**: before authoring, confirm the page is already long-form (`portfolio_longform.py <url> --plan` should NOT say "not a project-page layout page"); if it is, `--author` directly — a `--rollback` is only run if `--plan` shows otherwise, and its auto-saved backup is verified to exist afterward.
10. **Concurrent-editor test**: before writing, `git log` the portfolio repo's `content/longform/marvin.json` and `dashboard-*.jpg` figures for any uncommitted/very recent change by another session (shared repo, shared Mac mini dev site) — don't clobber live in-progress work.
11. **Misuse case — no Docker**: if the mac-mini dev site's containers aren't up (`bin/dev-up.sh` not run / Docker Desktop down), authoring and evaluation fail closed with a clear error, not a silent stale read — check before starting.
12. **Misuse case — single dev-DB instance**: confirm no other machine/session is also running the dev site against the same Docker volume at the same time (ADR 0003: one machine at a time), since that would corrupt or race the edit.

## Task List

1. Re-verify current facts, superseding this plan's snapshot where stale: dashboard tab list (confirm Workshop status/wording), MARVIN Mobile status (`~/Developer/marvin-mobile`, ADRs 0039-0046, CONTEXT.md "MARVIN Mobile" section), MARVIN Voice status (`~/Developer/marvin-voice` if reachable, ADR 0072/0075), machine count (`mac-mini-2012` status), and recount every `data-fact` value (skills, tests, prs_merged, agents, decisions, machines, counted_on) from the repo/GitHub/`facts.json` pipeline.
2. Resolve the three Decisions above (or proceed on the stated default if the owner hasn't answered by build time and note the assumption made).
3. On the mac-mini dev site: confirm Docker/dev-up is running and no other session holds it; `git log` the portfolio repo for concurrent edits before touching anything.
4. Diff the current "The dashboard" section's six screenshots against the live app; retake all six (plus any new tab, e.g. Workshop) this week via Playwright `_electron`, run the privacy/blur pass, and visually re-check each before use.
5. Rewrite `content/longform/marvin.json`: update "The dashboard" section/images for the current tab set; add or revise coverage for phone (MARVIN Mobile) and voice (MARVIN Voice) per the resolved Decision; update every `data-fact` value and `counted_on` date; re-check the pipeline PR chart, failure-causes chart, and bench table against current numbers (regenerate or re-caption if stale) — cut any claim with no fresh source.
6. If a new mechanism needs a diagram (e.g. phone/voice architecture) build it with `portfolio_diagrams.py` using the house Mermaid theme; otherwise reuse existing `context.svg`/`pipeline.svg`/`system.svg` if still accurate, or regenerate if the architecture changed.
7. Re-read the full rewritten copy against the writing-style "Portfolio register" and GUIDE.md rules (sell it, two readers, proof over adjectives, no competitor names, honest status, no em-dashes/AI phrasing).
8. `portfolio_longform.py marvin --plan` (dry run), then `--author content/longform/marvin.json` (via `~/.agents/venv/bin/python` on the mac-mini).
9. Run `portfolio_sync_dev.py` (sync, pages, capture, parity, evaluate); confirm the Portfolio tab shows "complete" content and a clean Evaluation.
10. Run the narrow-width check per the resolved Decision (860 px evaluator pass or manual screenshot); screenshot the full page at 860 px and 1440 px after scrolling (lazy-loaded images).
11. Run the privacy/no-private-names scan one more time over the final authored page and all figures before reporting done.
12. Report to Gil via `marvin-show` with both-width screenshots, what changed, what's uncommitted in the portfolio repo, and the three Decisions for his answer; do not push/deploy (production deploy stays his manual step).