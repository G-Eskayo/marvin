"""Tests for reverse-engineering tool wrappers.

Run via:
    ~/.agents/venv/bin/python -m pytest skills/reverse-engineering/scripts/tests/test_re_common.py -v
"""
import os
import sys
import json
import stat
import shutil
import tempfile
import subprocess
from pathlib import Path
from unittest import mock

import pytest

# Add scripts directory to path
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import re_common


# ── Authorization Gate ────────────────────────────────────────────────────────

def test_authorization_required():
    """Test that authorization check raises without env var or flag."""
    # Clear the env var
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError) as exc_info:
            re_common.check_authorization()
        assert "Authorization required" in str(exc_info.value)
        assert "--authorized" in str(exc_info.value)


def test_authorization_via_env():
    """Test that MARVIN_RE_AUTHORIZED=1 satisfies authorization."""
    with mock.patch.dict(os.environ, {"MARVIN_RE_AUTHORIZED": "1"}):
        # Should not raise
        re_common.check_authorization()


def test_authorization_via_env_false_value():
    """Test that MARVIN_RE_AUTHORIZED with wrong value doesn't authorize."""
    with mock.patch.dict(os.environ, {"MARVIN_RE_AUTHORIZED": "0"}):
        with pytest.raises(RuntimeError):
            re_common.check_authorization()


# ── Tool Availability ─────────────────────────────────────────────────────────

def test_tool_available_found():
    """Test that check_tool_available returns path when tool exists."""
    # Test with a real tool that should exist
    result = re_common.check_tool_available("python3")
    assert result is not None
    assert Path(result).exists()


def test_tool_available_missing():
    """Test that check_tool_available returns None for missing tool."""
    result = re_common.check_tool_available("nonexistent_tool_xyz")
    assert result is None


# ── Binary Path Validation ────────────────────────────────────────────────────

def test_validate_binary_path_valid(tmp_path):
    """Test validation passes for a valid binary."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy binary content")
    # Should not raise
    re_common.validate_binary_path(str(binary))


def test_validate_binary_path_nonexistent():
    """Test validation fails for non-existent file."""
    with pytest.raises(ValueError) as exc_info:
        re_common.validate_binary_path("/nonexistent/path/to/binary")
    assert "does not exist" in str(exc_info.value)


def test_validate_binary_path_directory(tmp_path):
    """Test validation fails when path is a directory, not a file."""
    with pytest.raises(ValueError) as exc_info:
        re_common.validate_binary_path(str(tmp_path))
    assert "not a regular file" in str(exc_info.value).lower()
    assert "directory" in str(exc_info.value).lower()


def test_validate_binary_path_empty_file(tmp_path):
    """Test validation passes for empty file (0 bytes)."""
    empty = tmp_path / "empty.bin"
    empty.write_text("")
    # Should not raise (size=0 is still valid)
    re_common.validate_binary_path(str(empty))


def test_validate_binary_path_too_large(tmp_path):
    """Test validation fails when file exceeds size limit."""
    large = tmp_path / "large.bin"
    # Write 600MB worth of data (exceeds default 500MB limit)
    # For testing, we'll write a smaller file and use a small limit
    large.write_text("x" * 100)
    with pytest.raises(ValueError) as exc_info:
        re_common.validate_binary_path(str(large), max_size_mb=0.00001)
    assert "exceeds size limit" in str(exc_info.value)


def test_validate_binary_path_not_readable(tmp_path):
    """Test validation fails when file is not readable."""
    binary = tmp_path / "unreadable.bin"
    binary.write_text("content")
    # Remove read permissions
    binary.chmod(0o000)
    try:
        with pytest.raises(ValueError) as exc_info:
            re_common.validate_binary_path(str(binary))
        assert "not readable" in str(exc_info.value).lower()
    finally:
        # Restore permissions for cleanup
        binary.chmod(0o644)


def test_validate_binary_path_invalid_type():
    """Test validation fails for invalid path type."""
    with pytest.raises(ValueError):
        re_common.validate_binary_path(None)


# ── Subprocess Execution ──────────────────────────────────────────────────────

def test_run_subprocess_success(tmp_path):
    """Test successful subprocess execution."""
    result = re_common.run_subprocess(["echo", "hello"])
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_run_subprocess_timeout():
    """Test that subprocess timeout is enforced."""
    with pytest.raises(RuntimeError) as exc_info:
        re_common.run_subprocess(["sleep", "10"], timeout=0.1)
    assert "timed out" in str(exc_info.value).lower()


def test_run_subprocess_nonzero_exit():
    """Test that non-zero exit from subprocess is captured."""
    result = re_common.run_subprocess(["sh", "-c", "exit 42"])
    assert result.returncode == 42


# ── Install Hints ─────────────────────────────────────────────────────────────

def test_install_hint_radare2():
    """Test install hint for radare2."""
    hint = re_common.install_hint("r2")
    assert "radare2" in hint.lower()
    assert "brew" in hint.lower()


def test_install_hint_ghidra():
    """Test install hint for Ghidra."""
    hint = re_common.install_hint("analyzeHeadless")
    assert "ghidra" in hint.lower()


def test_install_hint_frida():
    """Test install hint for Frida."""
    hint = re_common.install_hint("frida")
    assert "frida" in hint.lower()


def test_install_hint_unknown():
    """Test install hint for unknown tool."""
    hint = re_common.install_hint("unknown_tool")
    assert "unknown_tool" in hint


# ── SKILL.md Authorization Content ────────────────────────────────────────────

def test_skill_md_contains_authorization_section():
    """Test that SKILL.md explicitly documents authorization requirement."""
    skill_path = Path(__file__).resolve().parents[2] / "SKILL.md"
    assert skill_path.exists(), f"SKILL.md not found at {skill_path}"

    content = skill_path.read_text()
    assert "Authorization" in content, "SKILL.md missing Authorization section"
    assert "--authorized" in content, "SKILL.md doesn't mention --authorized flag"
    assert "MARVIN_RE_AUTHORIZED" in content, "SKILL.md doesn't mention env var"
    assert "dual-use" in content.lower(), "SKILL.md doesn't mention dual-use nature"


def test_skill_md_names_all_three_tools():
    """Test that SKILL.md explicitly names radare2, Ghidra, and Frida."""
    skill_path = Path(__file__).resolve().parents[2] / "SKILL.md"
    content = skill_path.read_text()

    # Check for tool names (case-insensitive for some, case-sensitive for others)
    assert "Radare2" in content or "radare2" in content, "SKILL.md missing Radare2"
    assert "Ghidra" in content, "SKILL.md missing Ghidra"
    assert "Frida" in content, "SKILL.md missing Frida"


# ── Shell Injection Prevention ────────────────────────────────────────────────

@pytest.fixture
def fake_tool_on_path(tmp_path, monkeypatch):
    """Create a fake tool binary on PATH that echoes its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    fake_tool = bin_dir / "fake_analyzer"
    # Script that echoes arguments it received (one per line)
    script_content = """#!/bin/sh
for arg in "$@"; do
    echo "ARG: $arg"
done
exit 0
"""
    fake_tool.write_text(script_content)
    fake_tool.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return fake_tool


def test_subprocess_uses_list_not_shell(tmp_path, monkeypatch):
    """Test that subprocess calls use list form (no shell injection)."""
    # Create a test that verifies argv escaping
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Create a tool that will receive dangerous-looking arguments
    fake_tool = bin_dir / "fake_tool"
    fake_tool.write_text("""#!/bin/sh
# Output each argument on a separate line
for arg in "$@"; do
    echo "ARGV: $arg"
done
""")
    fake_tool.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    # Test that dangerous characters are passed literally, not interpreted
    dangerous_arg = "; echo INJECTED"
    result = re_common.run_subprocess([str(fake_tool), dangerous_arg])

    # Verify the argument was passed literally, not executed
    assert "ARGV: ; echo INJECTED" in result.stdout
    assert "INJECTED" not in result.stdout.replace("ARGV: ; echo INJECTED", "")
