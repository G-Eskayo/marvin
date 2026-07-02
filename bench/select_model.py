#!/usr/bin/env python3
"""select_model.py — ascending-cost model sweep for a single project task.

Tries candidate models cheapest-first (free local Ollama -> Haiku -> the
account's default Claude model, ascending) and locks in the FIRST one that
achieves --repeat consecutive substring+judge passes. Escalates to the next,
more expensive candidate on any failure.

A single or double pass is not enough to trust: repeat runs against the same
model in this harness have already shown judge/substring disagreement and
wide token variance run-to-run (see marvin-bench-harness memory, Run 13's
--repeat 3 data). Default --repeat is therefore 3, not 1 or 2.

Reuses bench.py's run mechanics directly (run_once, run_once_ollama,
judge_run, the infra-error tagging, and the profile-isolated judge) so this
never duplicates — or drifts from — the main harness's scoring logic.

Usage:
    python3 select_model.py tasks/task-012-protocol-mismatch
    python3 select_model.py tasks/task-014-kb-lookup --profile marvin
    python3 select_model.py tasks/task-001-bugfix --candidates \\
        ollama:qwen2.5:7b,ollama:qwen2.5:14b,claude:claude-haiku-4-5-20251001,claude:default
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
from bench import (  # noqa: E402
    PROFILES, load_task, run_once, run_once_ollama, judge_run, _check_quota,
)

# Ascending cost. "claude:default" = no --model override (the account's
# configured default, confirmed claude-sonnet-5 as of 2026-07-01). Deliberately
# stops there rather than auto-escalating to Opus/Fable — those cost/drain
# more per the account's own promo notice, and picking them should be an
# explicit --candidates choice, not a silent default.
DEFAULT_LADDER = [
    ("ollama", "qwen2.5:7b"),
    ("ollama", "qwen2.5:14b"),
    ("claude", "claude-haiku-4-5-20251001"),
    ("claude", "default"),
]


def _parse_candidates(spec: str) -> list[tuple[str, str]]:
    out = []
    for item in spec.split(","):
        runner, _, model = item.partition(":")
        out.append((runner.strip(), model.strip()))
    return out


def _run_one(task: dict, profile: str, runner: str, model: str, context: str) -> dict | None:
    if runner == "ollama":
        run = run_once_ollama(task, profile, model, context)
        if run is None:
            return None  # fs tasks unsupported by the ollama runner
        run["judge_correctness"] = judge_run(task, run)
        return run
    m = None if model == "default" else model
    run = run_once(task, profile, capture_snapshot=True, model=m)
    if not run.get("infra_error"):
        run["judge_correctness"] = judge_run(task, run)
    return run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task", help="task directory")
    ap.add_argument("--profile", default="marvin", choices=list(PROFILES),
                    help="profile to run candidates under (default: marvin)")
    ap.add_argument("--repeat", type=int, default=3, metavar="N",
                    help="consecutive substr+judge passes required to lock in "
                         "a model (default 3 — 2 was judged too noisy to trust)")
    ap.add_argument("--context", default="rag", choices=["full", "rag"],
                    help="context injection mode for ollama candidates (default: rag)")
    ap.add_argument("--candidates", default=None,
                    help="comma list runner:model, ascending cost "
                         "(default: ollama qwen 7b -> 14b -> haiku -> default)")
    args = ap.parse_args()

    task_dir = Path(args.task)
    if not (task_dir / "task.json").exists():
        sys.exit(f"{task_dir} has no task.json")
    task = load_task(task_dir)

    ladder = _parse_candidates(args.candidates) if args.candidates else DEFAULT_LADDER

    print(f"preflight: up to {len(ladder)} candidate(s) x {args.repeat} run(s) "
          f"(worst case {len(ladder) * args.repeat * 2} claude sessions incl. judging)",
          flush=True)
    quota = _check_quota()
    if quota is None:
        print("preflight: could not determine account quota — proceeding anyway", flush=True)
    elif quota.get("status") != "allowed":
        reset_str = time.strftime("%H:%M %Z", time.localtime(quota.get("resetsAt", 0)))
        sys.exit(f"aborting — account already at its {quota.get('rateLimitType')} "
                 f"limit (resets {reset_str}); re-run after that")
    else:
        reset_str = time.strftime("%H:%M %Z", time.localtime(quota.get("resetsAt", 0)))
        print(f"preflight: quota status=allowed resets={reset_str}", flush=True)

    trace = []
    selected = None

    for runner, model in ladder:
        label = f"{runner}:{model}"
        print(f"\n--- trying {label} (need {args.repeat}/{args.repeat} consecutive passes) ---",
              flush=True)
        runs = []
        rejected = False
        skipped = False

        for i in range(args.repeat):
            print(f"  run {i+1}/{args.repeat} ...", flush=True)
            run = _run_one(task, args.profile, runner, model, args.context)

            if run is None:
                print(f"  {label} does not support this task type — skipping candidate",
                      flush=True)
                skipped = True
                break

            if run.get("infra_error"):
                sys.exit(f"aborting sweep — hit an infra error (rate/session limit or "
                         f"stale auth) mid-run on {label}; re-run after quota resets "
                         f"rather than trusting a partial sweep")

            runs.append(run)
            sc = (run.get("correctness") or {}).get("score")
            jc = (run.get("judge_correctness") or {}).get("score")
            passed = sc == 1.0 and jc == 1.0
            print(f"    substr={sc} judge={jc} -> {'PASS' if passed else 'FAIL'}", flush=True)
            if not passed:
                rejected = True
                break

        locked_in = (not rejected and not skipped and len(runs) == args.repeat)
        trace.append({"runner": runner, "model": model, "label": label,
                       "runs": runs, "locked_in": locked_in, "skipped": skipped})

        if locked_in:
            selected = label
            print(f"\n*** LOCKED IN: {label} — {args.repeat}/{args.repeat} consecutive "
                  f"substr+judge passes ***", flush=True)
            break
        elif not skipped:
            print(f"  {label} rejected after {len(runs)}/{args.repeat} — escalating", flush=True)

    if selected is None:
        print(f"\nNo candidate in the ladder reached {args.repeat}/{args.repeat} consecutive "
              f"passes. Try a longer --candidates ladder (e.g. add claude-opus-4-8) or "
              f"reconsider whether this task is inherently too noisy for a {args.repeat}-run gate.",
              flush=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "results" / f"model-select-{task['id']}-{stamp}.json"
    out.write_text(json.dumps({
        "task": task["id"], "profile": args.profile, "repeat": args.repeat,
        "ladder": [f"{r}:{m}" for r, m in ladder], "selected": selected, "trace": trace,
    }, indent=2, default=str))
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
