# Portfolio: tests for moving the mockups into WordPress (2026-10-22)

**Status: design only, for Gil's approval. Nothing gets built until he approves it.**
Owner: Gil. The redesign itself belongs to the Mac Mini chat. This suite only **reads** what that chat builds.

## 1. The problem

The new look exists as static mockups (`/homepagefiles/brand-proto/*.html`, `/homepagefiles/landing-proto/living.html`).
They have to become real WordPress pages.

WordPress can change a page on the way through without saying so:

| What WordPress / Avada does | What it breaks |
|---|---|
| `wpautop` adds `<p>` and `<br>` | Empty gaps, broken grids, a line break mid-sentence (already seen once: see `portfolio_migrate.tidy_text`) |
| `wptexturize` swaps quotes and dashes | Text no longer matches; code samples change |
| Avada's own CSS loads on every page | Fonts, sizes, colours and margins drift from the mockup |
| Avada wraps content in a 1200px row | Full-width bands and the landing canvas stop being full-width |
| Content saved through the editor or REST | Inline `<script>` blocks can be stripped or escaped |
| Asset paths | The mockups load from `/homepagefiles/brand-proto/`. **That folder is not in `deploy/`**, so production would not have it |
| Caching (browser, Avada CSS cache) | The dev site shows an old stylesheet, and the test passes on stale files |

Today nothing checks a mockup against the page built from it. Gil would find each problem by eye, one at a time.

## 2. Goals and non-goals

**Goals**
- For every (mockup → WordPress page) pair, prove the page looks, reads and behaves like the mockup.
- Prove the content rules hold on every page, wherever text can hide (alt text, comments, PDFs).
- Prove the migration can run twice safely and can be undone.
- Block anything going to production until the suite passes.
- Fail with a plain sentence and a screenshot, saved to the outbox.

**Non-goals**
- No model judging "does this look right". Every check is deterministic (code and numbers).
- No writes to production. Ever.
- Not a test of the copy itself. The copy is Gil's call; the suite checks it moved intact.
- Not a speed or SEO audit (could come later).
- Does not replace `bin/check-site-quality.py` or `portfolio_eval.py`. The gate runs them too.

## 3. What gets compared: the pair manifest

One data file declares every pair. Proposed: `templates/migration-pairs.json` in the portfolio repo (site data lives with the site).

```json
{
  "version": 1,
  "mockup_base": "http://localhost:8080/homepagefiles/",
  "wp_base": "http://localhost:8080",
  "pairs": [
    {"id": "about",     "mockup": "brand-proto/about.html",     "wp": "/about/",     "content_root": "main.wrap"},
    {"id": "education", "mockup": "brand-proto/education.html", "wp": "/education/", "content_root": "main.wrap"},
    {"id": "contact",   "mockup": "brand-proto/contact.html",   "wp": "/contact/",   "content_root": "main.wrap"},
    {"id": "resume",    "mockup": "brand-proto/resume.html",    "wp": "/resume/",    "content_root": "main.wrap"},
    {"id": "home",      "mockup": "landing-proto/living.html",  "wp": "/",           "kind": "webgl",
     "masks": ["canvas#scene"], "full_bleed": ["canvas#scene"]}
  ],
  "mockup_only": [".mocknote"],
  "redirects": {"/achievements/": "/about/", "/organizations/": "/about/", "/education/computer-science/": "/education/"},
  "console_allow": [{"match": "type is not defined", "reason": "local-only WP Coder error (STEERING 2026-09-25)", "expires": "2026-12-01"}]
}
```

Rules for the manifest:
- **WordPress URLs above are placeholders.** The real ones come from the redesign chat (About may stay `/about-me/`).
- **The link map is derived, not stored.** Each pair already says "this mockup file is that WP page". A mockup link to `about.html` must become a WP link to that pair's `wp` URL. No second table to drift.
- `mockup_only` lists mockup scaffolding (the black "MOCKUP" strip). It is hidden before screenshots and must **not** appear on WordPress.
- Each run records each mockup's SHA-256. If a mockup changed since the last pass, the report says so first, so a moving mockup is not mistaken for a broken page.

**Found while reading:** there are **26 mockups**, not 5. Besides the 5 above there are 4 Portfolio hubs and 17 project pages (`project-*.html`, built by `build_projects.py`). Scope is decision D1.

## 4. The check catalogue

Every check has an ID, so a failure line says exactly which rule broke.
`V` = per viewport. Default viewports are decision D4.

### A. Preflight (stop early with a clear reason)

| ID | Check | Pass rule |
|---|---|---|
| P1 | Dev site is up | `GET /` returns 200 |
| P2 | Dev site serves the files we think it does | `portfolio_parity.dev_site_drift()` returns nothing (catches the wrong Docker mount, marvin#585) |
| P3 | Every pair exists | Mockup returns 200; WP page is published |
| P4 | Mockup unchanged, or change noted | SHA-256 recorded; a change is a notice, not a failure |
| P5 | Noise floor | Mockup screenshotted twice gives **0 differing pixels** outside masks. If not, a region is animated and needs a mask. This is a suite setup error (exit 2), not a page failure |

A failed P1–P3 exits with code 2 ("could not run"). That is different from "ran and found problems".

### B. Visual parity (V)

| ID | Check | Pass rule |
|---|---|---|
| V1 | Full-page screenshot diff, mockup vs WP | Page heights match within max(8px, 0.5%). Differing pixels ≤ **0.2%** of the unmasked area. **No single blob of difference larger than 24×24 px**. A pixel "differs" if any colour channel moves more than 24/255 (allows anti-aliasing). Thresholds are decision D3 |
| V2 | Masks are honest | Each mask covers ≤ 60% of the viewport, so a mask can't hide the whole page |
| V3 | No sideways scroll | `scrollWidth ≤ viewport + 1` (reuse `portfolio_eval.check_overflow`) |
| V4 | Full-width parts stay full-width | Each `full_bleed` element is viewport-wide ±1px (catches Avada's 1200px row) |
| V5 | Computed style parity | For `h1, h2, h3, p, a, nav a, .mono, .eyebrow`, the font family, size, weight, line height, letter spacing and colour are equal (reuse `portfolio_elements.PART_PROPS` and `portfolio_parity.compare`) |
| V6 | Web fonts really loaded | `portfolio_parity.unloaded_fonts` returns nothing (otherwise the browser quietly draws Arial) |

Why the blob rule: on a long page, a missing button is under 0.2% of the pixels. The blob rule still catches it.

### C. Text and structure

| ID | Check | Pass rule |
|---|---|---|
| T1 | Same words | Visible text under `content_root`, normalised (Unicode NFKC, spaces collapsed, curly quotes and dashes made plain). **0 words lost, 0 words added** (reuse `portfolio_migrate.words` / `lost_words`). Quote or dash swaps are listed as warnings |
| T2 | Same heading outline | The sequence of (level, text) for `h1`–`h6` is identical |
| T3 | Same skeleton | The DOM under `content_root`, reduced to tags and structural classes (the `portfolio_layouts` skeleton idea), is identical. Extra Avada wrappers *outside* the root are ignored |
| T4 | No `wpautop` damage | No visible empty `<p>`; no `<br>` WordPress added that the mockup lacks; no `<p>` wrapped around a block element; no literal `[fusion_` or `[wp_code` in visible text |
| T5 | Same title and description | `<title>` and meta description match, after removing " (mockup)" |
| T6 | No mockup leftovers | No "MOCKUP", no `.mocknote`, no link to `*.html` under `/homepagefiles/`, no `localhost` URL in the served HTML |
| T7 | Inline scripts survive | Each inline `<script>` in the mockup is in the WP page, byte-for-byte after trimming, and it ran (a marker it sets exists) |

### D. Links and assets

| ID | Check | Pass rule |
|---|---|---|
| L1 | Every internal link works | 200, after at most one redirect. Unique URLs only, checked once per run |
| L2 | Links point where the mockup pointed | Each mockup link, translated through the pairs, equals the WP link. `mailto:` and external links must be identical |
| L3 | Every request on page load succeeds | No 4xx, 5xx or failed request (fonts, images, `.bin`, `.js`, `.css`) |
| L4 | Assets will exist in production | Every same-origin asset is under `wp-content/` (shipped by `deploy/` or in uploads), WP core, or the theme. **Nothing from `/homepagefiles/brand-proto/` or `/landing-proto/`** |
| L5 | Served files are the real files | The stylesheet and scripts the page loads are byte-equal to their source files, and the `?v=` version matches (the `dev_site_drift` pattern). Catches caching |
| L6 | Images load | Every `<img>` has `naturalWidth > 0` (reuse `portfolio_eval.check_media`) |
| L7 | External links | Checked once a day, cached. A failure is a **warning**, not an error (LinkedIn answers bots with code 999) |

### E. Runtime and navigation

| ID | Check | Pass rule |
|---|---|---|
| R1 | No console errors | 0 console errors, 0 page errors, 0 unhandled promise rejections, except `console_allow` entries. Each entry needs a reason and an expiry date. An expired entry fails |
| R2 | Same menu | Header menu labels and order equal the mockup. Each target returns 200. The highlighted item is this page |
| R3 | Menu can be clicked at narrow widths | At each narrow viewport, every menu link is visible and is the top element at its centre (nothing covers it) |
| R4 | Retired pages redirect | Each `redirects` entry returns 301 to its target |

### F. The living landing page (`kind: webgl`)

The painting moves, so its canvas is masked in V1 (decision D5). These checks prove it still works.

| ID | Check | Pass rule |
|---|---|---|
| W1 | WebGL starts | A `webgl2` context is created (recorded by a script added before the page loads) |
| W2 | Not blank | After 2 s, the canvas's brightness spread (std dev) is above a floor measured from the mockup |
| W3 | It moves | Two captures 500 ms apart differ. With reduced motion turned on, the page is still and the text is readable |
| W4 | Script loads once | `living.js` loads exactly once, in order, not combined or deferred by Avada |
| W5 | Data files intact | `depth.png`, `regions.png`, `sky-strokes.bin`, `bridge.jpg` are byte-equal to source and served with the right content type |
| W6 | Canvas fills the screen | Canvas box equals the viewport ±1px |
| W7 | Typing text is the same | The lines typed are the mockup's lines. No word breaks across lines (each word has one line box) |

### G. Content rules (every page on the site, not only the pairs)

Checked on every surface: visible text, attributes (`alt`, `title`, `aria-label`, `href`), the raw HTML including comments, the REST `raw` content, and the text of any linked PDF.

| ID | Rule | Pass rule |
|---|---|---|
| C1 | No phone number | No `tel:` link. No phone-shaped number. Gil's real number (read at run time from `~/.claude/resume/master.md`, never copied into code) appears nowhere |
| C2 | No Snorkel AI | "Snorkel" absent, any case |
| C3 | Never Brooksource | "Brooksource" absent, any case |
| C4 | No grades, no student ID | No "GPA". No course name followed by a letter grade. The student ID (read from a private local file outside every repo) appears nowhere |
| C5 | No certs not yet held | "AWS GenAI Pro", "Generative AI Professional", "SecAI+", "SecAI" absent |
| C6 | Aircraft Dynamics left off | "Aircraft Dynamics" and "ASEN 3128" absent |
| C7 | Nourished is "in development" | Every mention of "Nourished" has "in development" in the same block |

The rules live as data in `portfolio_rules.py` (`content_bans`), so `portfolio_eval` and this suite share one copy, and Gil can edit them in the Guide & rules tab.
A short phone number is easy to guess from a hash, so hashing it in the repo would not protect it. That is why the private values are read from private files.

### H. Lifecycle (the migration itself)

| ID | Check | Pass rule |
|---|---|---|
| I1 | Plan writes nothing | `--plan` leaves a checksum of `wp_posts` and `wp_postmeta` unchanged |
| I2 | Idempotent | Running the migration twice: the second run reports 0 changes; each page's `post_content` hash is the same; page and media counts are unchanged (no duplicates) |
| I3 | Rollback works | Apply, then roll back: `post_content` hash equals the saved `before.json`, and a screenshot equals the pre-migration one (0 diff outside masks). Then re-apply works |
| I4 | The suite is stable | Two runs in a row give the same verdict and the same diff numbers |

`portfolio_migrate.py` already has `--plan`, `--rollback` and `before.json`. Any tool that moves these pages must offer the same three. Where I1–I3 run is decision D7.

### WordPress risk → check that catches it

| Risk | Checks |
|---|---|
| `wpautop` | T3, T4, V1 |
| `wptexturize` | T1 (warning) |
| Avada CSS bleed | V5, V6, V1 |
| Avada 1200px row | V4, W6, V3 |
| Asset URLs rewritten or dev-only | L3, L4, T6 |
| Script loading for `living.js` / WebGL | T7, W1, W4 |
| Caching | L5, plus a fresh browser context per run |

## 5. How it is built (reuse first)

**One new module, one new test file, one new data file.** Everything else is reused.

| Part | Where | New or reused |
|---|---|---|
| Pair manifest | portfolio repo `templates/migration-pairs.json` | New data file |
| Runner + check functions | `~/.agents/lib/portfolio_wp_parity.py` | New (pure check functions + one Playwright runner) |
| Self-tests | `~/.agents/lib/tests/test_portfolio_wp_parity.py` | New |
| Overflow, media, viewports | `portfolio_eval.check_overflow`, `check_media`, `_MEDIA_JS` | Reused |
| Drift, fonts, style compare | `portfolio_parity.dev_site_drift`, `unloaded_fonts`, `compare` | Reused |
| Look capture | `portfolio_elements.PART_PROPS`, `BASE` | Reused |
| DOM skeleton | `portfolio_layouts` skeleton reducer | Reused (expose it as a function if needed) |
| Lost words, plan/rollback contract | `portfolio_migrate.words`, `lost_words`, `before.json` | Reused |
| Rules and thresholds | `portfolio_rules.DEFAULT_RULES`, adding `content_bans` and `visual_parity` | Extended |
| Pipeline step and status | `portfolio_sync_dev.run` gains step 6, `wp-parity`; shows in `pipeline-status.json` | Extended |
| Site crawl, 404s, manifest sync | `bin/check-site-quality.py` | Reused as is, called by the gate |

**Tools.** Python Playwright (1.61 on the Mini) for the browser, as the other portfolio modules use. Its `screenshot()` takes `mask=` and `animations="disabled"`. Pixel diff with numpy + Pillow. The `page.clock` API can freeze time for the typing text.
**Where it runs:** the Mac Mini. The MacBook's MARVIN venv has no Playwright today (checked), and the dev database is per machine anyway (ADR 0003).

**Flow of one run**

1. Preflight (P1–P5). Stop with exit 2 if the site can't be tested.
2. For each pair and each viewport: open the mockup and the WP page, each in a fresh context.
3. Hide `mockup_only`, apply masks, take screenshots, measure the DOM, record console and network.
4. Run the pure checks on what was measured (V, T, L, R, W).
5. Run the content rules over every published page (G).
6. Write the report. Exit 0 (pass), 1 (failures), 2 (could not run).

The browser part only **measures**. All judging is in pure functions, so the self-tests can feed them fixtures with no browser.

**Commands**

```
portfolio_wp_parity.py run                 # every pair, every viewport
portfolio_wp_parity.py run --pair contact --viewport 390
portfolio_wp_parity.py rules               # content rules only, whole site (fast)
portfolio_wp_parity.py lifecycle           # I1–I3, on the target chosen in D7
portfolio_wp_parity.py gate                # everything + check-site-quality + portfolio_eval; for pre-deploy
```

### The suite's own tests (it must try to break itself)

Before it judges a real page, each check must **fail** on a planted defect. Real collaborators: real Chromium, a real local HTTP server serving fixture pages, a temp `HOME` (so the outbox and status files never touch the real ones).

| Planted defect | Must fail |
|---|---|
| Phone number in an `alt`; "Snorkel" in an HTML comment; phone in a linked PDF | C1, C2 |
| "Nourished" with no "in development" | C7 |
| A copy run through real `wpautop` | T3 or T4 |
| A button moved 3px; a button removed on a long page | V1 (blob rule) |
| An Avada-like stylesheet changing `h2` size | V5 |
| A font URL that 404s | V6, L3 |
| An asset under `/homepagefiles/brand-proto/` | L4 |
| A stale stylesheet copy | L5 |
| A `throw` in a script; an expired allowlist entry | R1 |
| A canvas that never draws | W2 |
| A mask covering the whole page | V2 |
| An animated region with no mask | P5 (exit 2) |

## 6. How it fails: the report

Every run writes to `~/.claude/outbox/portfolio-wp-parity/<YYYY-MM-DD-HHMM>/`, which the dashboard and MARVIN Mobile already show:

| File | What it is |
|---|---|
| `report.html` | One page. Failures first. Per pair and viewport: mockup, WP and diff images side by side |
| `summary.json` | Machine-readable: every finding with check ID, pair, viewport, numbers |
| `<pair>@<width>/mockup.png`, `wp.png`, `diff.png` | Diff in magenta over a faded WP shot. Ready to pin in a ticket (screenshot rule) |

One plain line per finding, for example:

> FAIL V1 about @899: 1.8% of pixels differ (limit 0.2%). Largest difference 310×42 px at y=1220. See about@899/diff.png
> FAIL C1 /resume/: a phone number is in the linked PDF master-resume.pdf, page 1
> FAIL L4 /education/: diploma.jpg loads from /homepagefiles/brand-proto/, which production does not have

The pipeline status (`~/.claude/portfolio/pipeline-status.json`) gets a `wp-parity` step, so the Templates tab shows pass or fail without opening the outbox.

**Storage is bounded.** Full images are kept only for failing pair-viewports. Passing ones keep a 400px thumbnail. Only the last 5 runs are kept; older run folders are deleted by the suite itself.

## 7. Cost: time and space

Let P = pairs, V = viewports, U = unique URLs linked across pages, N = published pages, A = pixels per screenshot.

| Part | Time | Space |
|---|---|---|
| Page loads | 2·P·V loads, about 3 s each. With 4 browser contexts in parallel: 5 pairs × 4 viewports ≈ **1 min**; all 26 pairs ≈ **5 min** | — |
| Pixel diff | O(A) per pair-viewport. A 1440×4000 page is 5.8M pixels, about 50 ms in numpy | 3 images in memory at a time, ~70 MB peak |
| Links | O(U): each unique URL checked once per run, not once per page | O(U) cache |
| Content rules | One combined regex pass, O(total text) for N pages + PDFs | O(largest page) |
| Skeleton / text compare | O(nodes) per page | O(nodes) |
| Report on disk | Fail: ~3 MB per pair-viewport. Pass: ~40 KB thumbnail | Capped at 5 runs. Worst case 26 × 4 × 3 MB × 5 ≈ 1.6 GB, typical well under 100 MB |

No step re-reads the whole site more than once per run. Nothing grows without a cap.

## 8. Rollout, as vertical slices

Each slice works end to end and shows a real report before the next starts.

| Slice | What it delivers | Needs |
|---|---|---|
| S0 | Self-tests and fixtures; every planted defect fails (red first) | Nothing from the redesign chat |
| S1 | One pair end to end: **Contact** (smallest mockup) at 2 viewports. P, V1, T1, L3, R1, all of G. Report in the outbox | The WP Contact page exists on dev |
| S2 | All 5 named pairs, all viewports, the rest of V, T, L, R | Those WP pages exist |
| S3 | The living landing page (W1–W7) | WP home built from `living.html` |
| S4 | Lifecycle (I1–I4) on the D7 target | The migration tool offers plan / apply / rollback |
| S5 | The gate (D6) and the pipeline step | — |
| S6 | Hubs and project pages, if D1 says so | Those WP pages exist |
| S7 | After launch: baseline mode (D8), optional production read-only check (D9) | Gil approves each page |

S0 can start as soon as Gil approves this doc. S1 onwards waits for the redesign chat's WP pages, and only ever reads them.

## 9. Things to watch

- **`/homepagefiles/` is not deployed.** `deploy/` mirrors `wp-content/` only. Any brand CSS, hero or thumbnail still served from `/homepagefiles/brand-proto/` would be missing in production. L4 makes this a hard failure.
- **Circular source.** `build_projects.py` builds project mockups from the *dev site's* pages. Once WP pages are built from mockups, the two must not feed each other. The manifest's SHA-256 record makes a loop visible.
- **Moving target.** The redesign chat is still editing mockups. P4 reports a changed mockup before any diff, so a moving mockup is not mistaken for a broken page.
- **Copy is a first pass.** The mockups say so. If Gil edits copy in WordPress later, T1 will fail by design. D8 decides what the reference is after launch.

## 10. Open decisions for Gil

Each has a recommendation. Tap one per question.

<!-- marvin:decisions -->
### d1-scope: Which pages does the first version cover?
- [ ] The 5 named pages: About, Education, Contact, Resume, Home (recommended)
- [ ] The 5, plus the 4 Portfolio hub pages
- [ ] All 26 mockups, including the 17 project pages

### d2-region: What part of the page is compared by screenshot?
- [ ] The whole page, header and footer included: it is what a visitor sees (recommended)
- [ ] Only the content area; the header and footer are checked by structure and style instead
- [ ] Both: whole page with a loose limit, content area with a strict one

### d3-threshold: How strict is the screenshot comparison?
- [ ] Strict: 0.1% of pixels, no difference bigger than 16×16 px
- [ ] Balanced: 0.2% of pixels, no difference bigger than 24×24 px (recommended)
- [ ] Loose: 1% of pixels, no difference bigger than 48×48 px
- [ ] Perceptual score (SSIM) of at least 0.98 instead of pixel counts

### d4-viewports: Which screen widths?
- [ ] Today's rule set: 1440, 1100 and 390
- [ ] 1440, 899 and 390 (899 is just under the mockups' 900px breakpoint)
- [ ] 1440, 1100, 899 and 390: covers the Mini's narrow window and a phone (recommended)

### d5-landing: How is the moving painting on Home compared?
- [ ] Hide the canvas in the screenshot; prove it works with the WebGL checks (W1–W7) (recommended)
- [ ] Freeze the clock and the randomness, then compare the canvas pixel by pixel too
- [ ] Both: frozen canvas compared with a loose limit, plus the WebGL checks

### d6-gate: What stops a change reaching production?
- [ ] Nothing automatic: run the command by hand before pushing
- [ ] A pre-push hook in the portfolio repo: a push touching `deploy/`, or a content push to the live site, is refused without a passing report for the current state
- [ ] The pre-push hook, plus a `wp-parity` step in MARVIN's portfolio pipeline with a pass/fail badge in the dashboard (recommended)
- [ ] GitHub Actions (not workable: GitHub cannot reach the dev site on the Mini)

### d7-lifecycle: Where do the run-twice and rollback tests (I1–I3) write?
- [ ] The shared dev site, on the real pages
- [ ] A throwaway second WordPress on another port, made from a database copy, deleted afterwards (recommended: never clashes with the redesign chat)
- [ ] Draft copies of each page on the dev site, with their own slugs

### d8-reference: After launch, what does a page get compared against?
- [ ] The mockup, for good
- [ ] A baseline: the WordPress page as Gil approved it; the mockup is retired (recommended)
- [ ] Both, until the mockups are deleted

### d9-prod: May the suite check production after a deploy, read-only?
- [ ] No, dev only
- [ ] Yes, read-only: content rules, links and console errors on the live site, no writes (recommended)
- [ ] Yes, plus a screenshot comparison of production against dev

### d10-notes: Anything to add or change (text) (optional)
