"""Tests for ghidra_headless.py wrapper.

Run via:
    ~/.agents/venv/bin/python -m pytest skills/reverse-engineering/scripts/tests/test_ghidra_headless.py -v
"""
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Add scripts directory to path
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import ghidra_headless


# ── Authorization Gate ────────────────────────────────────────────────────────

def test_ghidra_refuses_without_authorization(tmp_path, monkeypatch, capsys):
    """Test that ghidra_headless refuses without --authorized flag."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy")

    monkeypatch.delenv("MARVIN_RE_AUTHORIZED", raising=False)

    sys.argv = ["ghidra_headless.py", "--binary", str(binary)]
    with pytest.raises(SystemExit) as exc_info:
        ghidra_headless.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Authorization" in captured.err or "Authorization" in captured.out


def test_ghidra_runs_with_authorization(tmp_path, monkeypatch):
    """Test that ghidra_headless runs with --authorized flag."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy binary")

    # Create a fake analyzeHeadless
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_ghidra = bin_dir / "analyzeHeadless"
    fake_ghidra.write_text("#!/bin/sh\necho 'Analysis complete'\nexit 0\n")
    fake_ghidra.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    sys.argv = ["ghidra_headless.py", "--binary", str(binary), "--authorized"]
    try:
        ghidra_headless.main()
    except SystemExit as e:
        if e.code != 0 and e.code is not None:
            pytest.fail(f"Expected exit code 0, got {e.code}")


# ── Tool Availability ─────────────────────────────────────────────────────────

def test_ghidra_fails_when_tool_missing(tmp_path, monkeypatch, capsys):
    """Test that ghidra_headless fails with clear hint when analyzeHeadless is missing."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy")

    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["ghidra_headless.py", "--binary", str(binary), "--authorized"]
    with pytest.raises(SystemExit) as exc_info:
        ghidra_headless.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()
    assert "ghidra" in captured.err.lower()


# ── Binary Path Validation ────────────────────────────────────────────────────

def test_ghidra_rejects_nonexistent_binary(tmp_path, monkeypatch, capsys):
    """Test that ghidra_headless rejects non-existent binary."""
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["ghidra_headless.py", "--binary", "/nonexistent/binary", "--authorized"]
    with pytest.raises(SystemExit) as exc_info:
        ghidra_headless.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "does not exist" in captured.err.lower()


def test_ghidra_rejects_directory(tmp_path, monkeypatch, capsys):
    """Test that ghidra_headless rejects directory as binary."""
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["ghidra_headless.py", "--binary", str(tmp_path), "--authorized"]
    with pytest.raises(SystemExit) as exc_info:
        ghidra_headless.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "not a regular file" in captured.err.lower() or "directory" in captured.err.lower()


def test_ghidra_rejects_unreadable_file(tmp_path, monkeypatch, capsys):
    """Test that ghidra_headless rejects file without read permissions."""
    binary = tmp_path / "unreadable.bin"
    binary.write_text("content")
    binary.chmod(0o000)

    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    try:
        sys.argv = ["ghidra_headless.py", "--binary", str(binary), "--authorized"]
        with pytest.raises(SystemExit) as exc_info:
            ghidra_headless.main()
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "permission" in captured.err.lower() or "not readable" in captured.err.lower()
    finally:
        binary.chmod(0o644)


# ── Ghidra Project Directory Reuse ────────────────────────────────────────────

def test_ghidra_reuses_project_on_second_run(tmp_path, monkeypatch):
    """Test that running ghidra twice against same binary doesn't crash on 'project exists'."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy binary")

    # Create a fake analyzeHeadless
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_ghidra = bin_dir / "analyzeHeadless"
    fake_ghidra.write_text("#!/bin/sh\necho 'Analysis complete'\nexit 0\n")
    fake_ghidra.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    # First run
    sys.argv = ["ghidra_headless.py", "--binary", str(binary), "--authorized"]
    try:
        ghidra_headless.main()
    except SystemExit:
        pass

    # Second run (should succeed, not crash on "project exists")
    sys.argv = ["ghidra_headless.py", "--binary", str(binary), "--authorized"]
    try:
        ghidra_headless.main()
    except SystemExit as e:
        if e.code != 0 and e.code is not None:
            pytest.fail(f"Second run failed: {e.code}")


# ── Function-Specific Decompilation ───────────────────────────────────────────

def test_ghidra_accepts_function_name(tmp_path, monkeypatch):
    """Test that ghidra_headless accepts --function-name argument."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy binary")

    # Create a fake analyzeHeadless
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_ghidra = bin_dir / "analyzeHeadless"
    fake_ghidra.write_text("#!/bin/sh\necho 'Decompiled main'\nexit 0\n")
    fake_ghidra.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "ghidra_headless.py",
        "--binary", str(binary),
        "--authorized",
        "--function-name", "main",
    ]
    try:
        ghidra_headless.main()
    except SystemExit as e:
        if e.code != 0 and e.code is not None:
            pytest.fail(f"Expected exit code 0, got {e.code}")


# ── Output Formats ───────────────────────────────────────────────────────────

def test_ghidra_json_output(tmp_path, monkeypatch):
    """Test that ghidra_headless can output JSON."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy binary")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_ghidra = bin_dir / "analyzeHeadless"
    fake_ghidra.write_text("#!/bin/sh\necho 'OK'\nexit 0\n")
    fake_ghidra.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "ghidra_headless.py",
        "--binary", str(binary),
        "--authorized",
        "--output-format", "json",
    ]
    try:
        ghidra_headless.main()
    except SystemExit as e:
        if e.code != 0 and e.code is not None:
            pytest.fail(f"Expected exit code 0, got {e.code}")


# ── Tool Failure Handling ─────────────────────────────────────────────────────

def test_ghidra_handles_tool_nonzero_exit(tmp_path, monkeypatch, capsys):
    """Test that ghidra_headless handles tool returning non-zero exit."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy binary")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_ghidra = bin_dir / "analyzeHeadless"
    fake_ghidra.write_text("#!/bin/sh\necho 'Error: invalid binary format'\nexit 1\n")
    fake_ghidra.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["ghidra_headless.py", "--binary", str(binary), "--authorized"]
    with pytest.raises(SystemExit) as exc_info:
        ghidra_headless.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "failed" in captured.err.lower() or "error" in captured.err.lower()
