"""Tests for clone_sweep.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_clone_sweep.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import clone_sweep as cs  # noqa: E402


# ── _darwin_user_roots ────────────────────────────────────────────────────

def test_darwin_user_roots_returns_set():
    roots = cs._darwin_user_roots()
    assert isinstance(roots, set)


def test_darwin_user_roots_deduplicates(monkeypatch):
    # If both DARWIN_USER_TEMP_DIR and DARWIN_USER_CACHE_DIR point to the same place,
    # the result is still a set (no duplicates)
    import subprocess

    call_count = [0]
    def mock_run(cmd, *args, **kwargs):
        call_count[0] += 1
        result = type('obj', (object,), {
            'stdout': '/var/tmp\n',
            'returncode': 0
        })()
        return result

    monkeypatch.setattr("subprocess.run", mock_run)
    roots = cs._darwin_user_roots()
    # Both calls return the same path, so set deduplicates it
    assert len(roots) == 1
    assert call_count[0] == 2


def test_darwin_user_roots_fails_closed(monkeypatch):
    # If the system doesn't have these vars, we get an empty set, not an exception
    import subprocess

    def mock_run(cmd, *args, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr("subprocess.run", mock_run)
    roots = cs._darwin_user_roots()
    # Both calls fail, so we get an empty set (fail-closed)
    assert isinstance(roots, set)
    assert len(roots) == 0


# ── _looks_like_clone ──────────────────────────────────────────────────────

def test_looks_like_clone_rejects_symlinks(tmp_path):
    symlink = tmp_path / "code_sign_clone.1"
    target = tmp_path / "target"
    target.mkdir()
    symlink.symlink_to(target)
    assert not cs._looks_like_clone(symlink)


def test_looks_like_clone_accepts_matching_directory(tmp_path):
    parent = tmp_path / "something.code_sign_clone"
    parent.mkdir()
    entry = parent / "code_sign_clone.123"
    entry.mkdir()
    assert cs._looks_like_clone(entry)


def test_looks_like_clone_rejects_wrong_parent_suffix(tmp_path):
    parent = tmp_path / "something_code_sign_clone"  # missing dot
    parent.mkdir()
    entry = parent / "code_sign_clone.123"
    entry.mkdir()
    assert not cs._looks_like_clone(entry)


def test_looks_like_clone_rejects_wrong_entry_prefix(tmp_path):
    parent = tmp_path / "something.code_sign_clone"
    parent.mkdir()
    entry = parent / "code_sign.123"  # wrong prefix
    entry.mkdir()
    assert not cs._looks_like_clone(entry)


# ── _default_list_clones ────────────────────────────────────────────────────

def test_default_list_clones_returns_list(monkeypatch, tmp_path):
    # Mock _darwin_user_roots to avoid calling real getconf
    parent = tmp_path / "something.code_sign_clone"
    parent.mkdir()
    entry = parent / "code_sign_clone.123"
    entry.mkdir()

    monkeypatch.setattr(cs, "_darwin_user_roots", lambda: {tmp_path})
    clones = cs._default_list_clones(min_age_hours=0)
    assert isinstance(clones, list)
    for clone in clones:
        assert "path" in clone
        assert "age_hours" in clone


def test_default_list_clones_age_filter(tmp_path, monkeypatch):
    import time

    parent = tmp_path / "something.code_sign_clone"
    parent.mkdir()
    entry = parent / "code_sign_clone.123"
    entry.mkdir()

    # Set the entry's mtime to now (age ~ 0 hours)
    now = time.time()
    entry.touch()

    # Monkeypatch _darwin_user_roots to return our temp dir
    monkeypatch.setattr(cs, "_darwin_user_roots", lambda: {tmp_path})

    # With min_age_hours=0, should find it
    clones = cs._default_list_clones(min_age_hours=0)
    assert len(clones) >= 1
    assert any(c["path"] == entry for c in clones)

    # With high min_age_hours, should not find it (too new)
    clones = cs._default_list_clones(min_age_hours=100)
    assert not any(c["path"] == entry for c in clones)


# ── _default_is_open ──────────────────────────────────────────────────────

def test_default_is_open_returns_bool_or_none(monkeypatch):
    import subprocess

    def mock_run(*args, **kwargs):
        result = type('obj', (object,), {
            'stdout': 'n/var/tmp/somefile\n'
        })()
        return result

    monkeypatch.setattr("subprocess.run", mock_run)
    result = cs._default_is_open(Path("/some/path"))
    assert isinstance(result, bool)


def test_default_is_open_closed_path(monkeypatch):
    import subprocess

    # Most paths on the system aren't open by any process
    def mock_run(*args, **kwargs):
        result = type('obj', (object,), {
            'stdout': 'n/var/tmp/other\n'
        })()
        return result

    monkeypatch.setattr("subprocess.run", mock_run)
    result = cs._default_is_open(Path("/tmp/nonexistent_path_xyz_12345"))
    # Should return False because the path is not in lsof output
    assert result is False


def test_default_is_open_timeout_returns_none(monkeypatch):
    import subprocess

    def mock_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", 1)

    monkeypatch.setattr("subprocess.run", mock_run)
    result = cs._default_is_open(Path("/some/path"))
    assert result is None


def test_default_is_open_resolves_var_symlink_before_matching(monkeypatch, tmp_path):
    import subprocess

    # Create a real target and a symlink to it
    target = tmp_path / "real_target"
    target.mkdir()
    symlink = tmp_path / "symlink_to_target"
    symlink.symlink_to(target)

    # Mock subprocess.run to return the RESOLVED path in lsof output
    def mock_run(*args, **kwargs):
        resolved_str = str(target.resolve())
        result = type('obj', (object,), {
            'stdout': f'n{resolved_str}\n'
        })()
        return result

    monkeypatch.setattr("subprocess.run", mock_run)
    # Call with the symlink path; should resolve it and match
    result = cs._default_is_open(symlink)
    assert result is True


def test_default_is_open_no_match_returns_false(monkeypatch, tmp_path):
    import subprocess

    # Mock subprocess.run to return lsof output without the queried path
    def mock_run(*args, **kwargs):
        result = type('obj', (object,), {
            'stdout': 'n/other/path\nn/another/path\n'
        })()
        return result

    monkeypatch.setattr("subprocess.run", mock_run)
    # Query a path not in the lsof output
    result = cs._default_is_open(tmp_path / "not_in_lsof")
    assert result is False


# ── find_orphan_clones ─────────────────────────────────────────────────────

def test_find_orphan_clones_returns_list(monkeypatch):
    # Mock _default_list_clones to avoid calling real getconf/lsof
    monkeypatch.setattr(cs, "_default_list_clones", lambda min_age_hours, **kw: [])
    orphans = cs.find_orphan_clones(min_age_hours=0)
    assert isinstance(orphans, list)


def test_find_orphan_clones_fail_closed_on_true():
    """If is_open returns True, the clone is skipped (fail-closed)."""
    clones_found = [{"path": Path("/some/path"), "age_hours": 10}]

    def always_true(path):
        return True

    # Patch _default_list_clones to return our mock clones
    original_list = cs._default_list_clones

    try:
        cs._default_list_clones = lambda min_age_hours=cs.MIN_AGE_HOURS, **kw: clones_found
        orphans = cs.find_orphan_clones(
            min_age_hours=0,
            is_open=always_true,
        )
        # If is_open always returns True, no clones should be removed
        assert orphans == []
    finally:
        cs._default_list_clones = original_list


def test_find_orphan_clones_fail_closed_on_none():
    """If is_open returns None (error), the clone is skipped (fail-closed)."""
    clones_found = [{"path": Path("/some/path"), "age_hours": 10}]

    def always_none(path):
        return None

    original_list = cs._default_list_clones

    try:
        cs._default_list_clones = lambda min_age_hours=cs.MIN_AGE_HOURS, **kw: clones_found
        orphans = cs.find_orphan_clones(
            min_age_hours=0,
            is_open=always_none,
        )
        # If is_open always returns None (transient error), no clones should be removed
        assert orphans == []
    finally:
        cs._default_list_clones = original_list


def test_find_orphan_clones_proceeds_on_false():
    """If is_open returns False and recheck also returns False, clone is orphan."""
    clones_found = [{"path": Path("/some/path"), "age_hours": 10}]

    def always_false(path):
        return False

    original_list = cs._default_list_clones

    try:
        cs._default_list_clones = lambda min_age_hours=cs.MIN_AGE_HOURS, **kw: clones_found
        orphans = cs.find_orphan_clones(
            min_age_hours=0,
            is_open=always_false,
        )
        # If is_open always returns False, the clone is an orphan
        assert len(orphans) == 1
        assert orphans[0]["path"] == Path("/some/path")
    finally:
        cs._default_list_clones = original_list


def test_find_orphan_clones_recheck_fail_closed_on_none():
    """If recheck returns None after initial False, clone is skipped (fail-closed)."""
    clones_found = [{"path": Path("/some/path"), "age_hours": 10}]
    call_count = [0]

    def sometimes_none(path):
        call_count[0] += 1
        # First call returns False, second (recheck) returns None
        return False if call_count[0] == 1 else None

    original_list = cs._default_list_clones

    try:
        cs._default_list_clones = lambda min_age_hours=cs.MIN_AGE_HOURS, **kw: clones_found
        orphans = cs.find_orphan_clones(
            min_age_hours=0,
            is_open=sometimes_none,
        )
        # Recheck returned None, so fail-closed: not removed
        assert orphans == []
    finally:
        cs._default_list_clones = original_list


def test_find_orphan_clones_recheck_fail_closed_on_true():
    """If recheck returns True after initial False, clone is skipped (fail-closed)."""
    clones_found = [{"path": Path("/some/path"), "age_hours": 10}]
    call_count = [0]

    def sometimes_true(path):
        call_count[0] += 1
        # First call returns False, second (recheck) returns True
        return False if call_count[0] == 1 else True

    original_list = cs._default_list_clones

    try:
        cs._default_list_clones = lambda min_age_hours=cs.MIN_AGE_HOURS, **kw: clones_found
        orphans = cs.find_orphan_clones(
            min_age_hours=0,
            is_open=sometimes_true,
        )
        # Recheck returned True (path became open), so fail-closed: not removed
        assert orphans == []
    finally:
        cs._default_list_clones = original_list


# ── sweep_clones ──────────────────────────────────────────────────────────

def test_sweep_clones_returns_list(monkeypatch):
    # Mock find_clones to avoid calling real system commands
    monkeypatch.setattr(cs, "find_orphan_clones", lambda min_age_hours, is_open: [])
    removed = cs.sweep_clones()
    assert isinstance(removed, list)


def test_sweep_clones_removes_directories(tmp_path, monkeypatch):
    import time

    parent = tmp_path / "something.code_sign_clone"
    parent.mkdir()
    entry = parent / "code_sign_clone.123"
    entry.mkdir()

    # Create a marker file so we can verify it was removed
    marker = entry / "marker.txt"
    marker.write_text("test")

    def mock_find_clones():
        return [{"path": entry, "age_hours": 10}]

    removed = cs.sweep_clones(is_open=lambda p, **kw: False, find_clones=mock_find_clones)
    assert len(removed) >= 1
    assert not entry.exists()
    assert not marker.exists()


def test_sweep_clones_isolated_on_permission_error(tmp_path, monkeypatch):
    # One failed removal shouldn't stop others from being removed
    entry1 = tmp_path / "clone1"
    entry2 = tmp_path / "clone2"
    entry1.mkdir()
    entry2.mkdir()

    clones = [
        {"path": entry1, "age_hours": 10},
        {"path": entry2, "age_hours": 10},
    ]

    def find_clones():
        return clones

    # Mock shutil.rmtree to raise PermissionError on entry1
    import shutil
    original_rmtree = shutil.rmtree

    def mock_rmtree(path, *args, **kwargs):
        if path == entry1:
            raise PermissionError("denied")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("shutil.rmtree", mock_rmtree)

    # Should still remove entry2 despite entry1's failure (exception isolation)
    removed = cs.sweep_clones(is_open=lambda p, **kw: False, find_clones=find_clones)
    assert entry2 in [r["path"] for r in removed]  # entry2 should be removed successfully
    assert entry1.exists()  # entry1 should still exist (failed to remove)
    assert not entry2.exists()  # entry2 should be removed


def test_sweep_clones_silent_on_filenotfounderror(tmp_path, monkeypatch, capsys):
    # If a clone disappears between listing and removal (race), don't report an error
    clones = [{"path": tmp_path / "nonexistent", "age_hours": 10}]

    def find_clones():
        return clones

    removed = cs.sweep_clones(is_open=lambda p, **kw: False, find_clones=find_clones)

    # Should complete without error (FileNotFoundError is silent)
    assert isinstance(removed, list)
    captured = capsys.readouterr()
    assert "unexpected error" not in captured.err


# ── real-process test ─────────────────────────────────────────────────────

def test_find_and_sweep_clones_real_process(tmp_path, monkeypatch):
    """Real end-to-end test: list, filter, and remove an actual clone directory."""
    import time

    # Set up a real clone structure
    parent = tmp_path / "something.code_sign_clone"
    parent.mkdir()
    clone_entry = parent / "code_sign_clone.123"
    clone_entry.mkdir()

    # Create a marker file inside to verify full removal
    marker = clone_entry / "marker.txt"
    marker.write_text("test marker")

    # Mock _darwin_user_roots to return our tmp dir
    monkeypatch.setattr(cs, "_darwin_user_roots", lambda: {tmp_path})

    # Use always-closed mock for is_open
    def always_closed(path):
        return False

    # Run find_orphan_clones with age filter disabled
    orphans = cs.find_orphan_clones(min_age_hours=0, is_open=always_closed)

    # Should find our clone
    assert any(o["path"] == clone_entry for o in orphans), \
        f"Expected to find {clone_entry} in {orphans}"

    # Run sweep_clones with our mock
    removed = cs.sweep_clones(
        min_age_hours=0,
        is_open=always_closed,
        find_clones=lambda: cs.find_orphan_clones(min_age_hours=0, is_open=always_closed),
    )

    # Should report removal of the clone
    assert any(r["path"] == clone_entry for r in removed)
    # And the clone should actually be gone
    assert not clone_entry.exists()
    assert not marker.exists()
