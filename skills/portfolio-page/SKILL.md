---
name: portfolio-page
description: Build or rebuild a project page on gileskayo.me from a content template, end to end on the dev site — verified facts, real evidence (screenshots, outputs, charts, diagrams), copy in Gil's portfolio voice, authored as a long-form page and checked by the pipeline. Use for "add X to the portfolio", "rewrite the X page", "this page needs evidence/diagrams", "make the portfolio page for X".
tags: [intent:write, intent:portfolio, intent:document, type:skill]
---

# Portfolio page

Decisions: MARVIN ADR 0051 (content templates and checks). Rules: the portfolio repo's `templates/GUIDE.md` (also the Guide & rules tab). Voice: the `writing-style` skill's "Portfolio register: sell it". Everything happens on the **dev** site. Never push the portfolio repo: `deploy/` auto-deploys to production and Gil decides when.

Paths: portfolio repo `~/Documents/Projects/portfolio-website-updater` (the dev site and its repo work happen on the mac-mini, `ssh gils-mac-mini`); MARVIN tools in `~/.agents/lib/portfolio_*.py`. Run them with `~/.agents/venv/bin/python`: the system `python3` lacks Playwright and bs4, so rendering and authoring fail under it.

## 1. Pick the template
Choose the page type and read its template in `templates/content/`: `skill-tool`, `app-product`, `system` or `ml-study`. The template gives the lead's job and the sections in order, each with a `role` and the evidence it needs.

## 2. Gather and check every fact
Write down each claim you mean to make and where it was checked: stacks against the code (package.json, imports, languages), counts from the repo or GitHub, usage from real outputs, "the pipeline built it" against merged `pipeline/...` PRs. If a claim can't be checked, cut it. Read the current page first; old copy often states stacks or features the code doesn't have. The repo's own docs aren't proof either: run the test suite rather than quoting a README or submission count (the Hackathon's submission said "211 passing"; the suite has 206, 6 failing). And ask Gil anything only he knows, such as whether it was solo or a team.

Check the other direction too: the repo often has stronger material than the page uses. Look for a headline feature the copy never names (Mancala's notebook has a real minimax AI with alpha-beta pruning, and the old page never said so), charts and figures already in the repo (a confusion matrix, an engagement distribution), metrics the page leaves out, and links that should be there (a GitHub repo, a hub parent, a manifest entry and card for a page published outside the manifest). Lead with the strongest checked thing you find.

## 3. Capture the evidence
- **App screenshots:** a debug-only demo mode in the app (Clarity: `-ClarityDemo`, `-ClarityDemoStatic`, `-ClarityDemoSettings`), the iPhone simulator, `xcrun simctl status_bar ... override --time 9:41`, `xcrun simctl io <udid> screenshot`. Resize to 600 px wide.
- **Dashboard screenshots:** quit the installed MARVIN Metrics app first (its single-instance lock makes a second launch hang), drive the built app with Playwright `_electron`, then reopen it.
- **Real outputs:** render PDFs with `qlmanage -t -s 1700`. When the original output is gone (a dead demo deployment), run the repo's own code path from a script outside the repo, record exactly what it returned, render that as a table image (HTML through Playwright at 2x), and caption it with the date and what the data is (the Hackathon deal log).
- **Looking at a diagram:** don't use `qlmanage` on a wide SVG (it crops to a square thumbnail). Open the SVG directly in Playwright (`page.goto(file_uri)`) and take a viewport screenshot; `full_page=True` hangs on a bare SVG document.
- **Privacy pass, always:** blur phone, email, security clearance, private project names (finance-os, the Fellows paper), tokens and credential paths. Look at the blurred result before using it.
- **Charts:** load the `dataviz` skill first; validate the palette; real data only; direct labels and a `<title>` hover on every mark.
- **Diagrams:** `portfolio_diagrams.py new <slug> setup run marvin`, edit the sources in `docs/diagrams/<slug>/` (keep only checked links), then `portfolio_diagrams.py render <slug>`. Wide diagrams go full width, tall ones beside their text.

Figures go in `deploy/longform/figures/<slug>/`; card thumbnails in `deploy/uploads/generated/` (800x500, matching the hero).

## 4. Write the page
Write `content/longform/<slug>.json`: `subtitle`, `lead_html`, `content_type`, `built_with_marvin`, and `sections` as `{heading, role, body_html}` in template order. Lead with the story, then proof. Two readers: a lay reader gets the gist from the lead and pictures; a technical reader gets architecture, the hard problem and numbers. No em-dashes, no competitor names, honest status. A MARVIN-built page links to `/ai-projects/marvin/`, and MARVIN's "Built with MARVIN" section links back.

## 5. Author it on the dev site
On the mac-mini, from `~/.agents/lib`:
- A page already in long form must be rolled back first: `portfolio_longform.py <url> --rollback`, then `--author <content.json>` (a `--plan` dry run first). You can tell it's long form when `--plan` answers "not a project-page layout page", or when its content has `longform-section` blocks (often base64 inside `[fusion_code]`). Save your own backup of the current page content before rolling back: `ID=$(${=W} post list --post_type=page --name=<slug> --field=ID); ${=W} post get $ID --field=post_content > backup/longform-<date>/<slug>.html`, with `W` set to the `wp_base()` command.
- A short page converts directly with `--author`.
- Writes go through `portfolio_apply.wp_base()` (wp-cli as the admin, so WordPress keeps tags like `<source>`). In zsh, split a command held in a variable with `${=VAR}`.

## 6. Verify and review
- Run the pipeline from a shell on the mac-mini: `portfolio_sync_dev.py` (sync, pages, capture, parity, evaluate). Launching it through the dashboard currently hangs; that bug is logged.
- Check the Portfolio tab's **Content** view (the page should be "complete") and **Evaluation** (copy, media and template warnings).
- Screenshot the whole page with a script that scrolls first: images lazy-load, and an unscrolled capture shows empty boxes. Look at every figure and the text around it.
- Re-read the copy against the writing-style avoid list before calling it done.

## 7. Report
Tell Gil what changed and where to see it on the dev site, what is uncommitted in the portfolio repo, and anything that needs his decision (privacy calls, claims you cut).
