"""Shared utilities for reverse-engineering tool wrappers."""
import sys
import os
import shutil
import subprocess
from pathlib import Path


def check_authorization():
    """
    Check if the user has authorized this operation.
    Raises RuntimeError if authorization is not present.
    """
    if os.environ.get("MARVIN_RE_AUTHORIZED") == "1":
        return True
    # If passed via CLI, the caller should check sys.argv before calling this
    raise RuntimeError(
        "Authorization required. This tool analyzes binaries. You must confirm authorization by:\n"
        "  1. Passing --authorized flag to the script, or\n"
        "  2. Setting MARVIN_RE_AUTHORIZED=1 before running\n"
        "This requirement exists because reverse-engineering tools are dual-use:\n"
        "they must only be used for authorized security testing, CTF, or defensive analysis."
    )


def check_tool_available(tool_name):
    """
    Check if a tool is available on PATH.
    Returns the full path if found, otherwise returns None.
    """
    return shutil.which(tool_name)


def validate_binary_path(binary_path, max_size_mb=500):
    """
    Validate that the binary path is:
    - A valid path (string or Path)
    - Points to an existing file (not a directory)
    - Is readable
    - Does not exceed max_size_mb

    Raises ValueError with a clear message if validation fails.
    """
    try:
        path = Path(binary_path)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid path: {binary_path}: {e}")

    if not path.exists():
        raise ValueError(f"Path does not exist: {binary_path}")

    if not path.is_file():
        raise ValueError(f"Path is not a regular file (is it a directory?): {binary_path}")

    if not os.access(path, os.R_OK):
        raise ValueError(f"File is not readable (permission denied): {binary_path}")

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        raise ValueError(
            f"File exceeds size limit ({size_mb:.1f}MB > {max_size_mb}MB): {binary_path}"
        )


def run_subprocess(cmd, timeout=60):
    """
    Run a subprocess safely with timeout and error handling.

    Args:
        cmd: List of command and arguments (for subprocess.run)
        timeout: Maximum seconds to wait (default 60)

    Returns:
        CompletedProcess with stdout/stderr captured

    Raises:
        subprocess.TimeoutExpired: If the process exceeds timeout
        subprocess.CalledProcessError: If the process exits non-zero
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"Tool execution timed out after {timeout}s. Command: {' '.join(cmd)}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Failed to run tool: {e}") from e


def install_hint(tool_name):
    """Return a helpful installation hint for a tool."""
    hints = {
        "r2": "Install radare2: brew install radare2",
        "rizin": "Install rizin: brew install rizin",
        "analyzeHeadless": "Install Ghidra from https://github.com/NationalSecurityAgency/ghidra and ensure analyzeHeadless is on PATH",
        "frida": "Install Frida: brew install frida or pip install frida-tools",
    }
    return hints.get(tool_name, f"Install {tool_name} and ensure it is on PATH")
