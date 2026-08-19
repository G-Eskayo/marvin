#!/usr/bin/env python3
"""Deep module for recording and comparing subsystem metrics (G-Eskayo/marvin#2).

Formalizes the pattern bench/RESULTS.md already uses informally for route.py's
classifier — baseline, change, re-measure, iterate until genuinely better, not
just different. Every future MR pipeline stage (sandbox orchestration's tune
loop, the MR raiser's evidence, the metrics dashboard) reads/writes through
this same three-function interface, so its own correctness matters more than
any one caller's.

Storage: one JSON file per subsystem (bench/metrics/<subsystem>.json, a list
of timestamped snapshots) is the machine-readable source of truth `latest()`
and `index()` read from. A parallel markdown narrative
(bench/metrics/<subsystem>.md) mirrors RESULTS.md's human-readable style, and
bench/metrics/index.md is a refreshed-on-every-call pointer file, not a
separately-maintained cache -- index() always recomputes from the per-subsystem
JSON files so it can never drift out of sync with them.

`compare()` is a pure function (no I/O) -- callers own capturing baseline and
current metrics (typically via latest() for baseline, a fresh measurement for
current) and deciding whether/how to persist the comparison result.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

METRICS_DIR = Path.home() / ".agents" / "bench" / "metrics"

# Deltas smaller than this fraction of the baseline value (or this absolute
# value, for a baseline of 0) are "unchanged" -- floating-point/measurement
# noise shouldn't flip a verdict between runs that didn't meaningfully change.
RELATIVE_TOLERANCE = 0.001
ABSOLUTE_TOLERANCE = 1e-9


def _snapshot_path(subsystem: str) -> Path:
    return METRICS_DIR / f"{subsystem}.json"


def _narrative_path(subsystem: str) -> Path:
    return METRICS_DIR / f"{subsystem}.md"


def _load_snapshots(subsystem: str) -> list[dict]:
    path = _snapshot_path(subsystem)
    if not path.exists():
        return []
    return json.loads(path.read_text())


def record(subsystem: str, metrics: dict[str, dict]) -> None:
    """Append a timestamped metrics snapshot for `subsystem`.

    `metrics` maps metric name -> {"value": float, "higher_is_better": bool}.
    """
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = _load_snapshots(subsystem)
    timestamp = datetime.now(timezone.utc).isoformat()
    snapshots.append({"timestamp": timestamp, "metrics": metrics})
    _snapshot_path(subsystem).write_text(json.dumps(snapshots, indent=2))

    narrative_lines = [f"## {timestamp} — {subsystem}\n"]
    for name, m in metrics.items():
        narrative_lines.append(f"- **{name}**: {m['value']}\n")
    narrative_lines.append("\n")
    narrative_path = _narrative_path(subsystem)
    with narrative_path.open("a") as f:
        f.writelines(narrative_lines)


def latest(subsystem: str) -> dict[str, dict] | None:
    """Return the most recently recorded metrics dict for `subsystem`, or
    None if nothing has ever been recorded for it."""
    snapshots = _load_snapshots(subsystem)
    if not snapshots:
        return None
    return snapshots[-1]["metrics"]


def _direction(baseline_value: float, current_value: float, higher_is_better: bool) -> str:
    delta = current_value - baseline_value
    tolerance = max(ABSOLUTE_TOLERANCE, abs(baseline_value) * RELATIVE_TOLERANCE)
    if abs(delta) <= tolerance:
        return "unchanged"
    improved = (delta > 0) if higher_is_better else (delta < 0)
    return "improved" if improved else "regressed"


def compare(subsystem: str, baseline: dict[str, dict], current: dict[str, dict]) -> dict:
    """Compare two metrics snapshots for `subsystem`. Pure function -- no I/O.

    Returns {"subsystem", "verdict", "passing", "metrics": {name: {...}}}.
    Only metrics present in *both* baseline and current are compared -- a
    metric that's new or missing on one side is informational, not a
    regression/improvement signal. `passing` is True only when the overall
    verdict is "improved" (no regressions, at least one real improvement) --
    "unchanged" deliberately does not pass, matching "genuinely better, not
    just different."
    """
    compared = {}
    for name in baseline.keys() & current.keys():
        b, c = baseline[name], current[name]
        higher_is_better = b.get("higher_is_better", True)
        direction = _direction(b["value"], c["value"], higher_is_better)
        compared[name] = {
            "baseline": b["value"],
            "current": c["value"],
            "delta": c["value"] - b["value"],
            "direction": direction,
        }

    directions = {m["direction"] for m in compared.values()}
    if directions == {"unchanged"} or not directions:
        verdict = "unchanged"
    elif "regressed" in directions and "improved" in directions:
        verdict = "mixed"
    elif "regressed" in directions:
        verdict = "regressed"
    else:
        verdict = "improved"

    return {
        "subsystem": subsystem,
        "verdict": verdict,
        "passing": verdict == "improved",
        "metrics": compared,
    }


def index() -> dict[str, dict]:
    """Recompute, from every per-subsystem JSON file, a subsystem -> latest
    metrics dict, and refresh bench/metrics/index.md as a human-readable
    pointer. Always recomputed live so it can never drift from the files it
    points to."""
    if not METRICS_DIR.exists():
        return {}

    result = {}
    for path in sorted(METRICS_DIR.glob("*.json")):
        subsystem = path.stem
        m = latest(subsystem)
        if m is not None:
            result[subsystem] = m

    lines = ["# Metrics Index\n\n", "Auto-generated by metrics_registry.index() — do not edit.\n\n"]
    for subsystem, metrics in sorted(result.items()):
        lines.append(f"## {subsystem}\n\n")
        for name, m in metrics.items():
            lines.append(f"- **{name}**: {m['value']}\n")
        lines.append("\n")
    (METRICS_DIR / "index.md").write_text("".join(lines))

    return result
