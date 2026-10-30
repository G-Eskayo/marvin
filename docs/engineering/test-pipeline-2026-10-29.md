# Test pipeline: why merges keep failing, and the fix (#826)

## Why merges keep failing: what I found (2026-10-29)

**1. GitHub and the merge check run different tests.**

| | GitHub CI | MARVIN's merge check (the Mini) |
|---|---|---|
| Dashboard tests (vitest, 2,518) | yes | yes |
| Python tests (pytest, 4,427) | **no** | yes |
| Rebase onto current main first | no | yes |

A PR can be green on GitHub and red in MR Review. Neither repo's `main` is protected (`Branch not protected`), so a merge on the website needs nothing at all.

**2. That makes a cascade.** A website merge skips the Python tests, and a broken test lands on main. The merge check then refuses every PR with MAIN_RED ("main itself fails these tests"), which pushes the owner to the website again, and more breakage lands. It happened on 10-27 (#689) and again today:
- #767 and #770 went in through the website, each hard-coding the owner name (`test_instance.py` forbids that).
- The Mini had no ripgrep, so two search tests failed only there.
- Every gated approval after 02:03 was refused. Fixed by #777 plus installing ripgrep.

**3. Every PR runs every test.** A one-line docs PR runs all ~7,000 tests, so any single unrelated failure blocks every PR in the repo.

**4. Some tests depend on the machine.** The same commit passes on one Mac and fails on the other:
- ripgrep is installed on the MacBook and was missing on the Mini
- `test_daily_digest.py` reads which Mac is primary, so it fails on the standby MacBook
- `test_instance_move.py` was 5 of the gate's failures since 10-20

**5. Rules are written as tests, and they only fail at the end.** Repo rules (no hard-coded owner, the engine never tracks the instance) are tests that first run in the merge check, after the work is done. Only the ADR 0063 "a test must change" rule runs at commit time.

**6. Helpers share worktrees.** On #761, a sweep helper and the #761 helper worked in the same worktree at once, and one had to hand over to the other.

**For scale:** since 10-20 the pipeline logged 103 failures. 50 are the executor never reaching passing tests in 3 tries, 18 are `claude` crashes, and about 15 are gate test failures.

## What to build

**A. One definition of "required checks" per project, used by both.** The project profile (`config/projects/<repo>.json`) lists them. GitHub CI runs exactly that list, and **branch protection on `main` requires it**, so a website merge can't skip it. The merge check becomes "rebase onto current main, then the same checks".

**B. Three tiers of tests, split by what the PR touches** (the owner's point: segregate instead of piling up):
1. **Rules (every PR, also before each commit):** secrets scan, no hard-coded owner, the instance split, the Decisions format. They're fast and run as pre-commit hooks too, so they fail when the code is written, not at merge.
2. **Affected tests (per PR):** chosen by the paths it changes and what imports them. For example, `dashboard/**` runs vitest, and `lib/x.py` runs its tests plus the tests of whatever imports it (graphify already has the import graph). Each profile maps its areas to its tests. Seal Speak: CaptionCore for `Packages/**`, the site checks for `site/**`, and so on.
3. **The full suite, triggered by every merge to main** (not a timer). If main goes red, a fix-forward ticket opens straight away.

**C. "No new failures" instead of refusing everything.** If every failing test also fails on main, the PR didn't cause it. Merge it, and open or attach to the main-red ticket. Only a PR that adds a failure is refused. Owner's decision.

**D. Tests state what they need.**
- A test that needs a tool (`rg`, `xcodegen`, a model) declares it.
- A missing tool gives a clear "this Mac is missing X" infrastructure message, never a red test.
- A Health card shows each Mac's tools.
- Tests never read the real machine's role.

**E. One worktree, one owner.** A lock file in each worktree. A second helper reads it and works elsewhere, or waits for the first to exit.

