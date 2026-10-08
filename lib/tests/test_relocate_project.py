"""relocate_project.py (#262): move a project out of iCloud ~/Documents without losing anything (the #192 procedure)."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import relocate_project as rp  # noqa: E402


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "Documents" / "Projects" / "demo"
    r.mkdir(parents=True)
    git(r, "init", "-q", "-b", "main"); git(r, "config", "user.email", "t@t"); git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("one\n"); git(r, "add", "-A"); git(r, "commit", "-qm", "c1")
    (r / "a.txt").write_text("two\n")                      # uncommitted change
    (r / "new.txt").write_text("untracked\n")              # untracked file
    return r


def test_state_captures_commit_changes_and_stashes(repo):
    s = rp.state(repo)
    assert s["git"] and len(s["head"]) == 40 and s["stashes"] == 0
    assert " M a.txt" in s["status"] and "?? new.txt" in s["status"]


def test_relocate_copies_everything_verifies_and_hides_the_old_copy(repo, tmp_path):
    dest_root = tmp_path / "Developer"
    out = rp.relocate(repo, dest_root, stamp="2026-10-08")
    new = dest_root / "demo"
    assert out["ok"] and out["dest"] == str(new)
    assert rp.state(new) == out["state"]                              # same commit, same changes, same stashes
    assert (new / "new.txt").read_text() == "untracked\n"
    hidden = repo.parent / ".demo-old-icloud-2026-10-08"
    assert hidden.is_dir() and not repo.exists()                       # renamed, never deleted


def test_relocate_refuses_when_the_destination_exists(repo, tmp_path):
    (tmp_path / "Developer" / "demo").mkdir(parents=True)
    with pytest.raises(rp.RelocateRefused):
        rp.relocate(repo, tmp_path / "Developer", stamp="x")
    assert repo.is_dir()                                               # nothing moved


def test_a_failed_verification_leaves_the_original_in_place(repo, tmp_path, monkeypatch):
    real = rp.state
    calls = []
    def flaky(p):
        calls.append(p)
        s = real(p)
        return {**s, "head": "different"} if len(calls) == 2 else s   # the copy reads differently
    monkeypatch.setattr(rp, "state", flaky)
    with pytest.raises(rp.RelocateRefused):
        rp.relocate(repo, tmp_path / "Developer", stamp="x")
    assert repo.is_dir()


def test_plain_folders_are_compared_by_file_list_and_size(tmp_path):
    d = tmp_path / "Documents" / "Projects" / "notes"; d.mkdir(parents=True)
    (d / "x.md").write_text("hi\n")
    out = rp.relocate(d, tmp_path / "Developer", stamp="s")
    assert out["state"]["git"] is False and (tmp_path / "Developer" / "notes" / "x.md").exists()
