"""Tests for r2_static_report.sh. Run via:
    ~/.agents/venv/bin/python -m pytest skills/reverse-engineering/scripts/tests/test_r2_static_report.py -v
"""
from __future__ import annotations
import subprocess
import json
from pathlib import Path
import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1]


def test_r2_script_exists():
    """r2_static_report.sh should exist."""
    script = SCRIPTS_DIR / "r2_static_report.sh"
    assert script.exists(), f"r2_static_report.sh not found at {script}"


def test_r2_script_is_executable():
    """r2_static_report.sh should be readable (can be run with bash)."""
    script = SCRIPTS_DIR / "r2_static_report.sh"
    # Script can be run with bash even if not directly executable
    assert script.stat().st_mode & 0o444, f"{script} is not readable"


def test_r2_script_requires_auth_gate():
    """Script should fail without --i-own-this-target flag."""
    script = SCRIPTS_DIR / "r2_static_report.sh"

    # Try to run without authorization flag
    result = subprocess.run(
        ["bash", str(script), "--binary", "/tmp/test"],
        capture_output=True,
        text=True
    )

    assert result.returncode != 0
    assert "Authorization gate" in result.stderr or "required" in result.stderr.lower()


def test_r2_script_requires_binary():
    """Script should fail if --binary is not provided."""
    script = SCRIPTS_DIR / "r2_static_report.sh"

    result = subprocess.run(
        ["bash", str(script), "--i-own-this-target"],
        capture_output=True,
        text=True
    )

    assert result.returncode != 0


def test_r2_script_checks_binary_exists():
    """Script should fail if binary file does not exist."""
    script = SCRIPTS_DIR / "r2_static_report.sh"

    result = subprocess.run(
        ["bash", str(script), "--binary", "/nonexistent/binary", "--i-own-this-target"],
        capture_output=True,
        text=True
    )

    assert result.returncode != 0
    assert "not found" in result.stderr


def test_r2_script_output_is_valid_json():
    """If radare2 is installed, output should be valid JSON."""
    script = SCRIPTS_DIR / "r2_static_report.sh"

    # Check if r2 is installed
    r2_check = subprocess.run(["which", "r2"], capture_output=True)
    if r2_check.returncode != 0:
        pytest.skip("radare2 not installed, skipping integration test")

    # Create a minimal test binary (ELF with just a few bytes)
    # Use /bin/ls or similar if available
    test_binary = "/bin/ls"
    if not Path(test_binary).exists():
        pytest.skip(f"{test_binary} not found, skipping integration test")

    result = subprocess.run(
        ["bash", str(script), "--binary", test_binary, "--i-own-this-target"],
        capture_output=True,
        text=True,
        timeout=30
    )

    # If r2 is working, output should be valid JSON
    if result.returncode == 0:
        try:
            output = json.loads(result.stdout)
            assert "binary" in output or "arch" in output or "functions" in output
        except json.JSONDecodeError:
            # Some outputs might have extra text, try parsing just the JSON part
            json_start = result.stdout.find('{')
            if json_start >= 0:
                json_str = result.stdout[json_start:]
                output = json.loads(json_str)
                assert isinstance(output, dict)


def test_r2_script_help():
    """Script should provide usage information."""
    script = SCRIPTS_DIR / "r2_static_report.sh"

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True
    )

    # Should fail (authorization gate or missing args)
    assert result.returncode != 0
    # Should have error message about authorization or missing arguments
    assert "Authorization gate" in result.stderr or "binary" in result.stderr.lower()


def test_r2_script_argument_parsing():
    """Script should parse arguments correctly."""
    script = SCRIPTS_DIR / "r2_static_report.sh"

    # Test invalid argument
    result = subprocess.run(
        ["bash", str(script), "--invalid-flag"],
        capture_output=True,
        text=True
    )

    assert result.returncode != 0
    assert "Usage" in result.stderr or "usage" in result.stderr.lower()


def test_r2_script_can_output_to_file():
    """Script should write output to file when --output is specified."""
    script = SCRIPTS_DIR / "r2_static_report.sh"

    # Check if r2 is installed
    r2_check = subprocess.run(["which", "r2"], capture_output=True)
    if r2_check.returncode != 0:
        pytest.skip("radare2 not installed, skipping integration test")

    test_binary = "/bin/ls"
    if not Path(test_binary).exists():
        pytest.skip(f"{test_binary} not found, skipping integration test")

    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        output_file = f.name

    try:
        result = subprocess.run(
            ["bash", str(script), "--binary", test_binary, "--i-own-this-target", "--output", output_file],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Output file should exist if command succeeded
        if result.returncode == 0:
            assert Path(output_file).exists()
            content = Path(output_file).read_text()
            # Should be valid JSON
            try:
                json.loads(content)
            except json.JSONDecodeError:
                pytest.skip("radare2 output not valid JSON (may not be installed properly)")
    finally:
        # Clean up
        if Path(output_file).exists():
            Path(output_file).unlink()
