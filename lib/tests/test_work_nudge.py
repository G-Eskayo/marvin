"""Tests for work_nudge.py (#854): a helper or builder starting tells the map's Work half, from the installed checkout only.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_work_nudge.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import work_nudge  # noqa: E402


def installed(tmp_path):
    repo = tmp_path / "home" / ".agents"
    (repo / "brain-map" / "scripts").mkdir(parents=True)
    (repo / work_nudge.SCRIPT).write_text("")
    return repo, tmp_path / "home"


def test_the_installed_checkout_starts_the_writer_detached(tmp_path):
    repo, home = installed(tmp_path)
    calls = []
    assert work_nudge.nudge(repo, home, popen=lambda args, **kw: calls.append((args, kw)))
    (args, kw), = calls
    assert args[-1] == str(repo / work_nudge.SCRIPT)
    assert kw["start_new_session"] is True


def test_a_worktree_or_a_test_home_never_writes_the_live_map(tmp_path):
    repo, _home = installed(tmp_path)
    calls = []
    assert not work_nudge.nudge(repo, tmp_path / "other-home", popen=lambda *a, **k: calls.append(a))
    assert calls == []


def test_no_writer_script_means_no_nudge(tmp_path):
    repo, home = installed(tmp_path)
    (repo / work_nudge.SCRIPT).unlink()
    assert not work_nudge.nudge(repo, home, popen=lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))


def test_a_writer_that_cannot_start_never_raises(tmp_path):
    repo, home = installed(tmp_path)

    def boom(*_a, **_k):
        raise OSError("fork failed")
    assert work_nudge.nudge(repo, home, popen=boom) is False
