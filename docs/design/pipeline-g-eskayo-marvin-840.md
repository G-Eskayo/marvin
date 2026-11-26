Now I have enough context to write the plan.

## North-star fit

**Reuses:** the `portfolio-page` skill end-to-end (`~/.agents/skills/portfolio-page/SKILL.md`) and its ADR 0051 machinery — `lib/portfolio_content.py::evaluate`/`findings_for_evaluation` (coverage, AI-phrase/em-dash, alt-text, figure, MARVIN-link checks) and `lib/portfolio_eval.py::run` (geometry/overflow checks via Playwright) — exactly as ticket #393 (Clarity Captions rebuild) used it. MARVIN already has a long-form page and `content/longform/marvin.json` with a recorded `content_type` from the 2026-10-06 build (ADR 0051 context); this is an **edit of that existing content file**, not a new page, so `portfolio_longform.py --rollback` + `--author` (not `--add-project`) is the right tool. Diagrams reuse the existing `setup`/`run` diagram kinds via `portfolio_diagrams.py`, not new tooling. Voice rules reuse `writing-style`'s "Portfolio register" section verbatim rather than inventing new guidance.

**Simplest sufficient approach:** no new code. This ticket is a content-authoring run through an already-built pipeline (templates, checks, evaluator, Portfolio tab). The only work is fact-gathering, evidence capture, copy, and running the existing tools — adding scaffolding here would contradict ADR 0051's "templates are data, checks and skill live in MARVIN" decision.

**Resources:** spends a small amount of tokens on fact verification and copywriting; spends Playwright/Docker compute on the mac-mini only (the one machine that runs the dev site — ADR 0003), never the laptop or box. No new persistent cost.

**User capability:** this doesn't automate a judgment Gil should keep — it's catching the site up to reality so a recruiter/hiring manager sees what MARVIN actually does today. Net effect is informational accuracy, not taking a decision off Gil (deploy to production stays his manual step per the ticket).

**Decisions:** none needed. Audience depth, voice, and "portfolio vs product-site" split are already settled (`feedback-tailor-pages-to-audience`, `feedback-portfolio-copy-sell-it`); template type and current page state are facts to read at build time, not choices for Gil.

## Context from the prior failed attempt

The retry comment (`gh issue view 840 --comments`) gives no specifics — "code review found must-fix issues" after 3 iterations, no PR number, no branch, no diff to inspect (none exists on this branch; it's unchanged from `main`). I cannot recover what specifically failed. I'm treating this as: build defensively against every failure mode the ticket and the skill's own retrospective (`retrospective.md`'s "check the other direction" lesson — under-claiming, missing links, missing manifest entries) already name, rather than guessing at a single root cause.

## Tests (verification checks) written FIRST

This is a content-authoring ticket, not application code — "tests" are the verification passes that must exist and must fail on a bad draft before the page is called done:

1. **Claim-traceability check:** every sentence making a factual claim gets a logged source (repo path / merged-PR number / log file / dashboard screenshot timestamp) in a claims-to-sources worksheet. A claim with no mapped source is cut, never shipped on a hedge. Verify the check itself by planting one invented/unverifiable claim in a first draft and confirming it gets caught and removed before the page is authored.
2. **Privacy scan on every new screenshot and on the copy itself:** no private names, no phone numbers/emails/IPs, no local paths (`~/Developer/...`, `~/.agents...`), no bare hostnames. Look at the blurred result before using it, per the skill.
3. **Content evaluator, zero findings:** `lib/portfolio_content.py --json` against the updated `content/longform/marvin.json` — no AI-phrase/em-dash hits, every image has alt text, at least one evidence figure, template coverage complete, MARVIN-links-both-ways satisfied.
4. **Layout evaluator, zero findings for the marvin page:** `lib/portfolio_eval.py` run against the dev site — no footer/grid/overflow/github-button/image findings tied to `/ai-projects/marvin/`.
5. **Explicit 860px and 1440px screenshots:** the AC's exact numbers don't match `portfolio_rules.DEFAULT_RULES`' configured viewports (`[1440, 1100, 390]`), so check the portfolio repo's actual `templates/design-rules.json` first; whatever it says, still capture scrolled (lazy-load-safe) full-page screenshots at exactly 860px and 1440px and confirm no overflow, no cut-off text, no broken images, bump `brand.css?v=` if styles changed.
6. **Recovery-path check before touching the live page:** confirm `portfolio_longform.py <marvin-url> --plan` reports it as already long-form, and that `--rollback` actually writes the before-rollback snapshot to `~/.claude/outbox/migrations/marvin/` before the real `--author` run — tested, not assumed.
7. **Dependency-failure handling:** each tool in the chain (`portfolio_longform.py`, `portfolio_diagrams.py render`, image generation, Docker dev containers, wp-cli write via `portfolio_apply.wp_base()`) is checked for a real success exit, not just "it printed something" — a Docker-down or wp-cli-auth failure halts the run rather than silently completing.
8. **Stale-mount check:** confirm (`docker inspect` on the mount source) that writes land in `~/portfolio-dev/wordpress/html`, not the repo's own `wordpress/html` copy, before trusting any screenshot of the result (`portfolio-dev-site-mount-path` gotcha).
9. **Single-writer check:** the dev site DB is one Docker volume on one machine; confirm no other session has an uncommitted diff in the portfolio repo or a dev site mid-edit before authoring, to avoid clobbering concurrent work.
10. **Oversized-asset check:** at least one dashboard screenshot is checked for file size/compression and lazy-load markup before it ships (mirrors #393's "images and GIFs load fast" bar, which #840 doesn't restate but the skill and ADR 0051 both require).
11. **No-production-push guard:** after authoring, confirm nothing in the session commits/pushes `deploy/` in the portfolio repo (which would auto-FTP-deploy to production) — `git status`/`git log origin/main..HEAD --stat` in that repo stays clean of any such push; promotion stays Gil's manual step per the ticket.

## Task List

1. On the primary development machine, read the current `content/longform/marvin.json`, its `content_type`, and the rendered `/ai-projects/marvin/` dev-site page, to see exactly what's stale.
2. Gather and verify today's facts against the repo/logs: pipeline throughput and the ticket-to-merged-PR flow (CONTEXT.md's MR pipeline / stage-strip / merge-queue sections, recent merged-PR counts via `gh`), the dashboard (Workshop, Vitals), MARVIN Mobile status (ADRs 0039–0046 — note what's shipped vs. "in design"), the voice endpoint's real state (ticket #670 / PR `voice-endpoint-670` is still **open**, not merged — don't claim it as shipped), and the multi-Mac setup (Mini + laptop + box, peer care). Build the claims-to-sources worksheet (test 1) as this happens; cut anything that can't be sourced.
3. Check the other direction (retrospective lesson): look for MARVIN capabilities already real in the repo that the old copy under-claims or omits entirely.
4. Capture fresh evidence: current dashboard screenshots (Workshop/Vitals, after quitting the installed app first per the skill), any numbers pulled straight from logs, and diagrams for the pipeline/dashboard architecture via `portfolio_diagrams.py` (`setup`/`run` kinds). Run the privacy pass (test 2) on every image before it's used anywhere.
5. Write `content/longform/marvin.json`: update `lead_html` and `sections` in Gil's portfolio voice (writing-style skill's "sell it" register), honest status on anything still in design, linking out to Seal Speak / other MARVIN-built pages where relevant.
6. Author on the dev site: `portfolio_longform.py <marvin-url> --plan`, then `--rollback`, then `--author content/longform/marvin.json` (tests 6–9 run around this step, not after it).
7. Run `portfolio_sync_dev.py` (sync, pages, capture, parity, evaluate) and `lib/portfolio_content.py --json`; fix anything either flags (tests 3–4) before moving on.
8. Capture full-page, scrolled screenshots at 860px and 1440px specifically (test 5); re-run the privacy pass on these too.
9. Re-read the final copy against the writing-style avoid-list one more time.
10. Confirm no `deploy/` push happened (test 11), then report to Gil what changed, link the dev-site page and screenshots via `marvin-show` (never a file card or temp path), and name anything left uncommitted in the portfolio repo or any claim that got cut for lack of a source.