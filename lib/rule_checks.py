#!/usr/bin/env python3
"""rule_checks.py — the repo's rules, checked when the code is written, not first at merge (marvin#826 step 2).

Repo rules used to be tests that first ran in the merge gate, after the work was done: #767 and #770 each hard-coded
the owner's name, which lib/tests/test_instance.py forbids, and the gate refused every PR after them. The same rules
now run as a git pre-commit hook and as CI's required "Rules" check:

  secrets     each staged line a commit ADDS, against bin/pre-push-guard's own pattern files
              (config/push-guard/patterns.txt and paths.txt, plus ~/.claude/private-push-patterns.txt if present;
              a private match is reported without echoing the string)
  instance    the content rules in test_instance.py and test_instance_move.py (RULE_TESTS): no hard-coded owner,
              account or machine; the engine never tracks the owner's instance state
  decisions   a doc with a <!-- marvin:decisions --> block must parse as the dashboard parses it
              (docs/agents/decisions-format.md). Only a real block is judged: an ADR's "## Decision" section
              records a decision, it doesn't ask one.

Auto-sync commits (MARVIN_COMMIT_KIND=auto-sync) skip the rule tests and the Decisions check, which judge work, not
sweeps, but never the secret scan. MARVIN_RULES_SKIP_TESTS=1 skips the rule tests only. `git commit --no-verify`
skips the hook; CI's Rules check and the pre-push guard still run.

    rule_checks.py pre-commit          the hook: check what is staged
    rule_checks.py ci                  CI's Rules check: docs changed since $MARVIN_BASE (all docs without it),
                                       plus the whole rule test files
    rule_checks.py install [repo]      put the hook in <repo>'s git hooks (never over a different pre-commit hook)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decisions_check  # noqa: E402

MARK = "# marvin-rule-checks (marvin#826)"
PRIVATE = Path.home() / ".claude" / "private-push-patterns.txt"
DEFAULT_PATHS = r"(^|/)logs/.*\.jsonl$|\.transcript$"  # as bin/pre-push-guard: a repo without paths.txt still refuses
# The content rules: what judges the repo's files, not instance.py's behaviour. Fast (~2 s), so they run per commit.
RULE_TESTS = [
    "lib/tests/test_instance.py::test_no_new_engine_file_hard_codes_an_owner_account_or_machine",
    "lib/tests/test_instance.py::test_the_grandfathered_list_only_shrinks",
    "lib/tests/test_instance.py::test_the_engine_never_tracks_the_instance_dir",
    "lib/tests/test_instance_move.py::test_the_engine_no_longer_tracks_the_owners_state",
    "lib/tests/test_instance_move.py::test_a_stale_writer_cannot_put_it_back",
]
# CI's Rules check runs these files whole: the rules and the checkers' own tests.
RULE_FILES = ["lib/tests/test_instance.py", "lib/tests/test_instance_move.py", "lib/tests/test_decisions_check.py",
              "lib/tests/test_rule_checks.py"]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60).stdout


def _patterns(path: Path) -> list[re.Pattern]:
    out = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#"):
            try:
                out.append(re.compile(line))
            except re.error:
                continue  # an ERE Python can't read: bin/pre-push-guard still applies it at push
    return out


def _added_lines(repo: Path) -> list[tuple[str, int, str]]:
    """(path, line number, text) for each line the staged changes add."""
    out, path, n = [], None, 0
    for line in _git(repo, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMR").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            n = int(m.group(1)) if m else 0
        elif line.startswith("+") and path:
            out.append((path, n, line[1:]))
            n += 1
    return out


def secret_hits(repo: Path, private: Path = PRIVATE) -> list[str]:
    repo = Path(repo)
    guard = repo / "config" / "push-guard"
    shared, mine = _patterns(guard / "patterns.txt"), _patterns(private)
    paths = _patterns(guard / "paths.txt") or [re.compile(DEFAULT_PATHS)]
    hits = []
    for p in _git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACR").splitlines():
        if any(r.search(p) for r in paths):
            hits.append(f"{p}: this path may never be committed (config/push-guard/paths.txt)")
    for path, n, text in _added_lines(repo):
        if any(r.search(text) for r in shared):
            hits.append(f"{path}:{n} matches a secret pattern (config/push-guard/patterns.txt)")
        elif any(r.search(text) for r in mine):
            hits.append(f"{path}:{n} matches one of your private patterns")  # never echo the string itself
    return hits


def decisions_problems(repo: Path, paths: list[str], refusal=decisions_check.refusal) -> list[str]:
    out = []
    for p in paths:
        if not p.endswith(".md"):
            continue
        try:
            text = (Path(repo) / p).read_text(errors="replace")
        except OSError:
            continue  # deleted in this change
        if "<!-- marvin:decisions -->" not in text:
            continue
        why = refusal(text)
        if why and why.startswith("DECISIONS_UNPARSED"):
            out.append(f"{p}: {why}")
    return out


def run_rule_tests(repo: Path, full: bool = False) -> tuple[bool, str]:
    repo = Path(repo)
    nodes = [n for n in (RULE_FILES if full else RULE_TESTS) if (repo / n.split("::")[0]).is_file()]
    if not nodes:
        return True, "no rule tests in this repo"
    import cleanup_sweep
    with cleanup_sweep.disposable_basetemp() as basetemp_args:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodes, *basetemp_args], cwd=repo,
                           capture_output=True, text=True, timeout=300)
    return p.returncode == 0, (p.stdout + p.stderr)[-4000:]


def pre_commit(repo: Path, env=os.environ, private: Path = PRIVATE, run_tests=run_rule_tests) -> tuple[bool, str]:
    repo = Path(repo)
    staged = _git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
    if not staged:
        return True, "nothing staged"
    problems = [f"secret: {h}" for h in secret_hits(repo, private)]
    if env.get("MARVIN_COMMIT_KIND") != "auto-sync":
        problems += [f"decisions: {d}" for d in decisions_problems(repo, staged)]
        if env.get("MARVIN_RULES_SKIP_TESTS") != "1":
            ok, out = run_tests(repo)
            if not ok:
                problems.append(f"rule tests failed:\n{out}")
    return not problems, "\n".join(problems) or "rules pass"


def ci(repo: Path, base: str | None, run_tests=lambda r: run_rule_tests(r, full=True),
       check_docs=decisions_problems) -> tuple[int, str]:
    repo = Path(repo)
    if base:
        paths = _git(repo, "diff", "--name-only", "--diff-filter=ACMR", base, "HEAD").splitlines()
    else:
        paths = _git(repo, "ls-files").splitlines()
    problems = list(check_docs(repo, [p for p in paths if p.endswith(".md")]))
    ok, out = run_tests(repo)
    if not ok:
        problems.append(f"rule tests failed:\n{out}")
    return (1 if problems else 0), "\n".join(problems) or "rules pass"


def _hook_text() -> str:
    return (f"#!/bin/sh\n{MARK}\n# Installed by lib/rule_checks.py; see that file. Remove this file to switch it off.\n"
            f'exec "{sys.executable}" "{Path(__file__).resolve()}" pre-commit\n')


def install_hook(repo: Path, force: bool = False) -> str:
    gitdir = Path(_git(Path(repo), "rev-parse", "--git-common-dir").strip())
    gitdir = gitdir if gitdir.is_absolute() else Path(repo) / gitdir
    hook = gitdir / "hooks" / "pre-commit"
    if hook.exists():
        current = hook.read_text(errors="replace")
        if MARK not in current and not force:
            return "skipped: a different pre-commit hook is already installed"
        if current == _hook_text():
            return "already installed"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(_hook_text())
    hook.chmod(0o755)
    return "installed"


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "pre-commit":
        try:
            ok, report = pre_commit(Path.cwd())
        except Exception as e:  # noqa: BLE001 -- a broken check says so; CI's Rules check still runs
            sys.stderr.write(f"rule checks could not run ({e}); committing anyway. CI's Rules check still applies.\n")
            return 0
        if not ok:
            sys.stderr.write(f"commit refused by the repo's rules (lib/rule_checks.py, marvin#826):\n{report}\n")
            return 1
        return 0
    if cmd == "ci":
        code, report = ci(Path.cwd(), os.environ.get("MARVIN_BASE") or None)
        print(report)
        return code
    if cmd == "install":
        print(install_hook(Path(argv[1]) if len(argv) > 1 else Path.home() / ".agents"))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
