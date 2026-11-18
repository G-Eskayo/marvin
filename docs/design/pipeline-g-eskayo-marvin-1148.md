## North-star fit

**Reuses:** `lib/contrast.py`'s `check()`/`over()` (marvin#1062) unchanged — it already globs `config/palette/*.json` generically (`lib/tests/test_contrast.py::test_every_marvin_palette_meets_the_rule`), so adding `config/palette/dashboard.json` plugs straight into the existing CI coverage with **no new wiring**; the ticket's "have the existing check run over `config/palette/*.json` in CI" is already true today, it just has nothing dashboard-shaped to check yet. The extraction-style regression test mirrors `lib/tests/test_wezterm_look.py::test_every_terminal_text_colour_is_a_checked_pair` (scan real usages → assert every one is a measured, passing pair) rather than hand-listing a fixed set that can silently drift. The fix colour, `#b89235`, is not invented — it's the exact "secondary text, ANSI bright black (AAA fix)" colour Gil already approved for this same semantic role in `config/palette/wezterm.json`, reused rather than picking a new amber.

**Simplest sufficient approach:** no new Python module. All extraction logic lives inside one new test file; `contrast.py` and the CI test that globs `config/palette/*.json` are untouched.

**Tokens/spend:** zero runtime cost — this is a static CSS/JSON/test change, checked at CI time, not read at request time.

**More capable, not more passive:** yes — it closes an accessibility gap (WCAG AA) for anyone actually reading the dashboard, and the regression test means this bug class (a stale colour in a second file) can't silently return.

**Correction to the ticket:** the "What to build" bullet says to list "every dashboard text token pair ... including the glass opacities the dashboard uses." I checked `dashboard/electron/main/index.js:382` and `show_window.js:87`: the main dashboard window uses macOS `vibrancy: 'under-window'` (an OS-blurred, content-dependent material with no fixed alpha), and the `marvin show` window is fully solid (`backgroundColor: '#05040A'`, no vibrancy, no opacity). The 30%/60% "glass" numbers in `config/palette/wezterm.json` are WezTerm's own `window_background_opacity` setting (issue #1073, "wezterm wrapper") — a literal, configurable alpha that has no dashboard equivalent. The only real translucent background in the dashboard CSS is `.show-card { background: #ffffff04 }` (≈1.6% white over `--bg`), which I did include. Vibrancy itself can't be expressed as a `{fg,bg,opacity,backdrop}` pair because its effective backdrop is whatever's behind the window on the user's desktop — this is the subject of the Decision below rather than something I'll guess at.

## Tests first (ticket's "How we'll try to break it")

1. **Every background the token sits on** → `lib/tests/test_dashboard_look.py::test_every_dim_text_use_passes_aa`: for both `.boot-root` (`--dash: #0f1117`) and `.show-root` (`--bg: #05040A`), and the composited card background (`#ffffff04` over `--bg`, the one translucent surface that actually exists), assert `contrast.ratio(new_dim, bg) >= 4.5`.
2. **Hover and disabled states that reuse `--dim`** → `test_no_hover_or_disabled_rule_uses_dim_below_aa`: textually scan both CSS files for any `:hover`/`:focus`/`:disabled`/`:focus-visible` rule whose declaration block sets `color: var(--dim)`; today there are none (hover states use `--green`), so this test pins that invariant rather than letting a future hover rule reuse `--dim` unmeasured.
3. **A second copy of the token left at the old value** → `test_6b551f_is_gone_from_dashboard_src`: `rg -i 6b551f dashboard/src` returns nothing (scoped to `dashboard/src`, so the historical note string in `config/palette/wezterm.json`'s `notes` field is untouched and correctly out of scope).
4. **A palette pair with a malformed colour fails, never skips** → already covered generically by `lib/tests/test_contrast.py::test_a_malformed_pair_fails_the_check_rather_than_being_skipped` and `test_the_cli_exits_non_zero_on_a_failure`; no duplicate needed, just confirm `dashboard.json` is included by the existing glob.
5. **CI fails on a planted failing pair** → `test_a_planted_bad_pair_fails_exactly_like_the_real_bug_did`: build a palette identical to `dashboard.json` but with one pair's `fg` reverted to the historical `#6b551f`, assert `contrast.check(...)["ok"]` is `False` and the failure message names that pair and shows `2.9`/`2.6` vs `4.5` — this is the concrete regression test for the actual bug, not an abstract one.
6. **`show_window_view.test.jsx`'s literal `--dim: #6b551f` assertion** → update it to assert `--dim: #b89235` (or the chosen fallback) instead; this is a required edit, not a new test.
7. **Misuse the ticket's list didn't name:**
   - *Empty/missing `config/palette/dashboard.json`*: already covered generically (`test_every_marvin_palette_meets_the_rule` asserts `palettes` is non-empty for the whole glob).
   - *Permissions, concurrency, stale state, repeats*: don't apply — this is a static CSS/JSON check run once per CI invocation, not a running service with shared mutable state.

## Decisions
<!-- marvin:decisions -->
### vibrancy: The dashboard's main window uses macOS vibrancy (`under-window`), not a fixed alpha like WezTerm's glass. There's no number to put in `dashboard.json` for it. How should this ticket handle it?
- [x] A: Out of scope for this ticket — ship with the solid (#0f1117, #05040A) and card (#ffffff04 over #05040A) pairs only; note in the PR that vibrancy has no measurable backdrop today
- [ ] B: Add a worst-case exception pair (new colour over `#ffffff`, mirroring the WezTerm glass-over-white exception) as a documented, written-reason placeholder even though it isn't driven by a real config value
- [ ] C: File a follow-up ticket to give the main window's vibrancy a fixed CSS fallback opacity (so it becomes measurable at all) and treat that as blocking this one being fully "done"

**Chosen:** Option A. Rationale: the macOS vibrancy material has a content-dependent backdrop (the user's desktop) that cannot be meaningfully measured. The fixed backgrounds (boot and show windows) are properly addressed with accessible colours, and the card background's actual opacity is included. Vibrancy can be revisited in a follow-up if needed to improve robustness under dark backgrounds.

## Task List

1. Change `--dim: #6b551f` to `--dim: #b89235` in `dashboard/src/components/boot.css` and `dashboard/src/components/show_window.css`.
2. Update `dashboard/test/show_window_view.test.jsx`'s literal-token assertion from `--dim: #6b551f` to `--dim: #b89235`.
3. Create `config/palette/dashboard.json` with `levels: {text: 4.5, large: 3.0, ui: 3.0}` and pairs for every text token actually used in `boot.css`/`show_window.css` against its real background(s): `--dim`, `--amber`, `--green`, `--orange`, `--red` on `#0f1117` (boot); `--dim`, `--amber`, `--orange`, `--green`, `--red`, `--moon` on `#05040A` (show window); `--amber` (show-card-url) on the composited `#ffffff04`-over-`#05040A` card background.
4. Write `lib/tests/test_dashboard_look.py`: the extraction-based "every `--dim` use is a checked, passing pair" test, the hover/disabled-state scan, the `6b551f`-is-gone grep test, and the planted-bad-pair regression test (item 5 above).
5. Resolve the `vibrancy` Decision and act on the chosen option before marking the PR ready.
6. Run `contrast.py check config/palette/*.json`, capture the ratios for every `--dim` use, and run the dashboard vitest suite; put the measured ratios in the PR body per acceptance criterion 1.
7. Boot the dashboard, screenshot the show window's header tag and history strip before and after the colour change, and attach both via `marvin-show` per `docs/agents/showing-things.md`.