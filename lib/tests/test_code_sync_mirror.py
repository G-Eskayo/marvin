"""mirror(): code sync for a pull-only node (ADR 0069). The box ends identical to origin/main, never pushes, never
loses what was on it (saved to a backup first), and never touches untracked files such as Claude's sign-in."""
import subprocess
from pathlib import Path

import pytest

import code_sync


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """origin (bare) <- mac (pushes) ; box (mirrors). Real git throughout."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    mac = tmp_path / "mac"
    subprocess.run(["git", "clone", "-q", str(origin), str(mac)], check=True)
    for r in (mac,):
        git(r, "config", "user.email", "t@t"); git(r, "config", "user.name", "t")
    (mac / "a.txt").write_text("v1\n")
    git(mac, "add", "."); git(mac, "commit", "-qm", "v1"); git(mac, "push", "-q", "origin", "main")
    box = tmp_path / "box"
    subprocess.run(["git", "clone", "-q", str(origin), str(box)], check=True)
    git(box, "config", "user.email", "b@b"); git(box, "config", "user.name", "b")
    (box / ".gitignore").write_text(".credentials.json\n")
    backups = tmp_path / "backups"
    monkeypatch.setattr(code_sync, "MIRROR_BACKUP_DIR", backups)
    monkeypatch.setattr(code_sync, "MIRROR_LOG_PATH", tmp_path / "mirror.log")
    errors = []
    monkeypatch.setattr(code_sync.error_log, "record", lambda *a, **k: errors.append(a))
    return {"origin": origin, "mac": mac, "box": box, "backups": backups, "errors": errors}


def mac_commits(w, text):
    (w["mac"] / "a.txt").write_text(text)
    git(w["mac"], "commit", "-qam", text.strip()); git(w["mac"], "push", "-q", "origin", "main")


def test_box_fast_forwards_to_what_the_macs_pushed(world):
    mac_commits(world, "v2\n")
    code_sync.mirror(world["box"])
    assert (world["box"] / "a.txt").read_text() == "v2\n"


def test_local_edits_on_the_box_are_backed_up_then_discarded(world):
    mac_commits(world, "v2\n")
    (world["box"] / "a.txt").write_text("edited on the box\n")
    code_sync.mirror(world["box"])
    assert (world["box"] / "a.txt").read_text() == "v2\n"
    saved = "".join(p.read_text() for p in world["backups"].rglob("*") if p.is_file())
    assert "edited on the box" in saved


def test_local_commits_on_the_box_are_backed_up_and_never_pushed(world):
    (world["box"] / "a.txt").write_text("box commit\n")
    git(world["box"], "commit", "-qam", "box commit")
    origin_before = git(world["origin"], "rev-parse", "main")
    code_sync.mirror(world["box"])
    assert git(world["origin"], "rev-parse", "main") == origin_before          # nothing left the box
    assert git(world["box"], "rev-parse", "HEAD") == origin_before             # box matches origin
    saved = "".join(p.read_text(errors="replace") for p in world["backups"].rglob("*") if p.is_file())
    assert "box commit" in saved


def test_untracked_and_ignored_files_survive(world):
    (world["box"] / ".credentials.json").write_text("secret")
    (world["box"] / "scratch.txt").write_text("untracked")
    mac_commits(world, "v2\n")
    (world["box"] / "a.txt").write_text("dirty\n")
    code_sync.mirror(world["box"])
    assert (world["box"] / ".credentials.json").read_text() == "secret"
    assert (world["box"] / "scratch.txt").read_text() == "untracked"


def test_an_unreachable_origin_leaves_the_box_alone_and_is_recorded(world):
    (world["box"] / "a.txt").write_text("dirty\n")
    git(world["box"], "remote", "set-url", "origin", "/nonexistent/repo.git")
    code_sync.mirror(world["box"])
    assert (world["box"] / "a.txt").read_text() == "dirty\n"
    assert world["errors"], "a failed mirror must reach the error log (Health)"


def test_mirror_never_writes_to_the_synced_sync_log(world, monkeypatch, tmp_path):
    synced_log = tmp_path / "sync-log.md"
    monkeypatch.setattr(code_sync, "LOG_PATH", synced_log)
    mac_commits(world, "v2\n")
    code_sync.mirror(world["box"])
    assert not synced_log.exists()


def test_running_twice_is_a_no_op(world):
    mac_commits(world, "v2\n")
    code_sync.mirror(world["box"])
    head = git(world["box"], "rev-parse", "HEAD")
    code_sync.mirror(world["box"])
    assert git(world["box"], "rev-parse", "HEAD") == head
    assert not world["backups"].exists() or not any(world["backups"].rglob("*.patch"))
