"""Tests for claude_bin.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_claude_bin.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import pytest

import claude_bin as cb  # noqa: E402


def test_returns_the_path_lookup_when_claude_is_on_path(monkeypatch):
    monkeypatch.setattr(cb.shutil, "which", lambda name: "/usr/bin/claude")
    assert cb.resolve_claude_bin() == "/usr/bin/claude"


def test_falls_back_to_the_first_existing_candidate(monkeypatch, tmp_path):
    real_candidate = tmp_path / "opt" / "claude"
    real_candidate.parent.mkdir(parents=True)
    real_candidate.write_text("")
    missing_candidate = tmp_path / "does-not-exist" / "claude"

    monkeypatch.setattr(cb.shutil, "which", lambda name: None)
    monkeypatch.setattr(cb, "_candidates", lambda: (missing_candidate, real_candidate))

    assert cb.resolve_claude_bin() == str(real_candidate)


def test_prefers_an_earlier_candidate_over_a_later_one_that_also_exists(monkeypatch, tmp_path):
    first = tmp_path / "first" / "claude"
    second = tmp_path / "second" / "claude"
    for p in (first, second):
        p.parent.mkdir(parents=True)
        p.write_text("")

    monkeypatch.setattr(cb.shutil, "which", lambda name: None)
    monkeypatch.setattr(cb, "_candidates", lambda: (first, second))

    assert cb.resolve_claude_bin() == str(first)


def test_raises_file_not_found_when_no_candidate_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(cb.shutil, "which", lambda name: None)
    monkeypatch.setattr(cb, "_candidates", lambda: (tmp_path / "nope" / "claude",))

    with pytest.raises(FileNotFoundError):
        cb.resolve_claude_bin()


def test_default_candidates_include_the_three_known_install_locations():
    candidates = cb._candidates()
    assert candidates == (
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    )
