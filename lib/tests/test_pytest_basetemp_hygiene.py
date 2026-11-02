#!/usr/bin/env python3
"""Tests for disposable_basetemp() context manager and regex matching."""
from __future__ import annotations

import os
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cleanup_sweep as cs


def test_disposable_basetemp_creates_and_cleans_up(tmp_path, monkeypatch):
    """disposable_basetemp yields basetemp args and unconditionally removes the path on exit."""
    monkeypatch.setattr(cs, "TMP_ROOTS", [tmp_path])

    path = None
    with cs.disposable_basetemp() as args:
        assert len(args) == 2
        assert args[0] == "--basetemp"
        path = Path(args[1])
        assert path.exists()
        assert path.name.startswith("marvin-pytest-")
        (path / "test_file.txt").write_text("test")

    assert path is not None
    assert not path.exists(), "disposable_basetemp should remove the path on exit"


def test_disposable_basetemp_cleans_up_even_on_exception(tmp_path, monkeypatch):
    """disposable_basetemp removes the path even if the with block raises."""
    monkeypatch.setattr(cs, "TMP_ROOTS", [tmp_path])

    path = None
    try:
        with cs.disposable_basetemp() as args:
            path = Path(args[1])
            assert path.exists()
            raise ValueError("test error")
    except ValueError:
        pass

    assert path is not None
    assert not path.exists(), "disposable_basetemp should remove the path even on exception"


def test_disposable_basetemp_creates_unique_names(tmp_path, monkeypatch):
    """Multiple calls to disposable_basetemp create non-colliding paths."""
    monkeypatch.setattr(cs, "TMP_ROOTS", [tmp_path])

    with cs.disposable_basetemp() as args1:
        with cs.disposable_basetemp() as args2:
            path1 = Path(args1[1])
            path2 = Path(args2[1])
            assert path1 != path2
            assert path1.exists() and path2.exists()


def test_pytest_basetemp_re_matches_numeric_pattern():
    """PYTEST_BASETEMP_RE matches pytest-<digits> pattern."""
    assert cs.PYTEST_BASETEMP_RE.match("pytest-0")
    assert cs.PYTEST_BASETEMP_RE.match("pytest-123")
    assert cs.PYTEST_BASETEMP_RE.match("pytest-999999")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-abc")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-")


def test_pytest_basetemp_re_matches_ctl_pattern():
    """PYTEST_BASETEMP_RE matches marvin-pytest-<hex> pattern for disposable basetemps."""
    assert cs.PYTEST_BASETEMP_RE.match("marvin-pytest-abc12345")
    assert cs.PYTEST_BASETEMP_RE.match("marvin-pytest-deadbeef")
    assert cs.PYTEST_BASETEMP_RE.match("marvin-pytest-00000000")
    assert not cs.PYTEST_BASETEMP_RE.match("marvin-pytest-")
    assert not cs.PYTEST_BASETEMP_RE.match("marvin-pytest-gg")  # invalid hex
    assert not cs.PYTEST_BASETEMP_RE.match("marvin-pytest")


def test_pytest_basetemp_re_rejects_unrelated_names():
    """PYTEST_BASETEMP_RE does not match unrelated folder names."""
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-of-user")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-current")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-")
    assert not cs.PYTEST_BASETEMP_RE.match("mr-merge-gate-abc")


def test_a_concurrent_plain_pytest_session_never_deletes_a_live_disposable_basetemp(tmp_path, monkeypatch):
    """Every plain pytest session prunes pytest-of-<user>/pytest-* down to its newest 3; a name it can't number parses
    as -1, so it is always the first to go. A disposable basetemp under that prefix was wiped mid-run by any other
    session on the machine (the Rules check's own inner pytest did it), failing every tmp_path setup after it."""
    from _pytest.pathlib import cleanup_numbered_dir
    monkeypatch.setattr(cs, "TMP_ROOTS", [tmp_path])
    with cs.disposable_basetemp() as args:
        live = Path(args[1])
        for n in range(6):
            (live.parent / f"pytest-{n}").mkdir()
        cleanup_numbered_dir(live.parent, "pytest-", keep=3, consider_lock_dead_if_created_before=time.time() + 1)
        assert live.exists(), "another session's retention pass removed a live disposable basetemp"
        assert not (live.parent / "pytest-0").exists()  # the pass itself did run
