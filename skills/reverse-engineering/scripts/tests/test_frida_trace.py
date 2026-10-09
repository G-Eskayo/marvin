"""Tests for frida_trace.py wrapper.

Run via:
    ~/.agents/venv/bin/python -m pytest skills/reverse-engineering/scripts/tests/test_frida_trace.py -v
"""
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Add scripts directory to path
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import frida_trace


# ── Authorization Gate ────────────────────────────────────────────────────────

def test_frida_refuses_without_authorization(tmp_path, monkeypatch, capsys):
    """Test that frida_trace refuses without --authorized flag."""
    monkeypatch.delenv("MARVIN_RE_AUTHORIZED", raising=False)

    sys.argv = ["frida_trace.py", "--target-process", "firefox", "--function-name", "malloc"]
    with pytest.raises(SystemExit) as exc_info:
        frida_trace.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Authorization" in captured.err or "Authorization" in captured.out


def test_frida_runs_with_authorization(tmp_path, monkeypatch):
    """Test that frida_trace runs with --authorized flag."""
    # Create a fake frida
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_frida = bin_dir / "frida"
    fake_frida.write_text("#!/bin/sh\necho 'malloc called with size: 1024'\nexit 0\n")
    fake_frida.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    sys.argv = [
        "frida_trace.py",
        "--target-process", "firefox",
        "--function-name", "malloc",
        "--authorized",
    ]
    try:
        frida_trace.main()
    except SystemExit as e:
        if e.code != 0 and e.code is not None:
            pytest.fail(f"Expected exit code 0, got {e.code}")


def test_frida_runs_with_env_authorization(tmp_path, monkeypatch):
    """Test that MARVIN_RE_AUTHORIZED=1 satisfies frida authorization."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_frida = bin_dir / "frida"
    fake_frida.write_text("#!/bin/sh\necho 'OK'\nexit 0\n")
    fake_frida.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "frida_trace.py",
        "--target-process", "firefox",
        "--function-name", "malloc",
    ]
    try:
        frida_trace.main()
    except SystemExit as e:
        if e.code != 0 and e.code is not None:
            pytest.fail(f"Expected exit code 0, got {e.code}")


# ── Tool Availability ─────────────────────────────────────────────────────────

def test_frida_fails_when_tool_missing(tmp_path, monkeypatch, capsys):
    """Test that frida_trace fails with clear hint when frida is missing."""
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "frida_trace.py",
        "--target-process", "firefox",
        "--function-name", "malloc",
        "--authorized",
    ]
    with pytest.raises(SystemExit) as exc_info:
        frida_trace.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()
    assert "frida" in captured.err.lower()


# ── Binary Path Validation (for --spawn) ──────────────────────────────────────

def test_frida_spawn_validates_binary_path(tmp_path, monkeypatch, capsys):
    """Test that --spawn mode validates the binary path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_frida = bin_dir / "frida"
    fake_frida.write_text("#!/bin/sh\necho 'OK'\nexit 0\n")
    fake_frida.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    # Non-existent file with --spawn
    sys.argv = [
        "frida_trace.py",
        "--target-process", "/nonexistent/binary",
        "--function-name", "malloc",
        "--authorized",
        "--spawn",
    ]
    with pytest.raises(SystemExit) as exc_info:
        frida_trace.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "does not exist" in captured.err.lower()


def test_frida_spawn_rejects_directory(tmp_path, monkeypatch, capsys):
    """Test that --spawn mode rejects directory as binary."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_frida = bin_dir / "frida"
    fake_frida.write_text("#!/bin/sh\necho 'OK'\nexit 0\n")
    fake_frida.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    # Directory with --spawn
    sys.argv = [
        "frida_trace.py",
        "--target-process", str(tmp_path),
        "--function-name", "malloc",
        "--authorized",
        "--spawn",
    ]
    with pytest.raises(SystemExit) as exc_info:
        frida_trace.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "not a regular file" in captured.err.lower() or "directory" in captured.err.lower()


def test_frida_spawn_with_valid_binary(tmp_path, monkeypatch):
    """Test that frida can spawn with a valid binary path."""
    binary = tmp_path / "test_app"
    binary.write_text("dummy app")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_frida = bin_dir / "frida"
    fake_frida.write_text("#!/bin/sh\necho 'Spawned and tracing'\nexit 0\n")
    fake_frida.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "frida_trace.py",
        "--target-process", str(binary),
        "--function-name", "malloc",
        "--authorized",
        "--spawn",
    ]
    try:
        frida_trace.main()
    except SystemExit as e:
        if e.code != 0 and e.code is not None:
            pytest.fail(f"Expected exit code 0, got {e.code}")


# ── Process Not Found (dynamic attach) ────────────────────────────────────────

def test_frida_attach_process_not_found(tmp_path, monkeypatch, capsys):
    """Test that frida handles process not found when attaching."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_frida = bin_dir / "frida"
    # Simulate process not found error
    fake_frida.write_text("#!/bin/sh\necho 'Process not found' >&2\nexit 1\n")
    fake_frida.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "frida_trace.py",
        "--target-process", "nonexistent_process",
        "--function-name", "malloc",
        "--authorized",
    ]
    with pytest.raises(SystemExit) as exc_info:
        frida_trace.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err.lower() or "running" in captured.err.lower()


# ── Timeout ───────────────────────────────────────────────────────────────────

def test_frida_respects_timeout(tmp_path, monkeypatch, capsys):
    """Test that frida trace respects the timeout setting."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_frida = bin_dir / "frida"
    fake_frida.write_text("#!/bin/sh\nsleep 10\nexit 0\n")
    fake_frida.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "frida_trace.py",
        "--target-process", "firefox",
        "--function-name", "malloc",
        "--authorized",
        "--timeout", "1",
    ]
    with pytest.raises(SystemExit) as exc_info:
        frida_trace.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "timed out" in captured.err.lower() or "timeout" in captured.err.lower()


# ── Argument Requirements ─────────────────────────────────────────────────────

def test_frida_requires_target_process(capsys):
    """Test that frida requires --target-process argument."""
    sys.argv = [
        "frida_trace.py",
        "--function-name", "malloc",
        "--authorized",
    ]
    with pytest.raises(SystemExit):
        frida_trace.main()

    captured = capsys.readouterr()
    # Should show usage error
    assert "target-process" in captured.err.lower() or "required" in captured.err.lower()


def test_frida_requires_function_name(capsys):
    """Test that frida requires --function-name argument."""
    sys.argv = [
        "frida_trace.py",
        "--target-process", "firefox",
        "--authorized",
    ]
    with pytest.raises(SystemExit):
        frida_trace.main()

    captured = capsys.readouterr()
    # Should show usage error
    assert "function-name" in captured.err.lower() or "required" in captured.err.lower()


# ── Spawn vs Attach ───────────────────────────────────────────────────────────

def test_frida_spawn_flag(tmp_path, monkeypatch):
    """Test that --spawn flag is recognized."""
    binary = tmp_path / "app"
    binary.write_text("dummy")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_frida = bin_dir / "frida"
    fake_frida.write_text("#!/bin/sh\necho 'OK'\nexit 0\n")
    fake_frida.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "frida_trace.py",
        "--target-process", str(binary),
        "--function-name", "main",
        "--authorized",
        "--spawn",
    ]
    try:
        frida_trace.main()
    except SystemExit as e:
        if e.code != 0 and e.code is not None:
            pytest.fail(f"Expected exit code 0, got {e.code}")
