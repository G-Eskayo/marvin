#!/usr/bin/env python3
"""marvin-bench — compare base Claude Code (clean profile) vs the MARVIN-
optimized setup on the same tasks.

Usage:
    python3 bench.py tasks/task-002-recall          # one task, both profiles
    python3 bench.py tasks/*                          # whole suite
    python3 bench.py tasks/task-002-recall --profiles clean    # one profile
    python3 bench.py tasks/* --repeat 5             # 5 runs each; reports mean ± σ
    python3 bench.py tasks/* --judge                # LLM-judge semantic grading
    python3 bench.py tasks/* --repeat 3 --judge     # both

Each task runs identically through every profile; results land in results/ and a
comparison table prints to stdout. Run profiles/setup.sh first.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import statistics as _stat
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


def run_once(task: dict, profile: str, capture_snapshot: bool = False) -> dict:
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
        if capture_snapshot:
            # capture .py files before cleanup so LLM judge can read them
            parts = []
            for p in sorted(workdir.rglob("*.py")):
                if p.stat().st_size < 30_000:
                    try:
                        parts.append(f"--- {p.name} ---\n{p.read_text(errors='ignore')}")
                    except OSError:
                        pass
            parsed["workdir_snapshot"] = "\n".join(parts)
        shutil.rmtree(workdir, ignore_errors=True)

    return parsed


def judge_run(task: dict, run: dict) -> dict:
    """Call claude as an LLM judge to semantically grade a completed run.
    Uses the system claude (no CLAUDE_CONFIG_DIR restriction) — inherits the
    user's default profile (richest available judge).
    Returns a correctness dict with score 0.0 or 1.0 + rationale.
    """
    snapshot = run.get("workdir_snapshot", "")
    judge_prompt = (
        "You are grading whether a coding assistant correctly completed a task.\n\n"
        f"TASK PROMPT:\n{task['prompt']}\n\n"
        f"ASSISTANT RESPONSE:\n{run.get('result_text') or '(empty)'}\n\n"
        + (f"FILES IN WORKDIR AFTER RUN:\n{snapshot}\n\n" if snapshot else "")
        + "Did the assistant correctly and completely implement what the task asked?\n"
        "Reply with exactly two lines:\n"
        "VERDICT: PASS\n"
        "REASON: one sentence\n\n"
        "or\n\n"
        "VERDICT: FAIL\n"
        "REASON: one sentence explaining the specific gap"
    )

    try:
        proc = subprocess.run(
            ["claude", "-p", judge_prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=90
        )
        text = proc.stdout.strip()
    except Exception as exc:
        return {"score": None, "judge": "llm", "rationale": f"judge call failed: {exc}"}

    verdict_line = next((l for l in text.splitlines() if "VERDICT" in l.upper()), "")
    passed = "PASS" in verdict_line.upper()
    reason_m = re.search(r"REASON\s*:\s*(.+)", text, re.IGNORECASE)
    reason = reason_m.group(1).strip() if reason_m else text[:300]

    return {
        "score": 1.0 if passed else 0.0,
        "judge": "llm",
        "rationale": reason,
    }


# ── aggregation ───────────────────────────────────────────────────────────────

def aggregate_runs(runs: list[dict]) -> dict:
    """Reduce N repeated runs into a summary row with mean + stddev fields.
    The raw runs are preserved in _raw for JSON export.
    """
    n = len(runs)
    agg: dict = {"profile": runs[0]["profile"], "_n": n, "_raw": runs}

    for field in ("cost_usd", "total_tokens", "num_turns", "tool_calls", "wall_s"):
        vals = [r[field] for r in runs]
        agg[field] = _stat.mean(vals)
        agg[field + "_std"] = _stat.stdev(vals) if n > 1 else 0.0

    scores = [(r.get("correctness") or {}).get("score") or 0.0 for r in runs]
    agg["correctness"] = {"score": _stat.mean(scores)}
    agg["_n_correct"] = sum(1 for s in scores if s == 1.0)

    # judge scores if present
    j_scores = [
        (r.get("judge_correctness") or {}).get("score")
        for r in runs
        if (r.get("judge_correctness") or {}).get("score") is not None
    ]
    if j_scores:
        agg["judge_correctness"] = {
            "score": _stat.mean(j_scores),
            "judge": "llm",
            "_n_pass": sum(1 for s in j_scores if s == 1.0),
        }

    return agg


# ── formatting ────────────────────────────────────────────────────────────────

def _ms(mean: float, std: float, fmt: str) -> str:
    """Format mean ± std; omit ±0 when std is zero."""
    m = format(mean, fmt)
    if std == 0:
        return m
    s = format(std, fmt)
    return f"{m}(±{s})"


def fmt_table(task_id: str, rows: list[dict], show_judge: bool = False) -> str:
    multi = rows[0].get("_n", 1) > 1

    if not multi:
        return _fmt_single(task_id, rows, show_judge)
    return _fmt_multi(task_id, rows, show_judge)


def _fmt_single(task_id: str, rows: list[dict], show_judge: bool) -> str:
    judge_col = [("judge", 6)] if show_judge else []
    cols = ([("profile", 8), ("cost_usd", 10), ("total_tokens", 13),
              ("num_turns", 6), ("tool_calls", 6), ("wall_s", 7), ("correct", 8)]
            + judge_col
            + [("tok/ok", 10), ("tools/ok", 9)])
    head = "  ".join(name.ljust(w) for name, w in cols)
    lines = [f"\n=== {task_id} ===", head, "-" * len(head)]
    for r in rows:
        c = (r.get("correctness") or {}).get("score")
        jc = (r.get("judge_correctness") or {}).get("score")
        fully_correct = c == 1.0
        cell = {
            "profile":      r["profile"],
            "cost_usd":     f"${r['cost_usd']:.4f}",
            "total_tokens": str(r["total_tokens"]),
            "num_turns":    str(r["num_turns"]),
            "tool_calls":   str(r["tool_calls"]),
            "wall_s":       str(r["wall_s"]),
            "correct":      ("n/a" if c is None else f"{c:.2f}"),
            "judge":        ("n/a" if jc is None else ("pass" if jc == 1.0 else "FAIL")),
            "tok/ok":       str(r["total_tokens"]) if fully_correct else "-",
            "tools/ok":     str(r["tool_calls"])   if fully_correct else "-",
        }
        lines.append("  ".join(cell[name].ljust(w) for name, w in cols))
        # judge rationale on a second line when it fails
        if show_judge and jc is not None and jc < 1.0:
            rationale = (r.get("judge_correctness") or {}).get("rationale", "")
            if rationale:
                lines.append(f"  {'':8}  {'':10}  {'':13}  {'':6}  {'':6}  {'':7}  {'':8}  "
                              f"⚠ {rationale[:80]}")
    return "\n".join(lines)


def _fmt_multi(task_id: str, rows: list[dict], show_judge: bool) -> str:
    n = rows[0]["_n"]
    judge_col = [("judge", 10)] if show_judge else []
    cols = ([("profile", 8), ("cost_usd", 18), ("total_tokens", 18),
              ("num_turns", 12), ("tool_calls", 12), ("wall_s", 12),
              ("correct", 10)]
            + judge_col
            + [("tok/ok", 18), ("tools/ok", 12)])
    head = "  ".join(name.ljust(w) for name, w in cols)
    lines = [f"\n=== {task_id} (N={n}) ===", head, "-" * len(head)]

    for r in rows:
        c = (r.get("correctness") or {}).get("score")
        n_ok = r.get("_n_correct", 0)
        jc_entry = r.get("judge_correctness") or {}
        jc = jc_entry.get("score")
        j_n_pass = jc_entry.get("_n_pass")

        # tok/ok and tools/ok: stats over runs that scored 1.0 substring-correct
        ok_runs = [x for x in r.get("_raw", [])
                   if (x.get("correctness") or {}).get("score") == 1.0]
        if ok_runs:
            tv = [x["total_tokens"] for x in ok_runs]
            cv = [x["tool_calls"] for x in ok_runs]
            tok_ok = _ms(_stat.mean(tv), _stat.stdev(tv) if len(tv) > 1 else 0.0, ".0f")
            tools_ok = _ms(_stat.mean(cv), _stat.stdev(cv) if len(cv) > 1 else 0.0, ".1f")
        else:
            tok_ok = tools_ok = "-"

        cell = {
            "profile":      r["profile"],
            "cost_usd":     "$" + _ms(r["cost_usd"], r["cost_usd_std"], ".4f"),
            "total_tokens": _ms(r["total_tokens"], r["total_tokens_std"], ".0f"),
            "num_turns":    _ms(r["num_turns"], r["num_turns_std"], ".1f"),
            "tool_calls":   _ms(r["tool_calls"], r["tool_calls_std"], ".1f"),
            "wall_s":       _ms(r["wall_s"], r["wall_s_std"], ".1f"),
            "correct":      (f"n/a" if c is None else f"{n_ok}/{n}={c:.2f}"),
            "judge":        ("n/a" if jc is None else f"{j_n_pass}/{n}={jc:.2f}"),
            "tok/ok":       tok_ok,
            "tools/ok":     tools_ok,
        }
        lines.append("  ".join(cell[name].ljust(w) for name, w in cols))
    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="+", help="task directories")
    ap.add_argument("--profiles", default="clean,lean,marvin",
                    help="comma list (default: clean,lean,marvin)")
    ap.add_argument("--repeat", type=int, default=1, metavar="N",
                    help="run each profile N times; report mean ± σ (default 1)")
    ap.add_argument("--judge", action="store_true",
                    help="add LLM-judge semantic grading alongside substring grading")
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
        all_raw: list[dict] = []

        for profile in profiles:
            if args.repeat == 1:
                print(f"running {task['id']} @ {profile} ...", flush=True)
                run = run_once(task, profile, capture_snapshot=args.judge)
                if args.judge:
                    print(f"  judging {task['id']} @ {profile} ...", flush=True)
                    run["judge_correctness"] = judge_run(task, run)
                rows.append(run)
                all_raw.append(run)
            else:
                profile_runs = []
                for i in range(args.repeat):
                    print(f"running {task['id']} @ {profile} [{i+1}/{args.repeat}] ...",
                          flush=True)
                    run = run_once(task, profile, capture_snapshot=args.judge)
                    if args.judge:
                        print(f"  judging [{i+1}/{args.repeat}] ...", flush=True)
                        run["judge_correctness"] = judge_run(task, run)
                    profile_runs.append(run)
                all_raw.extend(profile_runs)
                rows.append(aggregate_runs(profile_runs))

        print(fmt_table(task["id"], rows, show_judge=args.judge))

        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = ROOT / "results" / f"{task['id']}-{stamp}.json"
        out.write_text(json.dumps(
            {"task": task["id"], "repeat": args.repeat, "judge": args.judge, "runs": all_raw},
            indent=2, default=str,
        ))
        print(f"saved {out}")


if __name__ == "__main__":
    main()
