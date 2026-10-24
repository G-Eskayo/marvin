"""Tests for brief_fallback.py's fallback builder logic (ADR 0067)."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import brief_fallback as bf  # noqa: E402


# Test 1: _infer_remote_path converts ~/... to $HOME/...
def test_infer_remote_path_home_relative():
    local = str(Path.home() / ".claude" / "briefs" / "2026-10-24.md")
    remote = bf._infer_remote_path(local)
    assert remote == "$HOME/.claude/briefs/2026-10-24.md"


# Test 2: _infer_remote_path preserves absolute paths outside home
def test_infer_remote_path_absolute():
    local = "/tmp/test.md"
    remote = bf._infer_remote_path(local)
    assert remote == "/tmp/test.md"


# Test 3: read_remote with $HOME/ path quotes correctly
def test_read_remote_quoting_with_home():
    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="content", stderr=""))
    bf.read_remote("host", "$HOME/.claude/test.md", run=mock_run)
    # Check that the mock was called with correct arguments
    assert mock_run.called
    call_args = mock_run.call_args
    cmd = call_args[0][0]  # First positional argument is the command list
    cmd_str = " ".join(cmd)
    # Verify $HOME/ is preserved and rest is quoted
    assert "$HOME/" in cmd_str
    assert "cat" in cmd_str


# Test 4: read_remote returns None on ssh failure (not empty string)
def test_read_remote_ssh_failure():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        result = bf.read_remote("host", "$HOME/.claude/test.md")
        assert result is None


# Test 5: read_remote returns None on exception
def test_read_remote_exception():
    with patch.object(subprocess, "run", side_effect=Exception("timeout")):
        result = bf.read_remote("host", "$HOME/.claude/test.md")
        assert result is None


# Test 6: read_remote accepts injectable run parameter
def test_read_remote_injectable_run():
    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="test", stderr=""))
    result = bf.read_remote("host", "$HOME/test.md", run=mock_run)
    assert result == "test"
    mock_run.assert_called_once()


# Test 7: _is_failure_placeholder detects exact failure markers only
def test_is_failure_placeholder_exact_markers():
    # Only these two markers should be detected
    assert bf._is_failure_placeholder("NOT found at /some/path")
    assert bf._is_failure_placeholder("claude call failed: error")
    # These old markers should NOT be detected anymore
    assert not bf._is_failure_placeholder("couldn't measure: unknown")
    assert not bf._is_failure_placeholder("START_FAILED")
    assert not bf._is_failure_placeholder("Traceback (most recent call last)")


# Test 8: _is_failure_placeholder returns False for normal content
def test_is_failure_placeholder_normal():
    content = "# Morning brief\n\n## Needs you\n\n- Review PR #1"
    assert not bf._is_failure_placeholder(content)


# Test 9: produced(local) returns True when file exists and is valid
def test_produced_local_exists_valid(tmp_path):
    brief_file = tmp_path / "2026-10-24.md"
    brief_file.write_text("# Morning brief\n\n## Needs you")
    result = bf.produced("2026-10-24", str(brief_file), remote_host=None)
    assert result is True


# Test 10: produced(local) returns False when file doesn't exist
def test_produced_local_missing(tmp_path):
    result = bf.produced("2026-10-24", str(tmp_path / "missing.md"), remote_host=None)
    assert result is False


# Test 11: produced(local) returns False when file contains failure marker
def test_produced_local_failure_marker(tmp_path):
    brief_file = tmp_path / "2026-10-24.md"
    brief_file.write_text("NOT found at /some/path")
    result = bf.produced("2026-10-24", str(brief_file), remote_host=None)
    assert result is False


# Test 12: produced checks local first before remote
def test_produced_local_first(tmp_path):
    brief_file = tmp_path / "2026-10-24.md"
    brief_file.write_text("# Valid content")

    def mock_read_remote(host, path):
        raise AssertionError("Should not call read_remote when local file exists")

    result = bf.produced("2026-10-24", str(brief_file), "remote-host", read_remote_fn=mock_read_remote)
    assert result is True


# Test 13: produced falls back to remote when local is missing
def test_produced_remote_fallback(tmp_path):
    def mock_read_remote(host, path):
        return "# Remote content"

    result = bf.produced("2026-10-24", str(tmp_path / "missing.md"), "remote-host", read_remote_fn=mock_read_remote)
    assert result is True


# Test 14: produced returns False when remote returns None
def test_produced_remote_returns_none(tmp_path):
    def mock_read_remote(host, path):
        return None

    result = bf.produced("2026-10-24", str(tmp_path / "missing.md"), "remote-host", read_remote_fn=mock_read_remote)
    assert result is False


# Test 15: should_build returns (False, "owner") when not standby
def test_should_build_not_owner():
    with patch.object(bf, "is_owner", return_value=False):
        should_build, reason = bf.should_build("2026-10-24", "/path/to/brief.md")
        assert should_build is False
        assert reason == "owner"


# Test 16: should_build returns (True, reason) when primary missing/unreachable
def test_should_build_primary_missing():
    with patch.object(bf, "is_owner", return_value=True):
        with patch.object(bf.scanner_role, "_primary_device", return_value=(None, None)):
            should_build, reason = bf.should_build("2026-10-24", "/path/to/brief.md")
            assert should_build is True
            assert reason == "no-primary-registered"


# Test 17: should_build returns (True, reason) when primary unreachable
def test_should_build_primary_unreachable():
    with patch.object(bf, "is_owner", return_value=True):
        with patch.object(bf.scanner_role, "_primary_device", return_value=("dev", {"tailscale_hostname": None})):
            should_build, reason = bf.should_build("2026-10-24", "/path/to/brief.md")
            assert should_build is True
            assert reason == "primary-unreachable"


# Test 18: should_build respects produced() check on primary
def test_should_build_primary_produced():
    with patch.object(bf, "is_owner", return_value=True):
        with patch.object(bf, "produced", return_value=True):
            with patch.object(bf.scanner_role, "_primary_device", return_value=("dev", {"tailscale_hostname": "remote-host"})):
                should_build, reason = bf.should_build("2026-10-24", "/path/to/brief.md")
                assert should_build is False
                assert reason == "primary-produced"
