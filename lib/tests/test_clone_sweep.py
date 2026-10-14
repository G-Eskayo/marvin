"""Tests for clone_sweep.py (Xcode code_sign_clone cleanup, G-Eskayo/marvin#415).

Tests cover detection of code_sign_clone artifacts (*.code_sign_clone/code_sign_clone.*)
and safe removal of orphaned, old artifacts.
"""
import json
import shutil
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import clone_sweep


class TestConstants:
    def test_min_age_constant(self):
        """MIN_AGE_HOURS is set to 1 hour."""
        assert clone_sweep.MIN_AGE_HOURS == 1

    def test_globs_for_code_sign_clone(self):
        """Globs target code_sign_clone pattern."""
        assert clone_sweep.CLONE_PARENT_GLOB == "*.code_sign_clone"
        assert clone_sweep.CLONE_ENTRY_GLOB == "code_sign_clone.*"


class TestDarwinUserRoots:
    def test_darwin_user_roots_calls_getconf(self, monkeypatch):
        """_darwin_user_roots calls getconf for DARWIN_USER_TEMP_DIR and DARWIN_USER_CACHE_DIR."""
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            result = MagicMock()
            if cmd[1] == "DARWIN_USER_TEMP_DIR":
                result.returncode = 0
                result.stdout = "/var/folders/ab/temp\n"
            elif cmd[1] == "DARWIN_USER_CACHE_DIR":
                result.returncode = 0
                result.stdout = "/var/folders/ab/cache\n"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        monkeypatch.setattr("subprocess.run", mock_run)
        roots = clone_sweep._darwin_user_roots()

        assert len(roots) == 2
        assert any("/var/folders/ab/temp" in str(r) for r in roots)
        assert any("/var/folders/ab/cache" in str(r) for r in roots)

    def test_darwin_user_roots_handles_getconf_failure(self, monkeypatch):
        """_darwin_user_roots gracefully handles getconf failures."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            return result

        monkeypatch.setattr("subprocess.run", mock_run)
        roots = clone_sweep._darwin_user_roots()
        assert roots == set()

    def test_darwin_user_roots_deduplicates(self, monkeypatch):
        """_darwin_user_roots returns unique roots (set behavior)."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = "/same/path\n"
            return result

        monkeypatch.setattr("subprocess.run", mock_run)
        roots = clone_sweep._darwin_user_roots()
        assert len(roots) == 1  # Both calls return same path


class TestLooksLikeClone:
    def test_rejects_symlinks(self, tmp_path):
        """_looks_like_clone rejects symlinks explicitly."""
        real = tmp_path / "real.code_sign_clone" / "code_sign_clone.abc"
        real.mkdir(parents=True)

        symlink = tmp_path / "link.code_sign_clone" / "code_sign_clone.xyz"
        symlink.parent.mkdir(parents=True)
        symlink.symlink_to(real)

        assert clone_sweep._looks_like_clone(symlink) is False

    def test_checks_parent_suffix(self, tmp_path):
        """_looks_like_clone checks parent ends with .code_sign_clone."""
        good = tmp_path / "foo.code_sign_clone" / "code_sign_clone.abc"
        good.mkdir(parents=True)

        bad_parent = tmp_path / "foo.other" / "code_sign_clone.abc"
        bad_parent.mkdir(parents=True)

        assert clone_sweep._looks_like_clone(good) is True
        assert clone_sweep._looks_like_clone(bad_parent) is False

    def test_checks_entry_prefix(self, tmp_path):
        """_looks_like_clone checks entry starts with code_sign_clone."""
        good = tmp_path / "foo.code_sign_clone" / "code_sign_clone.abc"
        good.mkdir(parents=True)

        bad_entry = tmp_path / "foo.code_sign_clone" / "other.abc"
        bad_entry.mkdir(parents=True)

        assert clone_sweep._looks_like_clone(good) is True
        assert clone_sweep._looks_like_clone(bad_entry) is False

    def test_pattern_exact_match(self, tmp_path):
        """_looks_like_clone requires both parent suffix AND entry prefix."""
        # Good: matches both
        good = tmp_path / "a.code_sign_clone" / "code_sign_clone.x"
        good.mkdir(parents=True)
        assert clone_sweep._looks_like_clone(good) is True

        # Bad: only parent matches
        bad1 = tmp_path / "b.code_sign_clone" / "other.y"
        bad1.mkdir(parents=True)
        assert clone_sweep._looks_like_clone(bad1) is False

        # Bad: only entry matches
        bad2 = tmp_path / "c.other" / "code_sign_clone.z"
        bad2.mkdir(parents=True)
        assert clone_sweep._looks_like_clone(bad2) is False


class TestListClones:
    def test_lists_clones_from_darwin_roots(self, tmp_path, monkeypatch):
        """_default_list_clones iterates _darwin_user_roots() and globs two levels deep."""
        temp_root = tmp_path / "temp"
        cache_root = tmp_path / "cache"
        temp_root.mkdir()
        cache_root.mkdir()

        # Create code_sign_clone entries in both roots
        (temp_root / "build.code_sign_clone" / "code_sign_clone.abc").mkdir(parents=True)
        (cache_root / "xcode.code_sign_clone" / "code_sign_clone.def").mkdir(parents=True)

        def mock_darwin_roots():
            return {temp_root, cache_root}

        monkeypatch.setattr(clone_sweep, "_darwin_user_roots", mock_darwin_roots)
        clones = clone_sweep._default_list_clones()

        assert len(clones) == 2
        paths = {str(c["path"]) for c in clones}
        assert any("code_sign_clone.abc" in p for p in paths)
        assert any("code_sign_clone.def" in p for p in paths)

    def test_returns_age_hours(self, tmp_path, monkeypatch):
        """_default_list_clones returns age_hours for each clone."""
        root = tmp_path / "temp"
        root.mkdir()
        clone = root / "build.code_sign_clone" / "code_sign_clone.abc"
        clone.mkdir(parents=True)

        # Set mtime to 2 hours ago
        mtime = time.time() - 7200
        import os
        os.utime(clone, (mtime, mtime))

        def mock_darwin_roots():
            return {root}

        monkeypatch.setattr(clone_sweep, "_darwin_user_roots", mock_darwin_roots)
        clones = clone_sweep._default_list_clones()

        assert len(clones) == 1
        assert clones[0]["age_hours"] >= 1.9 and clones[0]["age_hours"] <= 2.1

    def test_guards_against_filenotfound(self, tmp_path, monkeypatch):
        """_default_list_clones skips entries that disappear during iteration."""
        root = tmp_path / "temp"
        root.mkdir()
        clone = root / "build.code_sign_clone" / "code_sign_clone.abc"
        clone.mkdir(parents=True)

        def mock_darwin_roots():
            return {root}

        original_stat = Path.stat

        def mock_stat(self):
            if "code_sign_clone" in str(self):
                raise FileNotFoundError("Vanished")
            return original_stat(self)

        monkeypatch.setattr(clone_sweep, "_darwin_user_roots", mock_darwin_roots)
        monkeypatch.setattr(Path, "stat", mock_stat)
        clones = clone_sweep._default_list_clones()

        # Should return empty despite the clone directory existing (guarded by exception)
        assert clones == []

    def test_skips_nondir_entries(self, tmp_path, monkeypatch):
        """_default_list_clones skips non-directory entries."""
        root = tmp_path / "temp"
        root.mkdir()
        parent = root / "build.code_sign_clone"
        parent.mkdir()
        file_entry = parent / "code_sign_clone.txt"
        file_entry.write_text("not a dir")
        dir_entry = parent / "code_sign_clone.abc"
        dir_entry.mkdir()

        def mock_darwin_roots():
            return {root}

        monkeypatch.setattr(clone_sweep, "_darwin_user_roots", mock_darwin_roots)
        clones = clone_sweep._default_list_clones()

        assert len(clones) == 1
        assert "code_sign_clone.abc" in str(clones[0]["path"])


class TestDefaultIsOpen:
    def test_returns_false_when_lsof_nonzero(self, tmp_path):
        """_default_is_open returns False when lsof exits non-zero."""
        with patch("subprocess.run") as mock_run:
            result = MagicMock()
            result.returncode = 1  # no processes hold the path
            mock_run.return_value = result

            ret = clone_sweep._default_is_open(tmp_path / "test")
            assert ret is False

    def test_returns_true_when_lsof_zero(self, tmp_path):
        """_default_is_open returns True when lsof exits zero."""
        with patch("subprocess.run") as mock_run:
            result = MagicMock()
            result.returncode = 0  # processes hold the path
            mock_run.return_value = result

            ret = clone_sweep._default_is_open(tmp_path / "test")
            assert ret is True

    def test_returns_none_on_oserror(self, tmp_path):
        """_default_is_open returns None when lsof raises OSError."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("lsof not found")

            ret = clone_sweep._default_is_open(tmp_path / "test")
            assert ret is None

    def test_returns_none_on_timeout(self, tmp_path):
        """_default_is_open returns None when lsof times out."""
        import subprocess
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("lsof", 5)

            ret = clone_sweep._default_is_open(tmp_path / "test")
            assert ret is None

    def test_lsof_command_format(self, tmp_path):
        """_default_is_open calls lsof with correct flags."""
        with patch("subprocess.run") as mock_run:
            result = MagicMock()
            result.returncode = 1
            mock_run.return_value = result

            clone_sweep._default_is_open(tmp_path / "test")

            call_args = mock_run.call_args[0][0]
            assert "/usr/sbin/lsof" in str(call_args[0])
            assert "-n" in call_args
            assert "-P" in call_args
            assert "+c" in call_args
            assert "-F" in call_args
            assert "n" in call_args


class TestFindOrphanClones:
    def test_filters_by_age(self, tmp_path):
        """find_orphan_clones skips clones younger than min_age_hours."""
        def mock_list():
            return [
                {"path": tmp_path / "old.code_sign_clone" / "code_sign_clone.1", "age_hours": 5.0},
                {"path": tmp_path / "new.code_sign_clone" / "code_sign_clone.2", "age_hours": 0.5},
            ]

        def mock_is_open(p):
            return False

        # Create the directories
        (tmp_path / "old.code_sign_clone" / "code_sign_clone.1").mkdir(parents=True)
        (tmp_path / "new.code_sign_clone" / "code_sign_clone.2").mkdir(parents=True)

        orphans = clone_sweep.find_orphan_clones(
            min_age_hours=1.0, list_clones=mock_list, is_open=mock_is_open
        )

        assert len(orphans) == 1
        assert "old" in str(orphans[0]["path"])

    def test_skips_open_clones(self, tmp_path):
        """find_orphan_clones skips clones that are currently open."""
        open_path = tmp_path / "open.code_sign_clone" / "code_sign_clone.1"
        closed_path = tmp_path / "closed.code_sign_clone" / "code_sign_clone.2"
        open_path.mkdir(parents=True)
        closed_path.mkdir(parents=True)

        def mock_list():
            return [
                {"path": open_path, "age_hours": 5.0},
                {"path": closed_path, "age_hours": 5.0},
            ]

        def mock_is_open(p):
            return p == open_path

        orphans = clone_sweep.find_orphan_clones(
            min_age_hours=1.0, list_clones=mock_list, is_open=mock_is_open
        )

        assert len(orphans) == 1
        assert orphans[0]["path"] == closed_path

    def test_rechecks_for_race_condition(self, tmp_path):
        """find_orphan_clones rechecks is_open to guard against races."""
        def mock_list():
            return [{"path": tmp_path / "race.code_sign_clone" / "code_sign_clone.x", "age_hours": 5.0}]

        call_count = [0]

        def mock_is_open(p):
            call_count[0] += 1
            if call_count[0] == 1:
                return False  # first: not open
            else:
                return True  # second: opened by race

        (tmp_path / "race.code_sign_clone" / "code_sign_clone.x").mkdir(parents=True)

        orphans = clone_sweep.find_orphan_clones(
            min_age_hours=1.0, list_clones=mock_list, is_open=mock_is_open
        )

        assert len(orphans) == 0  # Skipped due to race
        assert call_count[0] == 2  # Called twice

    def test_fail_closed_on_lsof_failure(self, tmp_path):
        """find_orphan_clones fails closed when lsof returns None."""
        def mock_list():
            return [{"path": tmp_path / "unclear.code_sign_clone" / "code_sign_clone.x", "age_hours": 5.0}]

        def mock_is_open(p):
            return None  # lsof failed

        (tmp_path / "unclear.code_sign_clone" / "code_sign_clone.x").mkdir(parents=True)

        orphans = clone_sweep.find_orphan_clones(
            min_age_hours=1.0, list_clones=mock_list, is_open=mock_is_open
        )

        assert len(orphans) == 0  # Fail-closed

    def test_per_entry_exception_isolation(self, tmp_path):
        """find_orphan_clones continues after a single entry raises."""
        def mock_list():
            return [
                {"path": tmp_path / "bad.code_sign_clone" / "code_sign_clone.1", "age_hours": 5.0},
                {"path": tmp_path / "good.code_sign_clone" / "code_sign_clone.2", "age_hours": 5.0},
            ]

        def mock_is_open(p):
            if "bad" in str(p):
                raise RuntimeError("Check failed")
            return False

        (tmp_path / "good.code_sign_clone" / "code_sign_clone.2").mkdir(parents=True)

        orphans = clone_sweep.find_orphan_clones(
            min_age_hours=1.0, list_clones=mock_list, is_open=mock_is_open
        )

        assert len(orphans) == 1
        assert "good" in str(orphans[0]["path"])


class TestSweepClones:
    def test_removes_orphans(self, tmp_path):
        """sweep_clones removes orphaned clones."""
        clone = tmp_path / "orphan.code_sign_clone" / "code_sign_clone.xyz"
        clone.mkdir(parents=True)
        (clone / "file.txt").write_text("data")

        def mock_list():
            return [{"path": clone, "age_hours": 5.0}]

        def mock_is_open(p):
            return False

        removed = clone_sweep.sweep_clones(
            list_clones=mock_list, is_open=mock_is_open, min_age_hours=1.0
        )

        assert len(removed) == 1
        assert removed[0]["path"] == clone
        assert "size_kb" in removed[0]
        assert not clone.exists()

    def test_handles_permission_error(self, tmp_path):
        """sweep_clones logs PermissionError."""
        clone = tmp_path / "perm.code_sign_clone" / "code_sign_clone.abc"
        clone.mkdir(parents=True)

        def mock_list():
            return [{"path": clone, "age_hours": 5.0}]

        def mock_is_open(p):
            return False

        with patch("clone_sweep.shutil.rmtree") as mock_rmtree:
            mock_rmtree.side_effect = PermissionError("Denied")

            removed = clone_sweep.sweep_clones(
                list_clones=mock_list, is_open=mock_is_open, min_age_hours=1.0
            )

            assert len(removed) == 1
            assert "error" in removed[0]
            assert "Denied" in removed[0]["error"]

    def test_silently_skips_filenotfound(self, tmp_path):
        """sweep_clones silently skips FileNotFoundError (concurrent removal)."""
        clone = tmp_path / "missing.code_sign_clone" / "code_sign_clone.xyz"
        clone.mkdir(parents=True)

        def mock_list():
            return [{"path": clone, "age_hours": 5.0}]

        def mock_is_open(p):
            return False

        with patch("clone_sweep.shutil.rmtree") as mock_rmtree:
            mock_rmtree.side_effect = FileNotFoundError("Already gone")

            removed = clone_sweep.sweep_clones(
                list_clones=mock_list, is_open=mock_is_open, min_age_hours=1.0
            )

            # FileNotFoundError should not appear in results
            assert len(removed) == 0

    def test_per_entry_exception_isolation_removal(self, tmp_path):
        """sweep_clones continues removing after one fails."""
        clone1 = tmp_path / "bad.code_sign_clone" / "code_sign_clone.1"
        clone2 = tmp_path / "good.code_sign_clone" / "code_sign_clone.2"
        clone1.mkdir(parents=True)
        clone2.mkdir(parents=True)

        def mock_list():
            return [
                {"path": clone1, "age_hours": 5.0},
                {"path": clone2, "age_hours": 5.0},
            ]

        def mock_is_open(p):
            return False

        original_rmtree = shutil.rmtree

        def mock_rmtree(path, *args, **kwargs):
            if "bad" in str(path):
                raise RuntimeError("Removal failed")
            return original_rmtree(path, *args, **kwargs)

        with patch("clone_sweep.shutil.rmtree", mock_rmtree):
            removed = clone_sweep.sweep_clones(
                list_clones=mock_list, is_open=mock_is_open, min_age_hours=1.0
            )

            # Should have removed the good one and reported the error
            assert len(removed) == 2
            assert any("error" in r for r in removed)
            assert any("size_kb" in r for r in removed)

    def test_returns_json_serializable(self, tmp_path):
        """sweep_clones results are JSON-serializable."""
        clone = tmp_path / "test.code_sign_clone" / "code_sign_clone.x"
        clone.mkdir(parents=True)

        def mock_list():
            return [{"path": clone, "age_hours": 5.0}]

        def mock_is_open(p):
            return False

        removed = clone_sweep.sweep_clones(
            list_clones=mock_list, is_open=mock_is_open, min_age_hours=1.0
        )

        # Should not raise when converting to JSON
        json_str = json.dumps([{
            "path": str(r["path"]), **{k: v for k, v in r.items() if k != "path"}
        } for r in removed])
        assert json_str


class TestIntegration:
    def test_no_unbounded_waits(self):
        """clone_sweep doesn't contain time.sleep or asyncio."""
        import inspect

        funcs = [
            clone_sweep.find_orphan_clones,
            clone_sweep.sweep_clones,
        ]

        for func in funcs:
            source = inspect.getsource(func)
            assert "time.sleep" not in source
            assert "asyncio" not in source
