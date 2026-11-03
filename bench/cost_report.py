#!/usr/bin/env python3
"""Cost per successful task, from bench.py result files (marvin#645).

Reads the JSON files bench.py saves, groups runs by task and cell (profile, model
override, tag), and prints markdown tables: mean and spread of cost, tokens and wall
time, the success count, cost per successful task, and each treatment cell's cost
per success as a ratio of the baseline cell's, with a bootstrap interval.

A run succeeds when its hidden check passes (if the task has one) AND the LLM judge
passes (if it was judged); with neither, the substring score must be 1.0. Failed runs
still cost money, so cost per success = total cost of all runs / successful runs.

    ~/.agents/venv/bin/python bench/cost_report.py bench/results/run31 --base clean --treat marvin
    ~/.agents/venv/bin/python bench/cost_report.py bench/results/run31 --base marvin --treat marvin+caveman
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics as st
from pathlib import Path

MODEL_SHORT = ("haiku", "sonnet", "opus", "fable")


# ── success and per-cell summary ──────────────────────────────────────────

def is_success(run: dict) -> bool | None:
    if run.get("infra_error"):
        return None
    check = run.get("check")
    judge = (run.get("judge_correctness") or {}).get("score")
    if check is not None or judge is not None:
        return (check is None or bool(check.get("pass"))) and (judge is None or judge == 1.0)
    return (run.get("correctness") or {}).get("score") == 1.0


def _input_tokens(r: dict) -> int:
    return ((r.get("input_tokens") or 0) + (r.get("cache_creation_input_tokens") or 0)
            + (r.get("cache_read_input_tokens") or 0))


def _cps(runs: list[dict]) -> float:
    ok = sum(1 for r in runs if is_success(r))
    return sum(r["cost_usd"] for r in runs) / ok if ok else math.inf


def _sd(xs: list[float]) -> float:
    return st.stdev(xs) if len(xs) > 1 else 0.0


def summarize_cell(runs: list[dict]) -> dict:
    ok_runs = [r for r in runs if not r.get("infra_error")]
    costs = [r["cost_usd"] for r in ok_runs]
    outs = [r.get("output_tokens") or 0 for r in ok_runs]
    ins = [_input_tokens(r) for r in ok_runs]
    walls = [r.get("wall_s") or 0.0 for r in ok_runs]
    n_success = sum(1 for r in ok_runs if is_success(r))
    return {
        "n": len(ok_runs),
        "n_infra_error": len(runs) - len(ok_runs),
        "n_success": n_success,
        "cost_mean": st.mean(costs) if costs else 0.0,
        "cost_sd": _sd(costs),
        "output_mean": st.mean(outs) if outs else 0.0,
        "output_sd": _sd(outs),
        "input_mean": st.mean(ins) if ins else 0.0,
        "input_sd": _sd(ins),
        "wall_mean": st.mean(walls) if walls else 0.0,
        "wall_sd": _sd(walls),
        "cost_per_success": _cps(ok_runs) if ok_runs else math.inf,
    }


# ── ratios ────────────────────────────────────────────────────────────────

def _ratio(base: list[dict], treat: list[dict]) -> float | None:
    b = _cps(base)
    if math.isinf(b):
        return None
    return _cps(treat) / b


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi or math.isinf(xs[lo]) or math.isinf(xs[hi]):
        return xs[int(round(k))]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def ratio_ci(base: list[dict], treat: list[dict], iters: int = 4000, seed: int = 645):
    """Treatment / baseline cost per success, with a 95% percentile bootstrap interval
    (runs resampled with replacement inside each cell). (None, None, None) when the
    baseline never succeeds."""
    base = [r for r in base if not r.get("infra_error")]
    treat = [r for r in treat if not r.get("infra_error")]
    point = _ratio(base, treat)
    if point is None:
        return None, None, None
    rng = random.Random(seed)
    samples = []
    for _ in range(iters):
        r = _ratio([rng.choice(base) for _ in base], [rng.choice(treat) for _ in treat])
        if r is not None:
            samples.append(r)
    return point, _pct(samples, 0.025), _pct(samples, 0.975)


def _geomean(xs: list[float]) -> float:
    if any(math.isinf(x) for x in xs):
        return math.inf
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def headline(pairs: dict[str, tuple[list[dict], list[dict]]], iters: int = 4000, seed: int = 645) -> dict:
    """Geometric mean, over tasks, of treatment/baseline cost per success. Tasks where
    either side never succeeded can't give a ratio and are listed in `excluded`."""
    tasks, excluded = [], []
    for t, (b, tr) in pairs.items():
        r = _ratio(b, tr)
        (tasks if r is not None and not math.isinf(r) and r > 0 else excluded).append(t)
    if not tasks:
        return {"ratio": None, "lo": None, "hi": None, "tasks": [], "excluded": excluded}
    point = _geomean([_ratio(*pairs[t]) for t in tasks])
    rng = random.Random(seed)
    samples = []
    for _ in range(iters):
        rs = []
        for t in tasks:
            b, tr = pairs[t]
            r = _ratio([rng.choice(b) for _ in b], [rng.choice(tr) for _ in tr])
            if r is None:
                break
            rs.append(r)
        else:
            samples.append(_geomean(rs) if all(x > 0 for x in rs) else 0.0)
    return {"ratio": point, "lo": _pct(samples, 0.025), "hi": _pct(samples, 0.975),
            "tasks": tasks, "excluded": excluded}


# ── loading ───────────────────────────────────────────────────────────────

def cell_name(profile: str, model: str | None, tag: str | None) -> str:
    name = profile
    if model and model != "default":
        name += "@" + next((m for m in MODEL_SHORT if m in model.lower()), model)
    if tag:
        name += "+" + tag
    return name


def load_cells(paths) -> dict[str, dict[str, list[dict]]]:
    files: list[Path] = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    cells: dict[str, dict[str, list[dict]]] = {}
    for f in files:
        d = json.loads(f.read_text())
        for r in d.get("runs", []):
            name = cell_name(r.get("profile", "?"), d.get("model"), d.get("tag"))
            cells.setdefault(d["task"], {}).setdefault(name, []).append(r)
    return cells


# ── markdown ──────────────────────────────────────────────────────────────

def _money(x: float) -> str:
    return "never succeeded" if math.isinf(x) else f"${x:.3f}"


def _pct_change(r: float | None) -> str:
    if r is None:
        return "n/a"
    if math.isinf(r):
        return "never succeeded"
    return f"{(r - 1) * 100:+.0f}%"


def cells_table(cells: dict[str, dict[str, list[dict]]]) -> str:
    out = ["| Task | Cell | N | Success | Cost $ mean (sd) | Input tok mean | Output tok mean (sd) "
           "| Wall s mean (sd) | $ per success |",
           "|---|---|---|---|---|---|---|---|---|"]
    for task in sorted(cells):
        for name in sorted(cells[task]):
            s = summarize_cell(cells[task][name])
            out.append(
                f"| {task} | {name} | {s['n']} | {s['n_success']}/{s['n']} "
                f"| {s['cost_mean']:.3f} ({s['cost_sd']:.3f}) | {s['input_mean']:,.0f} "
                f"| {s['output_mean']:,.0f} ({s['output_sd']:,.0f}) "
                f"| {s['wall_mean']:.0f} ({s['wall_sd']:.0f}) | {_money(s['cost_per_success'])} |")
    return "\n".join(out)


def comparison_table(cells, base: str, treat: str) -> str:
    out = [f"| Task | {base} $/success | {treat} $/success | change | 95% bootstrap interval |",
           "|---|---|---|---|---|"]
    pairs = {}
    for task in sorted(cells):
        if base not in cells[task] or treat not in cells[task]:
            continue
        b, t = cells[task][base], cells[task][treat]
        pairs[task] = (b, t)
        point, lo, hi = ratio_ci(b, t)
        interval = "n/a" if point is None else f"{_pct_change(lo)} to {_pct_change(hi)}"
        out.append(f"| {task} | {_money(summarize_cell(b)['cost_per_success'])} "
                   f"| {_money(summarize_cell(t)['cost_per_success'])} | {_pct_change(point)} | {interval} |")
    h = headline(pairs) if pairs else None
    if h and h["ratio"] is not None:
        out.append(f"| **geometric mean over {len(h['tasks'])} tasks** | | | **{_pct_change(h['ratio'])}** "
                   f"| {_pct_change(h['lo'])} to {_pct_change(h['hi'])} |")
    if h and h["excluded"]:
        out.append(f"\nNot in the mean (one side never succeeded): {', '.join(h['excluded'])}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="result JSON files or folders of them")
    ap.add_argument("--base", default="clean", help="baseline cell (default clean)")
    ap.add_argument("--treat", action="append", default=None,
                    help="treatment cell(s) to compare with the baseline (repeatable; default marvin)")
    args = ap.parse_args()
    cells = load_cells(args.paths)
    print(cells_table(cells))
    for t in args.treat or ["marvin"]:
        print(f"\n**{t} vs {args.base}** (cost per successful task)\n")
        print(comparison_table(cells, args.base, t))


if __name__ == "__main__":
    main()
