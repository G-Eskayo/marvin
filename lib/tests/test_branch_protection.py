"""marvin#826 step 6: protect main with the required-checks list, but only when that is safe. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_branch_protection.py -v

The owner approved protecting main on both repos (required checks, admins included). lib/branch_protection.py
builds the exact settings from .github/required-checks.json and refuses to apply them while either would break
work: CI on main hasn't yet run every listed check (GitHub would wait forever for a name it never sees), or commits
still reach main without a PR (version bumps, auto-sync), which a protected main would reject. GitHub is a fake that
records calls; the settings are checked against GitHub's documented request shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import branch_protection as bp  # noqa: E402
import required_checks  # noqa: E402


def test_the_settings_require_exactly_the_list_with_admins_included():
    s = bp.settings(ROOT)
    assert s["required_status_checks"]["contexts"] == required_checks.names(ROOT)
    assert s["enforce_admins"] is True
    assert s["required_status_checks"]["strict"] is False
    # Nothing beyond what the owner approved: no review requirement, no push restrictions.
    assert s["required_pull_request_reviews"] is None and s["restrictions"] is None
    assert s["allow_force_pushes"] is False and s["allow_deletions"] is False


def test_a_repo_without_a_list_has_nothing_to_protect_with(tmp_path):
    with pytest.raises(ValueError, match="required-checks"):
        bp.settings(tmp_path)


class Gh:
    def __init__(self, check_runs=(), raise_on=None):
        self.calls = []
        self.check_runs = list(check_runs)

    def __call__(self, args, input=None):
        self.calls.append((args, input))
        if "check-runs" in " ".join(args):
            return "\n".join(self.check_runs)
        return "{}"


NAMES = ["Rules", "Python tests"]


def test_main_runs_the_list_only_when_every_name_has_a_run_on_main():
    assert bp.missing_on_main("o/r", NAMES, gh=Gh(["Rules", "Python tests", "Other"])) == []
    assert bp.missing_on_main("o/r", NAMES, gh=Gh(["Rules"])) == ["Python tests"]


def _repo_with(tmp_path, subjects: list[str], via_pr: bool) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=r, check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.invalid")
    run("config", "user.name", "t")
    run("commit", "-q", "--allow-empty", "-m", "root")
    for s in subjects:
        if via_pr:
            run("checkout", "-q", "-b", "f")
            run("commit", "-q", "--allow-empty", "-m", s)
            run("checkout", "-q", "main")
            run("merge", "-q", "--no-ff", "f", "-m", f"Merge pull request #1 from o/f")
            run("branch", "-q", "-D", "f")
        else:
            run("commit", "-q", "--allow-empty", "-m", s)
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    return r


def test_commits_that_reached_main_without_a_pr_are_found(tmp_path):
    r = _repo_with(tmp_path, ["Version 0.23.0", "auto-sync (macbook-pro): 1 file(s) changed"], via_pr=False)
    assert bp.direct_pushes(r, since="1.year") == ["Version 0.23.0", "auto-sync (macbook-pro): 1 file(s) changed"]


def test_a_main_that_only_takes_prs_has_no_direct_pushes(tmp_path):
    r = _repo_with(tmp_path, ["feature"], via_pr=True)
    assert bp.direct_pushes(r, since="1.year") == []


def test_apply_refuses_while_main_does_not_run_the_list_and_sends_nothing(tmp_path):
    gh = Gh(["Rules"])
    with pytest.raises(bp.NotSafe, match="Python tests"):
        bp.apply("o/r", {"required_status_checks": {"contexts": NAMES}}, repo_dir=_repo_with(tmp_path, [], True), gh=gh)
    assert not [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]


def test_apply_refuses_while_commits_still_reach_main_without_a_pr(tmp_path):
    gh = Gh(NAMES)
    r = _repo_with(tmp_path, ["Version 0.23.0"], via_pr=False)
    with pytest.raises(bp.NotSafe, match="Version 0.23.0"):
        bp.apply("o/r", {"required_status_checks": {"contexts": NAMES}}, repo_dir=r, gh=gh)
    assert not [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]


def test_apply_puts_the_settings_when_it_is_safe(tmp_path):
    gh = Gh(NAMES)
    s = {"required_status_checks": {"strict": False, "contexts": NAMES}, "enforce_admins": True}
    bp.apply("o/r", s, repo_dir=_repo_with(tmp_path, ["feature"], True), gh=gh)
    put = [c for c in gh.calls if c[0][:3] == ["api", "-X", "PUT"]]
    assert put == [(["api", "-X", "PUT", "repos/o/r/branches/main/protection", "--input", "-"], json.dumps(s))]
