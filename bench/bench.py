#!/usr/bin/env python3
"""marvin-bench — compare base Claude Code (clean profile) vs the MARVIN-
optimized setup on the same tasks.

Usage:
    python3 bench.py tasks/task-002-recall          # one task, both profiles
    python3 bench.py tasks/*                          # whole suite
    python3 bench.py tasks/task-002-recall --profiles clean    # one profile

Each task runs identically through every profile; results land in results/ and a
comparison table prints to stdout. Run profiles/setup.sh first.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))
from score import parse_stream, score_correctness  # noqa: E402

PROFILES = {
    "clean":  ROOT / "profiles" / "clean",           # base Claude Code (control)
    "marvin": ROOT / "profiles" / "marvin",          # symlink overlay of ~/.claude (rich)
    "lean":   ROOT / "profiles" / "lean",            # symlink overlay of ~/.claude-lean (no memory overhead)
}


def load_task(task_dir: Path) -> dict:
    cfg = json.loads((task_dir / "task.json").read_text())
    cfg["dir"] = task_dir
    cfg["prompt"] = (task_dir / cfg.get("prompt_file", "prompt.md")).read_text()
    return cfg


def run_once(task: dict, profile: str) -> dict:
    config_dir = PROFILES[profile]
    is_fs = task.get("type") == "fs"

    # fs tasks get an isolated temp workdir; qa/recall tasks run in a fixed cwd
    # (default: home) so the project-scoped memory layer engages for the marvin
    # profile. The clean profile loads no memory regardless of cwd.
    if is_fs:
        workdir = Path(tempfile.mkdtemp(prefix=f"mb-{task['id']}-{profile}-"))
        if (task["dir"] / "files").exists():
            shutil.copytree(task["dir"] / "files", workdir, dirs_exist_ok=True)
        cleanup = True
    else:
        workdir = Path(task.get("cwd", str(Path.home())))
        cleanup = False

    cmd = ["claude", "-p", task["prompt"],
           "--output-format", "stream-json", "--verbose"]
    if is_fs:
        cmd += ["--permission-mode", "bypassPermissions"]

    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir)}
    # strip inherited Claude Code session vars so the child starts clean
    for k in list(env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            env.pop(k, None)

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=workdir, env=env,
                          capture_output=True, text=True, timeout=task.get("timeout", 600))
    wall = time.time() - t0

    parsed = parse_stream(proc.stdout)
    parsed["wall_s"] = round(wall, 1)
    parsed["correctness"] = score_correctness(task, parsed["result_text"],
                                              workdir if is_fs else None)
    parsed["profile"] = profile
    if proc.returncode != 0 and not parsed.get("result_text"):
        parsed["spawn_error"] = proc.stderr[-500:]
    if cleanup:
        shutil.rmtree(workdir, ignore_errors=True)
    return parsed


def fmt_table(task_id: str, rows: list[dict]) -> str:
    cols = [("profile", 8), ("cost_usd", 10), ("total_tokens", 13),
            ("num_turns", 6), ("tool_calls", 6), ("wall_s", 7), ("correct", 8),
            ("tok/ok", 10), ("tools/ok", 9)]
    head = "  ".join(name.ljust(w) for name, w in cols)
    lines = [f"\n=== {task_id} ===", head, "-" * len(head)]
    for r in rows:
        c = r.get("correctness", {}).get("score")
        fully_correct = c == 1.0
        cell = {
            "profile":      r["profile"],
            "cost_usd":     f"${r['cost_usd']:.4f}",
            "total_tokens": str(r["total_tokens"]),
            "num_turns":    str(r["num_turns"]),
            "tool_calls":   str(r["tool_calls"]),
            "wall_s":       str(r["wall_s"]),
            "correct":      ("n/a" if c is None else f"{c:.2f}"),
            # efficiency-when-correct: only meaningful when the answer is right
            "tok/ok":       str(r["total_tokens"]) if fully_correct else "-",
            "tools/ok":     str(r["tool_calls"])   if fully_correct else "-",
        }
        lines.append("  ".join(cell[name].ljust(w) for name, w in cols))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="+", help="task directories")
    ap.add_argument("--profiles", default="clean,lean,marvin",
                    help="comma list (default: clean,lean,marvin)")
    args = ap.parse_args()

    profiles = args.profiles.split(",")
    for p in profiles:
        if p not in PROFILES:
            sys.exit(f"unknown profile '{p}'; choose from {list(PROFILES)}")
    if "clean" in profiles and not PROFILES["clean"].exists():
        sys.exit("clean profile missing — run profiles/setup.sh first")

    for task_path in args.tasks:
        task_dir = Path(task_path)
        if not (task_dir / "task.json").exists():
            print(f"skip {task_dir} (no task.json)")
            continue
        task = load_task(task_dir)
        rows = []
        for profile in profiles:
            print(f"running {task['id']} @ {profile} ...", flush=True)
            rows.append(run_once(task, profile))
        print(fmt_table(task["id"], rows))

        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = ROOT / "results" / f"{task['id']}-{stamp}.json"
        out.write_text(json.dumps({"task": task["id"], "runs": rows}, indent=2, default=str))
        print(f"saved {out}")


if __name__ == "__main__":
    main()
