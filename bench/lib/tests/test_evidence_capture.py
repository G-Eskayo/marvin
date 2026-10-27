"""Tests for evidence_capture.py — git snapshot capture."""
import subprocess
import tempfile
from pathlib import Path

import pytest

from evidence_capture import capture_snapshot, CodeSnapshot


class TestEvidenceCapture:
    """Test capture_snapshot() on real git repositories."""

    def test_capture_non_git_dir_returns_none(self):
        """capture_snapshot() should return None for non-git directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = capture_snapshot(Path(tmpdir))

            assert result is None

    def test_capture_git_clean_repo(self):
        """capture_snapshot() on clean git repo should show no changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(
                ["git", "init"],
                cwd=tmpdir_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=tmpdir_path,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=tmpdir_path,
                capture_output=True,
            )

            # Create and commit a file
            (tmpdir_path / "test.txt").write_text("hello")
            subprocess.run(
                ["git", "add", "test.txt"],
                cwd=tmpdir_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=tmpdir_path,
                capture_output=True,
                check=True,
            )

            # Capture snapshot of clean repo
            result = capture_snapshot(tmpdir_path)

            assert result is not None
            assert isinstance(result, CodeSnapshot)
            assert result.git_status.strip() == ""  # No changes
            assert result.changed_files == []

    def test_capture_git_dirty_repo(self):
        """capture_snapshot() should detect modified files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(
                ["git", "init"],
                cwd=tmpdir_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=tmpdir_path,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=tmpdir_path,
                capture_output=True,
            )

            # Create and commit a file
            (tmpdir_path / "test.txt").write_text("hello")
            subprocess.run(
                ["git", "add", "test.txt"],
                cwd=tmpdir_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=tmpdir_path,
                capture_output=True,
                check=True,
            )

            # Modify the file
            (tmpdir_path / "test.txt").write_text("world")

            # Capture snapshot of dirty repo
            result = capture_snapshot(tmpdir_path)

            assert result is not None
            assert result.git_status.strip()  # Should show changes
            assert "test.txt" in result.changed_files

    def test_capture_git_new_file(self):
        """capture_snapshot() should detect new untracked files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(
                ["git", "init"],
                cwd=tmpdir_path,
                capture_output=True,
                check=True,
            )

            # Create a new file (untracked)
            (tmpdir_path / "new.txt").write_text("new")

            # Capture snapshot
            result = capture_snapshot(tmpdir_path)

            assert result is not None
            assert "new.txt" in result.git_status or "new.txt" in result.changed_files

    def test_code_snapshot_to_dict(self):
        """CodeSnapshot.to_dict() should serialize properly."""
        snap = CodeSnapshot(
            git_status="M file.py\n",
            git_diff="--- a/file.py\n+++ b/file.py\n",
            changed_files=["file.py"],
        )

        d = snap.to_dict()

        assert d["git_status"] == "M file.py\n"
        assert "file.py" in d["git_diff"]
        assert d["changed_files"] == ["file.py"]


class TestEvidenceCaptureRobustness:
    """Test capture_snapshot() error handling."""

    def test_capture_handles_missing_dir(self):
        """capture_snapshot() should handle missing directories gracefully."""
        result = capture_snapshot(Path("/nonexistent/path/xyz"))

        assert result is None

    def test_capture_truncates_large_diffs(self):
        """CodeSnapshot.to_dict() should truncate large diffs."""
        snap = CodeSnapshot(
            git_status="M file.py\n",
            git_diff="x" * 20000,  # Large diff
            changed_files=["file.py"],
        )

        d = snap.to_dict()

        # Should be truncated to 10000 chars
        assert len(d["git_diff"]) <= 10000
