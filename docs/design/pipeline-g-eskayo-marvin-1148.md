## North-star fit

**Reuses**, nothing new invented for the hard part:
- `lib/contrast.py`'s existing `check()`/`over()`/`ratio()` engine and its palette-file schema (`config/palette/wezterm.json` is the existing worked example — same `"what"/"fg"/"bg"/"level"` shape, same `opacity`+`backdrop` glass-composite convention).
- `lib/tests/test_contrast.py:125` `test_every_marvin_palette_meets_the_rule` — it already globs `config/palette/*.json` and fails if any pair in any palette is below its level. Adding `dashboard.json` there, correctly, is the entire CI enforcement; **no new CI job or test needs to be written** — that's the generic safety net marvin#1062 already built, and the only thing standing between a new palette file and "nothing to re-abstract."
- The AAA fix already decided and shipped for the terminal (`config/palette/wezterm.json`: `#6b551f` → `#b89235`, "secondary text, ANSI bright black"). The dashboard's `--dim` is the exact same colour for the exact same role; reusing it rather than picking a new amber keeps one decided colour for "dim/secondary" everywhere instead of two.

**Simplest sufficient approach:** the celestial-navigation token system (`--dim`, `--amber`, `--orange`, `--red`, `--green`, `--moon`) exists only in two files, `boot.css` and `show_window.css` — confirmed by `rg -- '--dim|--amber|--moon' dashboard/src` returning only those two files. The rest of the dashboard is Tailwind utility classes, a different, much larger system the ticket doesn't name and that `config/palette/dashboard.json` isn't scoped to cover. Treating "every dashboard text token pair" as "every pair in these two files' token set" keeps the file finite (13 pairs) and matches the one thing `lib/contrast.py` is built to check (a declared, named set of fg/bg pairs), rather than trying to palette-audit arbitrary Tailwind classes.

**Correction to the ticket's own framing:** the ticket's measured example (`#6b551f` on `#05040A` = 2.86:1) is `show_window.css`'s background. `boot.css` defines its own `--dash: #0f1117` and never uses `--bg`/`#05040A` at all — its `--dim` text sits on a *different* near-black. Both backgrounds need their own pair in the palette; I'm covering both, not just the one the ticket measured.

**Tokens/levels:** everything in these two files is normal-size, anti-aliased web-font text (Saira Condensed / Share Tech Mono), not MARVIN Term's bitmap font, so the "pixel" 7:1 rule from `marvin#1062`/`wezterm.json` does **not** apply here — the dashboard only needs "text" (4.5:1). I hand-verified (WCAG relative-luminance formula) that every current token except `--dim` already clears 4.5:1 on both backgrounds by a wide margin (amber ≈10.0–10.9:1, green ≈14.4:1, moon ≈14.0:1, orange ≈6.6–7.1:1, red ≈5.3–5.8:1); `#6b551f` is the only one below 4.5 on either background. `#b89235` (the already-approved terminal fix) measures ≈7.0:1 on `#05040A` and ≈6.47:1 on `#0f1117` — passes 4.5:1 on both with room, so no fallback colour is needed.

**Tokens, spends:** a 13-pair JSON file plus a one-line registration in `affected_tests.py`. No new runtime code, no new abstraction — pure data plus reuse of an existing generic check.

**Phone-OS / human-experience fit:** directly serves north star 3 — this is literally "text people can read." It leaves the user more capable (an owner's dashboard they can actually read the secondary labels on), not more passive.

**Where it runs:** this is a plan-only ticket; implementation will run wherever the pipeline executor runs it (no machine-specific requirement — pure text/CSS/JSON edits, Python + JS test runs).

## Correctness finding that likely explains the prior rejection

`lib/affected_tests.py`'s PR-scoped test selection (`select()`, lines 91–130) picks a test file only if a changed **non-`.py` file's basename literally appears as a substring in that test's source**. `lib/tests/test_contrast.py` never names a filename — it does `(REPO / "config" / "palette").glob("*.json")` — so a PR that adds only `config/palette/dashboard.json` would **not** select `test_contrast.py`, and on a PR (where `MARVIN_BASE` is set) the "CI fails on a planted failing pair" acceptance criterion would silently not hold: the failure would only surface on the next full-suite run *after* merging to main. `test_instance*.py` has the identical shape ("judges every file in the repo, so any change can break them") and is handled by being hard-coded into the `RULES` list (`lib/affected_tests.py:40`) rather than relying on name-matching. I'll apply the same fix: add `lib/tests/test_contrast.py` to `RULES`, with a comment explaining why (it judges every file under `config/palette/`, not a specific filename the heuristic can see).

## Tests to write/run first

1. `contrast.py check config/palette/*.json` and `pytest lib/tests/test_contrast.py::test_every_marvin_palette_meets_the_rule` — run with `dashboard.json` added but *before* touching the CSS (pairs still reference `#6b551f`): must **fail** (red), proving the new pairs are actually wired into the existing check — this is the ticket's "shown by a planted failing pair" criterion, using the real failing value rather than a synthetic one.
2. Same two commands after the CSS fix and the pairs updated to `#b89235`: must **pass** (green), with the printed ratios captured for the PR body.
3. `affected_tests.py list <base>` for a diff that touches only `config/palette/dashboard.json`: must include `lib/tests/test_contrast.py` — proves the `RULES` fix closes the gap found above. (Without the fix, this is the regression: it would print a list *not* containing that test.)
4. Re-plant a failing pair after everything's wired (e.g. temporarily restore one `--dim` pair's `fg` to `#6b551f`) → confirm `pytest lib/tests/test_contrast.py` fails → revert. Direct re-demonstration of the acceptance criterion against the finished file, not just the pre-fix state.
5. `rg '6b551f' dashboard/src` → must return nothing (ticket's named misuse check: a second stale copy of the token left behind).
6. Malformed-pair handling ("fails, never skipped") — already covered by the existing `test_a_malformed_pair_fails_the_check_rather_than_being_skipped` parametrized test in `lib/contrast.py`'s own suite; I'm not writing a new one, just confirming (by reading it, done above) that it already exercises the shared engine `dashboard.json` is checked by.
7. Hover/disabled states reusing `--dim` (ticket's attack list): inspect `.show-history-item:hover` / `.is-current` — confirmed by CSS specificity reading that `.show-history-meta`'s own `color: var(--dim)` always wins over the ancestor's inherited hover/current colour, and the background stays `transparent` (→ still `--bg` solid) in both states, so no new pair is introduced; I'll note this check explicitly in the PR rather than silently assuming it.
8. `npm test` (vitest) for `dashboard/test/show_window_view.test.jsx` after updating its literal `--dim: #6b551f` → `--dim: #b89235` assertion: must pass.
9. Visual check: launch the dashboard (via the `run` skill) and open a `marvin show` window, confirm the header tag and history-strip meta text are legibly amber-ish/brighter, not the old muddy olive, before screenshotting.

## Decisions
<!-- marvin:decisions -->
### glass-scope: Model the main window's `vibrancy: 'under-window'` as a "glass" pair in `config/palette/dashboard.json`, the way `wezterm.json` models the terminal's 30%/60% glass over white/mid-grey?
- [ ] A: No — no text token in `boot.css`/`show_window.css` is actually drawn over anything translucent today (boot screen and `marvin show` windows are both fully opaque; the only literal alpha is `.show-card`'s 1.6%-white tint, already covered as its own pair). Omit the glass/vibrancy scenario; it's not a real pixel anyone sees.
- [ ] B: Yes — add it anyway as a defensive/future-proofing entry (same convention as `wezterm.json`'s), approximating the main window's native macOS vibrancy against an assumed white/mid-grey desktop, even though no `--dim`-system text is drawn there yet.

## Task List

1. Add `config/palette/dashboard.json`: 13 pairs — 5 for `boot.css` tokens (`--amber`, `--orange`, `--red`, `--green`, `--dim`) on `#0f1117`; 6 for `show_window.css` tokens (`--amber`, `--orange`, `--red`, `--green`, `--dim`, `--moon`) on `#05040A`; 2 more for `--amber`/`--red` text inside `.show-card` (opacity ≈0.0157 white over `#05040A`). All at `fg`/old value (`#6b551f` for the two `--dim` pairs) to start red.
2. Run `contrast.py check config/palette/*.json` + `pytest lib/tests/test_contrast.py::test_every_marvin_palette_meets_the_rule`; confirm it fails on the two `--dim` pairs (2.86:1-ish on `#05040A`, similarly below 4.5 on `#0f1117`).
3. Change `--dim: #6b551f` → `--dim: #b89235` in `dashboard/src/components/boot.css:3` and `dashboard/src/components/show_window.css:6`. Update the two `--dim` pairs in `dashboard.json` to `#b89235`.
4. Re-run step 2's commands; confirm pass; record the exact ratios for the PR body.
5. Update `dashboard/test/show_window_view.test.jsx:23`'s literal `'--dim: #6b551f'` → `'--dim: #b89235'`; run the dashboard vitest suite.
6. Add `lib/tests/test_contrast.py` to `RULES` in `lib/affected_tests.py:40`, with a short comment (mirrors `test_instance*.py`'s rationale: it judges every file in `config/palette/`, invisible to the name-matching heuristic). Verify with `affected_tests.py list <base>` on a diff touching only `config/palette/dashboard.json`.
7. Plant a temporary failing pair, confirm `pytest lib/tests/test_contrast.py` fails, revert — the acceptance criterion's demonstration.
8. `rg '6b551f' dashboard/src` → confirm empty.
9. Resolve the `glass-scope` Decision; adjust `dashboard.json` accordingly (add or explicitly document the omission in its `notes` field).
10. Launch the dashboard (via `run` skill), open a `marvin show` window, capture before/after screenshots of the header tag and history strip; attach via `marvin-show --pr N` per `docs/agents/showing-things.md`.
11. Open the PR: measured ratios, screenshots, the Decisions block from above, "Closes #1148".