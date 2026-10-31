#!/usr/bin/env python3
"""Tests for disposable_basetemp() context manager and regex matching."""
from __future__ import annotations

import os
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
        assert "pytest-ctl-" in path.name
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
    """PYTEST_BASETEMP_RE matches pytest-ctl-<hex> pattern for disposable basetemps."""
    assert cs.PYTEST_BASETEMP_RE.match("pytest-ctl-abc12345")
    assert cs.PYTEST_BASETEMP_RE.match("pytest-ctl-deadbeef")
    assert cs.PYTEST_BASETEMP_RE.match("pytest-ctl-00000000")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-ctl-")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-ctl-gg")  # invalid hex
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-ctl")


def test_pytest_basetemp_re_rejects_unrelated_names():
    """PYTEST_BASETEMP_RE does not match unrelated folder names."""
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-of-user")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-current")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest")
    assert not cs.PYTEST_BASETEMP_RE.match("pytest-")
    assert not cs.PYTEST_BASETEMP_RE.match("mr-merge-gate-abc")
