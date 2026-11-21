## North-star fit

**Reuses before adding anything new:**
- `setup.sh:458-465` already defines what a "real skill" is for counting purposes: a direct subdirectory of the skills dir containing a file named exactly `SKILL.md`. I'll port that same definition into `lib/session_start_report.py` instead of inventing a new one.
- `skills/self-improve/SKILL.md:88-100` ("Auto-wire the skill") is the only place the "wired" mechanism is actually specified: a command file `~/.claude/commands/<skill-name>.md` is plain content (not a symlink) containing the literal path `~/.agents/skills/<skill-name>/SKILL.md`. That gives me a verifiable definition of "has a command or is otherwise reachable": stem match on the skill name, falling back to a content scan for the skill's `SKILL.md` path so a command whose filename doesn't match the skill (but whose content still points at it) still counts.
- `lib/purpose_metrics.py`'s `PROBES` dict (e.g. `_prd_dispatches`, `_mirror_failures`, `test_prd_dispatch_probe_is_registered`) is the existing, reviewed pattern for a recurrence probe — I'll add one more entry and one more private counter function in that same shape, not a new mechanism.
- `lib/tests/test_session_start_report_budget.py`'s `home` fixture (monkeypatching `ssr.CLAUDE_DIR`) is the existing pattern for testing this file; I'll monkeypatch a new `ssr.SKILLS_DIR` constant the same way rather than touching `HOME`.
- `dashboard/electron/main/boot_data.js`'s `memoryLine()` already counts skills from `~/.agents/skills/*/SKILL.md` for a different UI (the Electron boot screen) — confirms the skills-dir-based count is the right ground truth, but it doesn't compute "wired" at all, so it isn't reusable for that half.

**Why this is the simplest sufficient approach:** no new files, no new subprocess calls, no new dependency. It's a same-shaped `glob`/`iterdir` swap inside `check_identity()`, plus one small probe function reusing the issue's own stated verification command (`git ls-tree origin/main` on `skills/*/SKILL.md`).

**Tokens:** zero added LLM calls; this is a deterministic hook that runs once per session start, same cost class as today, net cost is slightly more filesystem I/O (bounded by ~35 skills × ~35 commands) — negligible.

**Capability, not passivity:** fixes a status line Gil is told to quote verbatim at the start of every session and that a reviewer can independently verify. A wrong number is a small, silent lie that erodes exactly the kind of trust north star 2 cares about; fixing it costs Gil nothing to act on himself, it's purely a reliability fix. Auto-pruning dangling command symlinks (the literal `self-optimize.md` case) also removes a recurring class of future miscounts without needing a human to notice and clean it up by hand each time.

**One correction to the ticket's own framing:** the ticket says "Remove the dangling `self-optimize.md` symlink" as if it's a one-off deletion. That file lives only in the live `~/.claude/commands/` on Gil's Mac (verified: it is not tracked in this repo, and `~/.claude/commands` doesn't even exist in this sandbox), so a one-time `rm` in this PR's diff is impossible and wouldn't survive the next time it happens anyway. I'm instead making `check_identity()` prune *any* dangling symlink it finds in `~/.claude/commands` as a side effect each session (mirroring the existing `process_and_check_quarantine()` pattern of combining cleanup with reporting) — this fixes the named instance and prevents recurrence, which is what "nothing breaks silently" actually calls for.

No Decisions section: the "wired" definition, the banner wording, and the auto-prune side effect are all fully determined by existing docs/patterns above, not open design choices for the owner.

## Tests (written first)

In `lib/tests/test_session_start_skills_wired.py` (new), against `skill_names()`, `_wired_skill_names()`, `_prune_dangling_commands()`, and `check_identity()` directly, monkeypatching `ssr.SKILLS_DIR` / `ssr.CLAUDE_DIR` the way the existing budget test monkeypatches `CLAUDE_DIR`:

Ticket's "How we'll try to break it" list:
1. A dangling symlink in `commands/` — is not counted as wired, and is deleted from disk by `check_identity()`.
2. A command with no matching skill (e.g. a stray `.md`) — ignored; doesn't inflate the skill or wired count.
3. A skill with no command (the `variable-tracker` case) — counted in the skill total, not counted as wired.
4. A non-skill command (Raindrop-style `new-raindrop-app.md`) — ignored entirely, never treated as a skill.
5. An empty (or missing) `commands/` folder — 0 wired, skill total unaffected, no crash.
6. A skill folder without `SKILL.md` — not counted in the skill total.

Additional misuse not in that list:
7. Bad/malformed: a command `.md` file containing non-UTF-8 bytes — read with `errors="replace"`, doesn't crash the content-fallback scan.
8. Huge input: ~500 junk command files plus ~50 skill folders — completes without error (no perf assertion, just correctness).
9. Dependency failing: `~/.agents/skills` itself missing — `skill_names()` returns `[]`, banner still prints "0 skills (0 wired)", doesn't raise.
10. Wrong permissions: a command file that raises `OSError` on read (simulated) — that one file is skipped; other skills' stem-matches still resolve correctly, no crash.
11. Repeats: calling `check_identity()` twice in a row after a dangling symlink is pruned the first time — second call is a no-op on that file, same result, no error.
12. A person's mistake: a nested `skills/foo/bar/SKILL.md` two levels deep — not counted (only direct children of `skills/`).
13. "Otherwise reachable": a command named differently from the skill but whose content contains `skills/<name>/SKILL.md` (the real wiring template from `self-improve/SKILL.md`) — counts as wired.
14. Banner format: `check_identity()`'s output contains the literal substring `"3 skills (2 wired)"` for a 3-skill/2-wired fixture (format assertion, not full-string equality, since the git-hash portion is environment-dependent).

In `lib/tests/test_purpose_metrics.py` (append), following the existing `test_prd_dispatch_probe_*` shape:
15. `test_banner_skill_count_drift_probe_is_registered` — `limit == 0.0` and `"#997"` in the description.
16. `test_banner_skill_count_drift_probe_reads_zero_when_main_matches` — fake `git ls-tree` output with the same count as a fixture skills dir → `0.0`.
17. `test_banner_skill_count_drift_probe_counts_the_difference` — fake `git ls-tree` output listing a different number of `skills/*/SKILL.md` paths → `abs(diff)`.
18. `test_banner_skill_count_drift_probe_handles_git_failure` — injected `run` returns non-zero / raises `OSError` → `0.0` (dependency failing, not unknown — matches every other probe's convention).
19. `test_banner_skill_count_drift_probe_handles_missing_repo` — `repo` path has no `.git` → `0.0`.

Existing-test hygiene (not new tests, but touched for consistency): update the two hardcoded mock banner strings in `lib/tests/test_session_start_report_budget.py` (lines 61, 93) from `"3 skills wired"` to `"3 skills (3 wired)"` so the test suite doesn't carry a stale format as a fossil — these tests mock `check_identity` entirely and don't exercise the new logic, so this is cosmetic only.

## Task List

1. In `lib/session_start_report.py`: add `SKILLS_DIR = HOME / ".agents" / "skills"` near `CLAUDE_DIR`.
2. Add `skill_names(skills_dir: Path) -> list[str]`: direct subdirectories of `skills_dir` containing a file named exactly `SKILL.md` (port of `setup.sh`'s skill-counting logic).
3. Add `_dir_entries(d: Path) -> list[Path]` helper (safe `iterdir()`, `[]` on `OSError`).
4. Add `_prune_dangling_commands(commands_dir: Path) -> None`: unlinks any symlink under `commands_dir` that no longer resolves, logging failures via `log_hook_error` (fixes the `self-optimize.md` case and any future recurrence, generally).
5. Add `_wired_skill_names(skills_dir: Path, commands_dir: Path) -> set[str]`: for each name from `skill_names()`, wired if a `.md` command file's stem matches, else if any command's content contains `skills/<name>/SKILL.md` (the `self-improve/SKILL.md` wiring template).
6. Rewrite `check_identity()` to call `_prune_dangling_commands()`, then build the banner from `skill_names(SKILLS_DIR)` and `_wired_skill_names(...)`, emitting `"... · {total} skills ({wired} wired)"` instead of the old `~/.claude/commands/*.md` count.
7. In `lib/purpose_metrics.py`: add `_banner_skill_count_drift(repo: Path | None = None, run=subprocess.run) -> float`, reusing `session_start_report.skill_names()` against the live `~/.agents/skills` and comparing to a `git -C <repo> ls-tree -r --name-only origin/main` count of paths matching `skills/[^/]+/SKILL\.md`; returns `0.0` on any git/path failure (dependency-failing-reads-zero, matching every other probe).
8. Register `"banner-skill-count-drift": (lambda days=PROBE_WINDOW_DAYS: _banner_skill_count_drift(), 0.0, "...marvin#997")` in `PROBES`.
9. Write `lib/tests/test_session_start_skills_wired.py` covering tests 1–14 above.
10. Append tests 15–19 to `lib/tests/test_purpose_metrics.py`.
11. Update the two hardcoded mock strings in `lib/tests/test_session_start_report_budget.py` (lines 61, 93) to the new format.
12. Update `docs/session-start-checklist.md` row 0 ("Identity banner") to describe the new source (`skills/*/SKILL.md` count + wired count) and the new line format `<N> skills (<M> wired)`.
13. Run the full affected test suite (`lib/tests/test_session_start_skills_wired.py`, `lib/tests/test_purpose_metrics.py`, `lib/tests/test_session_start_report_budget.py`) and confirm green before opening the PR.