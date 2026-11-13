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