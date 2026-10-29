"""opencode_runner.py — thin wrapper mirroring bench.py's ollama patterns.

Executes tasks via opencode CLI against a local Ollama endpoint.
Returns result dict on success, never raises. Mirrors run_once_ollama's contract.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def opencode_available() -> tuple[bool, str]:
    """Return (ok, error_message). Checks if opencode CLI is available."""
    if shutil.which("opencode") is None:
        return False, "opencode CLI not found. Install: npm install -g @sst/opencode"
    return True, ""


def run_once_opencode(
    task: dict,
    workdir: str | Path,
    ollama_model: str,
    timeout: int,
) -> dict | None:
    """Run a task via opencode CLI against Ollama endpoint.

    Args:
        task: dict with "id", "prompt", "type", etc. (same as bench.py's format)
        workdir: directory to run in (code generation target)
        ollama_model: model name (e.g. "qwen2.5:7b")
        timeout: seconds to allow before killing the process

    Returns:
        dict with keys: spawn_error, result_text, returncode, wall_s, total_tokens
        OR None for fs tasks (tool use not supported).
        Never raises.
    """
    # opencode doesn't support tool use, so skip fs tasks
    if task.get("type") == "fs":
        return None

    workdir = Path(workdir)
    prompt = task.get("prompt", "")

    # opencode run --model provider/model "<prompt>" in workdir
    # Ollama models are available as ollama/model-name on a local endpoint
    # Default Ollama listens on localhost:11434
    env = dict(os.environ)
    env["OLLAMA_BASE_URL"] = "http://localhost:11434"

    cmd = [
        "opencode",
        "run",
        "-m", f"ollama/{ollama_model}",
        prompt,
    ]

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        wall = time.time() - t0

        # Try to parse output for token count (opencode may include this)
        total_tokens = 0
        try:
            if proc.stdout:
                # Look for token count in output (varies by implementation)
                for line in proc.stdout.split("\n"):
                    if "tokens" in line.lower():
                        parts = line.split()
                        for part in parts:
                            if part.isdigit():
                                total_tokens = int(part)
                                break
        except Exception:
            pass

        return {
            "profile": "opencode",
            "model": ollama_model,
            "runner": "opencode",
            "result_text": proc.stdout or "",
            "stderr": proc.stderr or "",
            "returncode": proc.returncode,
            "spawn_error": None if proc.returncode == 0 else f"exit code {proc.returncode}",
            "wall_s": round(wall, 1),
            "total_tokens": total_tokens,
        }
    except subprocess.TimeoutExpired:
        wall = time.time() - t0
        return {
            "profile": "opencode",
            "model": ollama_model,
            "runner": "opencode",
            "result_text": "",
            "spawn_error": f"timeout after {timeout}s",
            "returncode": -1,
            "wall_s": round(wall, 1),
            "total_tokens": 0,
        }
    except Exception as exc:
        wall = time.time() - t0
        return {
            "profile": "opencode",
            "model": ollama_model,
            "runner": "opencode",
            "result_text": "",
            "spawn_error": str(exc),
            "returncode": -1,
            "wall_s": round(wall, 1),
            "total_tokens": 0,
        }
