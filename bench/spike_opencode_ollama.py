#!/usr/bin/env python3
"""Run the opencode+Ollama spike.

For each selected task:
1. Create a git worktree at the task's base commit
2. Start ollama_usage_proxy and energy_apple samplers
3. Run opencode against the task
4. Stop samplers and measure usage/energy
5. Run project_profile.verify_dir on the worktree for gate pass/fail
6. Clean up the worktree

Results are recorded as JSON per task and summarized to bench/results/.

Usage:
    python3 spike_opencode_ollama.py bench/tasks/spike-opencode-ollama/spike-* \\
        --ollama-model qwen2.5:7b
"""
from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT.parent / "lib"))

from ollama_usage_proxy import OllamaUsageProxy
from energy_apple import ApplePowermetricsSampler
import project_profile


def _load_task(task_dir: Path) -> dict:
    """Load task.json and prompt.md."""
    cfg = json.loads((task_dir / "task.json").read_text())
    cfg["dir"] = task_dir
    cfg["prompt"] = (task_dir / cfg.get("prompt_file", "prompt.md")).read_text()
    return cfg


def _create_worktree(base_clone: Path, base_commit: str, ticket_id: str) -> tuple[Path, Path, str]:
    """Create a git worktree at base_commit.

    Returns:
        (clone_dir, worktree_dir, branch_name)
    """
    # Find the clone of marvin repo
    clone = base_clone.resolve()
    if not (clone / ".git").exists():
        raise RuntimeError(f"Not a git repo: {clone}")

    branch = f"spike-{ticket_id}"
    # Remove any stale branch
    subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=clone,
        capture_output=True,
    )

    worktree_dir = clone.parent / f"worktree-{ticket_id}"
    # Remove any stale worktree
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_dir)],
        cwd=clone,
        capture_output=True,
    )

    # Create new worktree
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_dir), base_commit],
        cwd=clone,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create worktree: {result.stderr}")

    return clone, worktree_dir, branch


def _cleanup_worktree(clone: Path, worktree: Path, branch: str):
    """Remove worktree and branch."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=clone,
        capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=clone,
        capture_output=True,
    )
    # Also remove the worktree dir if it still exists
    import shutil
    shutil.rmtree(worktree, ignore_errors=True)


def _run_opencode(
    worktree: Path,
    prompt: str,
    ollama_model: str,
    proxy_port: int = 8765,
    timeout: int = 600,
) -> str:
    """Run opencode against the task in the worktree.

    Returns the stdout output.
    """
    # Use the proxy URL instead of direct Ollama
    env = {**os.environ}
    # opencode CLI needs to point to the proxy
    # (This depends on opencode's actual interface; adjust as needed)

    cmd = [
        "opencode",
        "--model", f"http://localhost:{proxy_port}",
        "--prompt", prompt,
        "--timeout", str(timeout),
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT after {timeout}s]"
    except FileNotFoundError:
        raise RuntimeError("opencode not found. Install with: npm install -g @raedah/opencode")


def run_spike_task(
    task: dict,
    ollama_model: str,
    clone_dir: Path,
    base_commit: str,
    proxy: OllamaUsageProxy,
    energy_sampler: ApplePowermetricsSampler,
    timeout: int = 600,
) -> dict:
    """Run a single spike task.

    Returns a result dict with:
        - task_id: task ID
        - status: success | timeout | error
        - gate: gate result from project_profile.verify_dir
        - usage: {"prompt_tokens": N, "gen_tokens": N}
        - energy: {"joules": N, "samples": N} or {"available": False}
        - wall_s: wall time
        - error: error message if status != success
    """
    task_id = task["id"]
    prompt = task["prompt"]

    result: dict = {
        "task_id": task_id,
        "status": "unknown",
        "gate": None,
        "usage": {"prompt_tokens": 0, "gen_tokens": 0},
        "energy": None,
        "wall_s": 0,
        "error": None,
    }

    start_time = time.time()
    clone = None
    worktree = None
    branch = None

    try:
        # Create worktree
        clone, worktree, branch = _create_worktree(clone_dir, base_commit, task_id)

        # Start samplers
        proxy_started = proxy.start() if proxy else False
        energy_started = energy_sampler.start() if energy_sampler else False

        # Run opencode
        try:
            opencode_output = _run_opencode(
                worktree,
                prompt,
                ollama_model,
                timeout=timeout,
            )
            result["status"] = "opencode_run"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            opencode_output = ""

        # Stop samplers
        if proxy:
            proxy.stop()
        if energy_sampler:
            energy_result = energy_sampler.stop_and_measure()
            result["energy"] = energy_result if energy_result else {"available": False}

        # Measure usage from proxy log
        if proxy:
            result["usage"] = _measure_usage_from_proxy_log(proxy.logfile)

        # Run gate (project_profile.verify_dir)
        if result["status"] != "error":
            try:
                profile = project_profile.load_profile("marvin")
                if profile:
                    gate_result = project_profile.verify_dir(profile, worktree)
                    result["gate"] = {
                        "ok": gate_result.get("ok"),
                        "kind": gate_result.get("kind"),
                        "summary": gate_result.get("summary"),
                    }
                    result["status"] = "success"
                else:
                    result["status"] = "no_profile"
                    result["error"] = "No profile found for marvin"
            except Exception as e:
                result["status"] = "gate_error"
                result["error"] = str(e)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    finally:
        # Cleanup
        if worktree and clone and branch:
            _cleanup_worktree(clone, worktree, branch)

    result["wall_s"] = round(time.time() - start_time, 1)
    return result


def _measure_usage_from_proxy_log(logfile: Path) -> dict:
    """Read proxy logfile and sum token counts."""
    if not logfile.exists():
        return {"prompt_tokens": 0, "gen_tokens": 0}

    try:
        with open(logfile) as f:
            total_prompt = 0
            total_gen = 0
            for line in f:
                if not line.strip():
                    continue
                try:
                    log = json.loads(line)
                    total_prompt += log.get("prompt_tokens", 0)
                    total_gen += log.get("gen_tokens", 0)
                except json.JSONDecodeError:
                    pass
        return {"prompt_tokens": total_prompt, "gen_tokens": total_gen}
    except Exception:
        return {"prompt_tokens": 0, "gen_tokens": 0}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run the opencode+Ollama spike")
    parser.add_argument("task_dirs", nargs="+", help="Task directories to run")
    parser.add_argument(
        "--ollama-model",
        default="qwen2.5:7b",
        help="Ollama model to use",
    )
    parser.add_argument(
        "--clone-dir",
        type=Path,
        default=Path(__file__).parent.parent / ".git",
        help="Git clone directory of marvin",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path(__file__).parent / "results",
        help="Directory to store results",
    )
    parser.add_argument(
        "--proxy-port",
        type=int,
        default=8765,
        help="Port for ollama_usage_proxy",
    )
    parser.add_argument(
        "--no-energy",
        action="store_true",
        help="Skip energy measurement",
    )

    args = parser.parse_args()

    results_dir = args.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    # Load tasks
    tasks = []
    for task_dir_pattern in args.task_dirs:
        task_dir = Path(task_dir_pattern)
        if not task_dir.is_dir():
            print(f"Warning: not a directory: {task_dir}", file=sys.stderr)
            continue
        try:
            task = _load_task(task_dir)
            tasks.append(task)
        except Exception as e:
            print(f"Warning: failed to load task {task_dir}: {e}", file=sys.stderr)
            continue

    if not tasks:
        print("No valid tasks to run", file=sys.stderr)
        return 1

    print(f"Running {len(tasks)} tasks...")

    # Create samplers
    logfile = results_dir / "usage.jsonl"
    proxy = OllamaUsageProxy("http://localhost:11434", logfile, port=args.proxy_port)
    energy_sampler = None if args.no_energy else ApplePowermetricsSampler()

    results = []
    for task in tasks:
        try:
            base_commit = task.get("base_commit", "HEAD")
            result = run_spike_task(
                task,
                args.ollama_model,
                args.clone_dir.parent,
                base_commit,
                proxy,
                energy_sampler,
            )
            results.append(result)
            print(f"✓ {result['task_id']}: {result['status']}")
        except Exception as e:
            print(f"✗ {task['id']}: {e}", file=sys.stderr)
            results.append({
                "task_id": task["id"],
                "status": "error",
                "error": str(e),
            })

    # Write results
    results_file = results_dir / f"spike-run-{int(time.time())}.json"
    results_file.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nResults saved to {results_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
