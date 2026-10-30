#!/usr/bin/env python3
"""branch_protection.py — protect main with the repo's required checks, once that is safe (marvin#826 step 6).

The owner approved protecting main on both repos: the required checks, admins included, so a website merge can no
longer skip them (#767 and #770 did). The settings come from .github/required-checks.json (lib/required_checks.py):

    required_status_checks  {"strict": false, "contexts": <every check name in the list>}
    enforce_admins          true
    required_pull_request_reviews, restrictions: none; force pushes and deletions: not allowed

strict is false: the merge gate already rebases onto main and retests, and a cross-PR break is caught by the full
suite after the merge (lib/main_red.py); strict would make every open PR wait for an update after each merge.

apply refuses (NotSafe) while protection would break work, and sends nothing:
  - CI on main has not run every listed check yet: GitHub would wait forever for a name main never reports
  - commits still reach main without a PR (version bumps, auto-sync): a protected main rejects those pushes

    branch_protection.py plan [repo_dir]                print the settings
    branch_protection.py apply <owner/repo> [repo_dir]  check it is safe, then PUT them (gh api)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import required_checks  # noqa: E402


class NotSafe(RuntimeError):
    pass


def _gh(args: list[str], input: str | None = None) -> str:
    return subprocess.run(["gh", *args], input=input, capture_output=True, text=True, check=True, timeout=60).stdout


def settings(repo_dir: Path) -> dict:
    names = required_checks.names(Path(repo_dir))
    if not names:
        raise ValueError(f"{repo_dir} has no .github/required-checks.json: nothing to require")
    return {"required_status_checks": {"strict": False, "contexts": names}, "enforce_admins": True,
            "required_pull_request_reviews": None, "restrictions": None,
            "allow_force_pushes": False, "allow_deletions": False}


def missing_on_main(repo: str, names: list[str], gh=_gh) -> list[str]:
    """Listed checks with no run on main's latest commit."""
    seen = set(gh(["api", f"repos/{repo}/commits/main/check-runs", "--paginate", "--jq", ".check_runs[].name"]).split("\n"))
    return [n for n in names if n not in seen]


def direct_pushes(repo_dir: Path, since: str = "14.days") -> list[str]:
    """Subjects of commits on origin/main that arrived without a PR merge (first-parent, not a merge commit)."""
    out = subprocess.run(["git", "log", "origin/main", "--first-parent", "--no-merges", f"--since={since}",
                          "--format=%s"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout
    # The repo's first commit is a root, not a push to a protected main.
    roots = subprocess.run(["git", "rev-list", "--max-parents=0", "--format=%s", "origin/main"], cwd=repo_dir,
                           capture_output=True, text=True).stdout.splitlines()[1::2]
    return [s for s in reversed(out.splitlines()) if s and s not in roots]


def apply(repo: str, wanted: dict, repo_dir: Path, gh=_gh) -> None:
    names = wanted["required_status_checks"]["contexts"]
    gone = missing_on_main(repo, names, gh=gh)
    if gone:
        raise NotSafe(f"CI on main has not run {', '.join(gone)} yet: merge the PR that adds them first")
    pushed = direct_pushes(Path(repo_dir))
    if pushed:
        raise NotSafe(f"{len(pushed)} commit(s) reached main without a PR recently (e.g. {pushed[-1]!r}); a protected "
                      f"main would reject those pushes. Move them onto PRs first.")
    gh(["api", "-X", "PUT", f"repos/{repo}/branches/main/protection", "--input", "-"], input=json.dumps(wanted))


def main(argv: list[str]) -> int:
    if argv[:1] == ["plan"]:
        print(json.dumps(settings(Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]), indent=2))
        return 0
    if argv[:1] == ["apply"] and len(argv) >= 2:
        repo_dir = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parents[1]
        try:
            apply(argv[1], settings(repo_dir), repo_dir)
        except NotSafe as e:
            print(f"not applied: {e}", file=sys.stderr)
            return 1
        print(f"main on {argv[1]} is protected")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
