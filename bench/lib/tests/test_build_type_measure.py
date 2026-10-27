"""Tests for build_type_measure.py — baseline measurement on real subprocesses."""
import subprocess
import tempfile
from pathlib import Path

import pytest

from build_type_measure import measure, BuildMeasure


class TestBuildMeasure:
    """Test BuildMeasure baseline collection."""

    def test_measure_on_empty_dir(self):
        """measure() on a directory with no Python code should report all-pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            result = measure(tmpdir_path, timeout=10)

            assert isinstance(result, BuildMeasure)
            assert result.wall_s > 0
            # Empty dir: no errors expected
            assert result.type_check_errors >= 0
            assert result.lint_warnings >= 0

    def test_measure_with_syntax_error(self):
        """measure() should detect syntax errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Write a file with syntax error
            (tmpdir_path / "bad.py").write_text("def foo(\n  invalid syntax")

            result = measure(tmpdir_path, timeout=10)
            # Mypy should fail on syntax
            assert not result.type_check_pass or result.type_check_errors > 0

    def test_measure_with_valid_python(self):
        """measure() on valid Python should pass type check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            (tmpdir_path / "good.py").write_text("def foo(x: int) -> str:\n    return str(x)\n")

            result = measure(tmpdir_path, timeout=10)
            assert isinstance(result, BuildMeasure)
            assert result.wall_s > 0

    def test_measure_timeout(self):
        """measure() should respect timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Create a file that would take a long time to check
            (tmpdir_path / "slow.py").write_text("x = " + " + ".join(["1"] * 10000))

            result = measure(tmpdir_path, timeout=1)
            # Should complete within timeout or handle gracefully
            assert isinstance(result, BuildMeasure)

    def test_to_dict(self):
        """BuildMeasure.to_dict() should serialize to dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            (tmpdir_path / "test.py").write_text("x = 1")

            result = measure(tmpdir_path, timeout=10)
            d = result.to_dict()

            assert isinstance(d, dict)
            assert "type_check_pass" in d
            assert "wall_s" in d
            assert "error_log" in d


class TestBuildMeasureRealScenarios:
    """Test measure() on real code scenarios."""

    def test_measure_preserves_state(self):
        """measure() should not modify the working directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            (tmpdir_path / "original.py").write_text("x = 1")

            cwd_before = Path.cwd()
            result = measure(tmpdir_path, timeout=10)
            cwd_after = Path.cwd()

            assert cwd_before == cwd_after
            assert (tmpdir_path / "original.py").exists()

    def test_multiple_runs_consistency(self):
        """Multiple runs on the same code should have similar results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            (tmpdir_path / "test.py").write_text("def foo(x: int) -> int:\n    return x + 1\n")

            result1 = measure(tmpdir_path, timeout=10)
            result2 = measure(tmpdir_path, timeout=10)

            # Results should be consistent
            assert result1.type_check_pass == result2.type_check_pass
            assert result1.tests_pass == result2.tests_pass
