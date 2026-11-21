## North-star fit

**Reuses before adding anything new:**
- `lib/contrast.py` (marvin#1062) — the formula, the palette-file schema (`fg`/`bg`/`opacity`/`backdrop`/`level`/`exception`), and its CLI. No new checker logic needed.
- `lib/tests/test_contrast.py::test_every_marvin_palette_meets_the_rule` (lines 125‑130) **already globs `config/palette/*.json` and fails if any pair is below its level**, and that file already runs inside the `python-tests` CI job (`.github/workflows/ci.yml` → `.github/run-check.sh python`). The ticket's "have the existing check run over `config/palette/*.json` in CI" acceptance criterion is **already satisfied by code that exists today** — dropping in `config/palette/dashboard.json` is enough to bring it under the gate. No new CI job, no new workflow wiring. (I'll correct the ticket on this point rather than build a redundant mechanism.)
- `config/palette/wezterm.json`'s shape and granularity — one self-contained design system's tokens, each pair's real composited background given explicitly, exceptions written out. `dashboard.json` follows the same shape for the dashboard's own self-contained design system (`dashboard/src/components/boot.css` + `show_window.css`, the celestial-navigation tokens, #428/#431/#715/#1029) — not an open-ended sweep of every Tailwind utility class elsewhere in the dashboard (those aren't part of this token system and are a different, unscoped problem).
- `dashboard/scripts/show_history_evidence.mjs` — already builds the show window headlessly with mock history data and screenshots exactly the header tag + history strip this ticket needs. Reused verbatim for "after"; run once more against the pre-fix CSS for "before". No new screenshot tooling.

**Why this is the simplest sufficient approach:** the defect is one token value and a missing inventory file; the CI mechanism, the screenshot harness, and the computation formula all already exist. The only genuinely new artifact is `config/palette/dashboard.json` itself plus the CSS/test edits it's checking.

**Likely cause of the two prior failed attempts (grounded in the code, not guessed):** `contrast.py`'s `levels.pixel = 7.0` applies only to MARVIN Term, the terminal's bitmap pixel font (per its own docstring and `wezterm.json`'s "AAA fix" notes) — it does **not** apply to the dashboard, which renders with `Share Tech Mono`/`Saira Condensed`, ordinary rendered fonts. I measured the ticket's suggested replacement, `#b89235`, by hand against both real backgrounds the token sits on:
- on `show_window.css`'s `--bg` (`#05040A`): **≈7.01:1**
- on `boot.css`'s `--dash` (`#0f1117`): **≈6.47:1**

Both clear the correct **"text" level (4.5:1)** comfortably. But if a palette (or an agent) mistakenly copies `wezterm.json`'s `"pixel": 7.0` level onto the boot-screen pair (an easy mistake — same hex value range, same file family), `6.47 < 7.0` and the check **fails**, which is exactly the shape of "code review found must-fix issues" after repeated iterations without a clear symptom in the comments. This is the one fact I'll verify with `contrast.py` itself (not by hand) before touching any file, and it's the main thing I'll get right that the previous attempts plausibly didn't.

**Token/background inventory actually in code** (read directly, not assumed):
- `--dim` sits on `--bg`/`--dash` solid, **and**, for `.show-tag` and the two boot lines (`.boot-check .boot-hdr`, `.boot-bar .boot-lbl`), under the "modern raster" texture (`.show-hud`'s own gradient; `.boot-raster`, `z-index:6`, confirmed in `BootSequence.jsx` to stack above the boot lines since they have no `z-index`) — a very faint `#ffffff07` (~2.7%) stripe composited on top. This is the dashboard's real equivalent of the ticket's "glass" case; there is no actual `backdrop-filter`/vibrancy glass behind any `--dim` text (Electron's `vibrancy: 'under-window'` only shows through non-opaque regions, and every `--dim` usage sits on an opaque `--bg`/`--dash` div). I'll model the raster stripe with `contrast.py`'s existing `opacity`+`backdrop` fields (`bg:"#ffffff", opacity:0.027, backdrop:"<the real bg>"`) as the worst-case pair, and say so plainly rather than inventing "30%/60% glass" pairs that don't correspond to anything in this code.
- Hover/disabled states: grepped both files — nothing reuses `--dim` for hover/disabled (hover states use `--green`). Negative result, worth stating, not worth a fix.
- `docs/design/864-projects-shipped/index.html` also defines `--dim: #6b551f` with the identical defect, but it's outside `dashboard/src` (the ticket's explicit grep scope) and outside the ticket's named files — flagged as a Decision below rather than silently included or silently skipped.

**Token saves/spends:** spends a little (reading four small CSS files + one JSON schema fully) to avoid the token-expensive failure mode both prior attempts hit — wrong level, many review round-trips. Net saving.

**Human experience:** direct — this is literally "text people can read" (north star 3). No automation-vs-coaching tension; nothing here should be done by a human instead.

## Tests to write first

One per "How we'll try to break it" item, plus misuse the section didn't name:

1. **Every background `--dim` sits on, solid** — `#05040A` (show window) and `#0f1117` (boot), both at the correct "text" (4.5) level, both for `#b89235` (replacement) — these are the pairs that must now pass.
2. **The raster-texture worst case** — `--dim` over the ~2.7% white-stripe-composited background, for `.show-tag` and the two boot lines, modeled with `contrast.py`'s `opacity`/`backdrop` fields, still ≥4.5.
3. **"Glass"/cards claim, falsified against the code** — a test (or a plan assertion backed by grep + the CSS read above) that no `--dim` usage sits behind an actual translucent/backdrop-filter layer, so the palette doesn't carry invented glass pairs that don't exist in code. (If I'm wrong and one does exist, this test catches it before the PR ships a fabricated pair.)
4. **Hover/disabled states reusing `--dim`** — grep/assertion that none exist today; if a future change adds one, `dashboard.json` must cover it (documented in the file's own comment/notes field, same style as `wezterm.json`'s header note).
5. **Second copy of `6b551f` left behind** — `rg 6b551f dashboard/src` must return nothing after the fix (currently 2 hits: `boot.css`, `show_window.css`).
6. **A malformed palette pair still fails, never skips** — already covered by `test_malformed_colours_are_refused` / `test_a_malformed_pair_fails_the_check_rather_than_being_skipped` in `lib/tests/test_contrast.py`; I'll add one dashboard-shaped malformed pair (e.g. a pair missing `bg`) to that parametrized list so it's clear the generic guarantee also covers this new file, not just `wezterm.json`.
7. **CI actually fails on a planted bad pair (acceptance criterion #3)** — a new test that takes the real, loaded `config/palette/dashboard.json` dict, mutates one passing pair's `fg` to something that fails (e.g. back to `#6b551f`), and asserts `contrast.check()` on the mutated copy is `not ok` with a clear failure line. This proves the mechanism without ever committing a failing `dashboard.json` to main (which would break the *other* criterion, "`contrast.py check config/palette/*.json` passes on main"). Mirrors the existing `test_a_pair_below_its_level_fails_with_a_clear_message` pattern.
8. **`show_window_view.test.jsx`'s literal assertion** — update `'--dim: #6b551f'` → `'--dim: #b89235'` in the existing test (line 23); this is the one existing test that pins the literal value and will fail until changed.
9. **Repeats/order misuse not in the ticket's list:** the same colour pair listed twice in `dashboard.json` with two different levels — already guaranteed to fail by `check()`'s `seen` dict; add one dashboard-shaped case alongside the existing `wezterm.json`-shaped one in `test_the_same_pair_listed_twice_with_different_levels_is_refused` (parametrize rather than duplicate).
10. **Stale exception misuse:** if I end up writing an `exception` field anywhere in `dashboard.json` and the fix makes that pair pass, `check()` already flags it as "no longer needed" — no new test needed, just don't leave a stale exception in the file (verified by running `contrast.py check` on the final file, not by trusting memory).

## Decisions
<!-- marvin:decisions -->
### design-doc-scope: `docs/design/864-projects-shipped/index.html` also defines `--dim: #6b551f` with the identical 2.86:1 defect, but it sits outside `dashboard/src` and outside the ticket's named files. Fix it in this PR too, or leave it out of scope?
- [ ] A: Fix it here too (same token, same bug, cheap, avoids a second ticket for an identical one-line fix)
- [ ] B: Leave it out — the ticket's grep check and file list are both scoped to `dashboard/src`; file a follow-up ticket instead

### palette-scope: `config/palette/dashboard.json` catalogs every text-color token used by `boot.css`/`show_window.css` (the celestial-navigation design system — ~7 tokens, matching `wezterm.json`'s granularity for one self-contained system), not every Tailwind text-color utility class used elsewhere across the dashboard's React components (a much larger, open-ended, differently-shaped problem). Confirm that scope.
- [ ] A: Correct scope — celestial-navigation tokens only (`boot.css` + `show_window.css`)
- [ ] B: Expand to audit Tailwind text-color classes across the whole dashboard in this same ticket

## Task List

1. Verify by running `lib/contrast.py` directly (not by hand) that `#b89235` clears 4.5:1 on both real backgrounds (`#05040A` solid, `#0f1117` solid, and the raster-texture-composited variants of each) before touching any CSS.
2. Replace `--dim: #6b551f` → `--dim: #b89235` in `dashboard/src/components/boot.css` and `dashboard/src/components/show_window.css`.
3. Update the literal `'--dim: #6b551f'` assertion in `dashboard/test/show_window_view.test.jsx` to `'--dim: #b89235'`.
4. Create `config/palette/dashboard.json`: `--dim` on every real background it sits on (solid `--bg`/`--dash`, plus the raster-texture worst case for `.show-tag`/the two boot lines), each at the "text" (4.5) level with a one-line "notes" field explaining why "text" and not "pixel" applies here (mirrors `wezterm.json`'s own `notes` field) — plus the other celestial-navigation text tokens (`--amber`, `--green`, `--orange`, `--red`, `--moon`) on their real backgrounds in both files, classified at "text" or "large" per actual font size (e.g. `.boot-title h1`'s 60px headline is "large", 3:1).
5. Add the dashboard-shaped cases to `lib/tests/test_contrast.py`'s existing parametrized tests (malformed pair, duplicate-pair-different-levels) rather than duplicating test functions; add the new "planted failing pair" test described above.
6. Run `contrast.py check config/palette/*.json` and the full `lib/tests/test_contrast.py` suite; fix any failure before moving on — no exceptions should be needed given the measured margins.
7. Run `rg 6b551f dashboard/src` to confirm zero hits (plus act on the `design-doc-scope` decision for the file outside that directory).
8. `npm run build` the dashboard, then run `node dashboard/scripts/show_history_evidence.mjs <before-dir>` against the pre-fix build (temporarily, in a disposable worktree/stash of just the CSS change) and again against the post-fix build for `<after-dir>`; `marvin-show` both PNGs in the PR (acceptance criterion #4).
9. Run the full dashboard unit-test suite (`dashboard-tests` CI job equivalent) and the full Python test suite locally before opening the PR, per the "full suites before a hand-merge" rule.
10. Open the PR with: the measured ratios table, the two screenshots, the Decisions block above, and "Closes #1148".