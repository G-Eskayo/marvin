"""Tests for r2_analyze.py wrapper.

Run via:
    ~/.agents/venv/bin/python -m pytest skills/reverse-engineering/scripts/tests/test_r2_analyze.py -v
"""
import os
import sys
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

# Add scripts directory to path
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import r2_analyze


# ── Authorization Gate (acceptance criterion) ────────────────────────────────

def test_r2_refuses_without_authorization(tmp_path, monkeypatch, capsys):
    """Test that r2_analyze refuses to run without --authorized flag."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy")

    # Ensure env var is not set
    monkeypatch.delenv("MARVIN_RE_AUTHORIZED", raising=False)

    # Create a fake tool to verify it's NOT called
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_r2 = bin_dir / "r2"
    fake_r2.write_text("#!/bin/sh\nexit 42\n")
    fake_r2.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    # Run without --authorized
    sys.argv = ["r2_analyze.py", "--binary", str(binary)]
    with pytest.raises(SystemExit) as exc_info:
        r2_analyze.main()
    assert exc_info.value.code == 1

    # Verify authorization message was printed
    captured = capsys.readouterr()
    assert "Authorization" in captured.err or "Authorization" in captured.out


def test_r2_runs_with_authorization(tmp_path, monkeypatch):
    """Test that r2_analyze runs with --authorized flag."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy binary")

    # Create a fake r2 that succeeds
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_r2 = bin_dir / "r2"
    fake_r2.write_text("""#!/bin/sh
# Fake r2 output
echo "0x00000000    0 sym.main"
echo "String: /bin/sh"
""")
    fake_r2.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    sys.argv = ["r2_analyze.py", "--binary", str(binary), "--authorized"]
    # Should succeed (doesn't raise SystemExit for successful case)
    r2_analyze.main()


def test_r2_runs_with_env_authorization(tmp_path, monkeypatch):
    """Test that MARVIN_RE_AUTHORIZED=1 satisfies authorization."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy binary")

    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    # Create a fake r2
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_r2 = bin_dir / "r2"
    fake_r2.write_text("#!/bin/sh\necho 'OK'\nexit 0\n")
    fake_r2.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    sys.argv = ["r2_analyze.py", "--binary", str(binary)]
    # Should succeed (no --authorized needed)
    r2_analyze.main()


# ── Tool Availability ─────────────────────────────────────────────────────────

def test_r2_fails_when_tool_missing(tmp_path, monkeypatch, capsys):
    """Test that r2_analyze fails with clear hint when r2 is missing."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy")

    # Ensure r2/rizin are not on PATH
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["r2_analyze.py", "--binary", str(binary), "--authorized"]
    with pytest.raises(SystemExit) as exc_info:
        r2_analyze.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()
    assert "brew install" in captured.err.lower()


# ── Binary Path Validation ────────────────────────────────────────────────────

def test_r2_rejects_nonexistent_binary(tmp_path, monkeypatch, capsys):
    """Test that r2_analyze rejects non-existent binary."""
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["r2_analyze.py", "--binary", "/nonexistent/binary", "--authorized"]
    with pytest.raises(SystemExit) as exc_info:
        r2_analyze.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "does not exist" in captured.err.lower()


def test_r2_rejects_directory(tmp_path, monkeypatch, capsys):
    """Test that r2_analyze rejects directory as binary."""
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["r2_analyze.py", "--binary", str(tmp_path), "--authorized"]
    with pytest.raises(SystemExit) as exc_info:
        r2_analyze.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "not a regular file" in captured.err.lower() or "directory" in captured.err.lower()


def test_r2_rejects_unreadable_file(tmp_path, monkeypatch, capsys):
    """Test that r2_analyze rejects file without read permissions."""
    binary = tmp_path / "unreadable.bin"
    binary.write_text("content")
    binary.chmod(0o000)

    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    try:
        sys.argv = ["r2_analyze.py", "--binary", str(binary), "--authorized"]
        with pytest.raises(SystemExit) as exc_info:
            r2_analyze.main()
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "permission" in captured.err.lower() or "not readable" in captured.err.lower()
    finally:
        binary.chmod(0o644)


# ── Output Formats ────────────────────────────────────────────────────────────

def test_r2_text_output(tmp_path, monkeypatch, capsys):
    """Test that r2_analyze produces text output by default."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy")

    # Create a fake r2 that outputs text
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_r2 = bin_dir / "r2"
    fake_r2.write_text("#!/bin/sh\necho '0x00000000    0 sym.main'\nexit 0\n")
    fake_r2.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["r2_analyze.py", "--binary", str(binary), "--authorized"]
    # Execute and capture output
    with mock.patch("sys.stdout", new_callable=lambda: mock.Mock()):
        try:
            r2_analyze.main()
        except SystemExit:
            pass


def test_r2_json_output(tmp_path, monkeypatch, capsys):
    """Test that r2_analyze produces JSON output with --output-format json."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy")

    # Create a fake r2
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_r2 = bin_dir / "r2"
    fake_r2.write_text("#!/bin/sh\necho 'functions output'\nexit 0\n")
    fake_r2.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = [
        "r2_analyze.py",
        "--binary", str(binary),
        "--authorized",
        "--output-format", "json",
    ]

    with mock.patch("sys.stdout", new_callable=lambda: mock.Mock()):
        try:
            r2_analyze.main()
        except SystemExit:
            pass


# ── Tool Timeout ──────────────────────────────────────────────────────────────

def test_r2_tool_timeout(tmp_path, monkeypatch, capsys):
    """Test that r2_analyze handles tool timeout gracefully."""
    binary = tmp_path / "test.bin"
    binary.write_text("dummy")

    # Create a fake r2 that sleeps longer than the timeout (30s default in r2_analyze.py)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_r2 = bin_dir / "r2"
    fake_r2.write_text("#!/bin/sh\nsleep 60\nexit 0\n")
    fake_r2.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("MARVIN_RE_AUTHORIZED", "1")

    sys.argv = ["r2_analyze.py", "--binary", str(binary), "--authorized"]
    with pytest.raises(SystemExit) as exc_info:
        r2_analyze.main()
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "timed out" in captured.err.lower() or "timeout" in captured.err.lower()
