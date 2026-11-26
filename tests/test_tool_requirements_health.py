#!/usr/bin/env python3
"""Tests for lib/tool_requirements.py health checking (tests 18-24 from the plan)."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import tool_requirements as tr


# ─── Test 18: health() runs pytest collection and parses catalog ──────────

def test_health_collects_tools():
    """health() runs pytest and captures tool catalog."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "tests"
        test_dir.mkdir()

        # Create a minimal test file with requires_tool marker
        test_file = test_dir / "test_example.py"
        test_file.write_text("""
import pytest

@pytest.mark.requires_tool("rg")
def test_something():
    pass
""")

        # Mock subprocess to return a catalog
        def mock_run(*args, **kwargs):
            if "pytest" in str(args):
                return MagicMock(
                    returncode=0,
                    stdout="",
                    stderr=json.dumps({"tools": ["rg"], "paths": []})
                )

        with patch("tool_requirements.subprocess.run", side_effect=mock_run):
            result = tr.health(test_root=test_dir)
            assert "rg" in result.available or "rg" in result.unavailable


# ─── Test 19: health() returns empty when no tests exist ────────────────────

def test_health_empty_test_dir():
    """health() returns empty result when test directory doesn't exist."""
    result = tr.health(test_root=Path("/nonexistent/tests"))
    assert result.available == {}
    assert result.unavailable == []


def test_health_no_test_files():
    """health() returns empty result when no test files are found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "tests"
        test_dir.mkdir()

        result = tr.health(test_root=test_dir)
        assert result.available == {}
        assert result.unavailable == []


# ─── Test 20: health() checks tools via shutil.which ────────────────────────

def test_health_finds_available_tool():
    """health() returns True for tools that exist on PATH."""
    catalog = {"tools": ["python3"], "paths": []}

    with patch("tool_requirements.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=json.dumps(catalog)
        )
        with patch("tool_requirements.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/python3"

            result = tr.health()
            assert result.available.get("python3") is True
            assert "python3" not in result.unavailable


def test_health_detects_missing_tool():
    """health() returns False for tools that don't exist on PATH."""
    catalog = {"tools": ["nonexistent-tool-xyz"], "paths": []}

    with patch("tool_requirements.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=json.dumps(catalog)
        )
        with patch("tool_requirements.shutil.which") as mock_which:
            mock_which.return_value = None

            result = tr.health()
            assert result.available.get("nonexistent-tool-xyz") is False
            assert "nonexistent-tool-xyz" in result.unavailable


# ─── Test 21: health() checks paths via os.path.exists ────────────────────

def test_health_finds_available_path():
    """health() returns True for paths that exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "exists"
        test_path.mkdir()

        catalog = {"tools": [], "paths": [str(test_path)]}

        with patch("tool_requirements.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=json.dumps(catalog)
            )

            result = tr.health()
            assert result.available.get(str(test_path)) is True
            assert str(test_path) not in result.unavailable


def test_health_detects_missing_path():
    """health() returns False for paths that don't exist."""
    catalog = {"tools": [], "paths": ["/nonexistent/path/that/should/not/exist"]}

    with patch("tool_requirements.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=json.dumps(catalog)
        )

        result = tr.health()
        assert result.available.get("/nonexistent/path/that/should/not/exist") is False
        assert "/nonexistent/path/that/should/not/exist" in result.unavailable


# ─── Test 22: health() expands ~ in paths ───────────────────────────────────

def test_health_expands_home_in_paths():
    """health() expands ~ to home directory when checking paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Simulate a path with ~ in it
        catalog = {"tools": [], "paths": ["~/.test-path"]}

        with patch("tool_requirements.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=json.dumps(catalog)
            )
            with patch("tool_requirements.os.path.exists") as mock_exists:
                mock_exists.return_value = False

                result = tr.health()
                # Should have checked the expanded path
                assert mock_exists.called
                # Should record it as unavailable
                assert "~/.test-path" in result.unavailable


# ─── Test 23: health() handles malformed JSON ────────────────────────────────

def test_health_handles_no_json():
    """health() returns empty result when pytest output has no JSON."""
    with patch("tool_requirements.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="some normal output",
            stderr="some error output"
        )

        result = tr.health()
        assert result.available == {}
        assert result.unavailable == []


def test_health_handles_subprocess_timeout():
    """health() returns timeout message when pytest collection times out."""
    with patch("tool_requirements.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("pytest", 60)

        result = tr.health()
        assert "(collection timed out)" in result.unavailable


def test_health_handles_subprocess_exception():
    """health() returns error message when pytest collection fails."""
    with patch("tool_requirements.subprocess.run") as mock_run:
        mock_run.side_effect = Exception("Some error")

        result = tr.health()
        assert any("collection failed" in msg for msg in result.unavailable)


# ─── Test 24: main() CLI entrypoint returns correct exit codes ──────────────

def test_main_health_command_success():
    """main() with 'health' returns 0 when all tools available."""
    with patch("tool_requirements.health") as mock_health:
        mock_health.return_value = tr.ToolHealth(available={"rg": True}, unavailable=[])

        with patch("sys.argv", ["tool_requirements.py", "health"]):
            with patch("tool_requirements.print") as mock_print:
                exit_code = tr.main()
                assert exit_code == 0


def test_main_health_command_failure():
    """main() with 'health' returns 1 when tools are missing."""
    with patch("tool_requirements.health") as mock_health:
        mock_health.return_value = tr.ToolHealth(
            available={"rg": False},
            unavailable=["rg"]
        )

        with patch("sys.argv", ["tool_requirements.py", "health"]):
            with patch("tool_requirements.print") as mock_print:
                exit_code = tr.main()
                assert exit_code == 1


def test_main_no_args_shows_usage():
    """main() with no args returns 1 and shows usage."""
    with patch("sys.argv", ["tool_requirements.py"]):
        with patch("tool_requirements.print") as mock_print:
            exit_code = tr.main()
            assert exit_code == 1
            # Should have printed usage
            assert mock_print.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
