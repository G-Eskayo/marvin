"""code_sync failures reach the error log, and a stale git lock heals itself (marvin#422).

On 2026-10-13 a git command killed at 12:56 (just before the Mini's network dropped) left .git/index.lock behind;
every pull for 26 hours failed with "Unable to create index.lock: File exists" and nothing said so. Real temp repos.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_errors.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402
import error_log  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repos(tmp_path):
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@e.com")
    _git(seed, "config", "user.name", "T")
    (seed / "a.txt").write_text("1\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", str(origin), "main")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "t@e.com")
    _git(clone, "config", "user.name", "C")
    # a new commit upstream for the clone to pull
    (seed / "a.txt").write_text("2\n")
    _git(seed, "commit", "-am", "upstream")
    _git(seed, "push", str(origin), "main")
    return clone


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "machine_label", lambda: "test-mac")
    errors = tmp_path / "errors.jsonl"
    monkeypatch.setattr(error_log, "PATH", errors)
    return errors


def _entries(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines()] if Path(p).exists() else []


def _old_lock(repo, age_s):
    lock = repo / ".git" / "index.lock"
    lock.write_text("")
    t = time.time() - age_s
    os.utime(lock, (t, t))
    return lock


def test_a_stale_unheld_lock_is_removed_and_the_pull_succeeds(tmp_path, monkeypatch):
    errors = _setup(tmp_path, monkeypatch)
    clone = _repos(tmp_path)
    lock = _old_lock(clone, 26 * 3600)
    monkeypatch.setattr(cs, "_lock_held", lambda p: False)
    cs.pull(clone)
    assert not lock.exists()
    assert (clone / "a.txt").read_text() == "2\n"
    (e,) = _entries(errors)
    assert e["fix"] is True and e["source"] == "sync:pull" and "stale git lock" in e["message"]


def test_a_young_lock_is_left_alone_and_the_failure_is_logged_with_its_cause(tmp_path, monkeypatch):
    errors = _setup(tmp_path, monkeypatch)
    clone = _repos(tmp_path)
    lock = _old_lock(clone, 60)  # one minute: a git command may still be running
    monkeypatch.setattr(cs, "_lock_held", lambda p: False)
    cs.pull(clone)
    assert lock.exists()
    errs = [e for e in _entries(errors) if not e.get("fix")]
    assert errs and errs[0]["source"] == "sync:pull"
    assert error_log.classify(errs[0]["raw"])["cause"] == "git is locked by a crashed command"


def test_a_lock_a_live_process_holds_is_never_removed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    clone = _repos(tmp_path)
    lock = _old_lock(clone, 3 * 3600)
    monkeypatch.setattr(cs, "_lock_held", lambda p: True)
    assert cs.heal_stale_index_lock(clone) is False
    assert lock.exists()


def test_if_the_holder_check_itself_fails_the_lock_stays(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    clone = _repos(tmp_path)
    lock = _old_lock(clone, 3 * 3600)

    def boom(p):
        raise OSError("lsof missing")
    monkeypatch.setattr(cs, "_lock_held", boom)
    assert cs.heal_stale_index_lock(clone) is False
    assert lock.exists()


def test_no_lock_is_a_no_op(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    clone = _repos(tmp_path)
    assert cs.heal_stale_index_lock(clone) is False


def test_real_lsof_check_sees_an_open_lock(tmp_path):
    lock = tmp_path / "index.lock"
    lock.write_text("")
    with open(lock):
        assert cs._lock_held(lock) is True
    assert cs._lock_held(lock) is False


def test_every_failure_kind_written_to_sync_log_also_reaches_the_error_log(tmp_path, monkeypatch):
    errors = _setup(tmp_path, monkeypatch)
    repo = tmp_path
    for action, summary in [("pull", "CONFLICT merging origin/main — merge aborted:\nCONFLICT (content)"),
                            ("push", "commit failed:\nfatal: Unable to create '/x/.git/index.lock': File exists."),
                            ("push", "push failed even after merge retry:\nerror connecting to api.github.com"),
                            ("pull", "REFUSING to run — conflict markers"),
                            ("pull", "pulled cleanly, but restoring local WIP conflicted — stash preserved")]:
        cs._log(repo, action, summary)
    cs._log(repo, "pull", "merged abc..def")
    cs._log(repo, "push", "committed + pushed 2 file(s)")
    got = _entries(errors)
    assert [e["source"] for e in got] == ["sync:pull", "sync:push", "sync:push", "sync:pull", "sync:pull"]
    assert got[1]["message"].startswith("commit failed")


def test_lsof_is_found_on_path_not_at_the_mac_location(monkeypatch, tmp_path):
    # Kali installs lsof in /usr/bin; the Mac path /usr/sbin/lsof does not exist there (ADR 0069).
    import code_sync
    seen = {}
    monkeypatch.setattr(code_sync.shutil, "which", lambda name: "/usr/bin/lsof" if name == "lsof" else None)
    monkeypatch.setattr(code_sync.subprocess, "run",
                        lambda cmd, **k: seen.setdefault("cmd", cmd) and __import__("subprocess").CompletedProcess(cmd, 1))
    code_sync._lock_held(tmp_path / "index.lock")
    assert seen["cmd"][0] == "/usr/bin/lsof"
