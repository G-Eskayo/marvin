#!/usr/bin/env python3
"""Deep module for recording and comparing subsystem metrics (G-Eskayo/marvin#2).

Formalizes the pattern bench/RESULTS.md already uses informally for route.py's
classifier — baseline, change, re-measure, iterate until genuinely better, not
just different. Every future MR pipeline stage (sandbox orchestration's tune
loop, the MR raiser's evidence, the metrics dashboard) reads/writes through
this same three-function interface, so its own correctness matters more than
any one caller's.

Storage: per-machine JSON files (bench/metrics/<subsystem>.<machine>.json, a list
of timestamped snapshots) prevent collision across Macs. Each machine writes only
to its own file; legacy bare files (<subsystem>.json, pre-existing before this
change) are left untouched and surfaced with "legacy" tag. A parallel markdown
narrative (bench/metrics/<subsystem>.<machine>.md) mirrors RESULTS.md's style for
per-machine records, and bench/metrics/index.md is a refreshed-on-every-call
pointer file, not a separately-maintained cache -- index() always recomputes from
the per-subsystem JSON files so it can never drift out of sync with them.

`compare()` is a pure function (no I/O) -- callers own capturing baseline and
current metrics (typically via latest() for baseline, a fresh measurement for
current) and deciding whether/how to persist the comparison result.

Subsystem names must not contain a literal '.', as the parser splits on the
rightmost '.' to extract the machine label.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402

METRICS_DIR = Path.home() / ".agents" / "bench" / "metrics"

# Deltas smaller than this fraction of the baseline value (or this absolute
# value, for a baseline of 0) are "unchanged" -- floating-point/measurement
# noise shouldn't flip a verdict between runs that didn't meaningfully change.
RELATIVE_TOLERANCE = 0.001
ABSOLUTE_TOLERANCE = 1e-9


def _snapshot_path(subsystem: str, machine: str | None = None) -> Path:
    """Path to JSON snapshot file. If machine is None, uses current machine label."""
    m = machine or machine_profile.machine_label()
    return METRICS_DIR / f"{subsystem}.{m}.json"


def _narrative_path(subsystem: str, machine: str | None = None) -> Path:
    """Path to markdown narrative file. If machine is None, uses current machine label."""
    m = machine or machine_profile.machine_label()
    return METRICS_DIR / f"{subsystem}.{m}.md"


def _load_snapshots(subsystem: str, machine: str | None = None) -> list[dict]:
    """Load snapshots for a subsystem, optionally from a specific machine."""
    path = _snapshot_path(subsystem, machine)
    if not path.exists():
        return []
    return json.loads(path.read_text())


def record(subsystem: str, metrics: dict[str, dict], machine: str | None = None, replace_same_day: bool = False) -> None:
    """Append a timestamped metrics snapshot for `subsystem`.

    `metrics` maps metric name -> {"value": float, "higher_is_better": bool}.
    `machine` defaults to the current machine; specifying it explicitly writes
    to that machine's own file.
    `replace_same_day` (default False): when True, replaces today's snapshot
    instead of appending. Idempotent for same-day re-recordings.
    """
    import fcntl

    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(subsystem, machine)
    lock_path = path.with_suffix(path.suffix + ".lock")

    # Acquire exclusive lock for atomic read-modify-write
    with open(lock_path, "a") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            snapshots = _load_snapshots(subsystem, machine)
            timestamp = datetime.now(timezone.utc).isoformat()
            today = timestamp[:10]  # YYYY-MM-DD

            if replace_same_day and snapshots:
                # Replace today's snapshot if it exists
                last = snapshots[-1]
                if last.get("timestamp", "")[:10] == today:
                    snapshots[-1] = {"timestamp": timestamp, "metrics": metrics}
                else:
                    snapshots.append({"timestamp": timestamp, "metrics": metrics})
            else:
                snapshots.append({"timestamp": timestamp, "metrics": metrics})

            # Atomic write
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(snapshots, indent=2))
            tmp.replace(path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    narrative_lines = [f"## {timestamp} — {subsystem}\n"]
    for name, m in metrics.items():
        narrative_lines.append(f"- **{name}**: {m['value']}\n")
    narrative_lines.append("\n")
    narrative_path = _narrative_path(subsystem, machine)
    with narrative_path.open("a") as f:
        f.writelines(narrative_lines)


def latest(subsystem: str, machine: str | None = None) -> dict[str, dict] | None:
    """Return the most recently recorded metrics dict for `subsystem`, or
    None if nothing has ever been recorded for it. If `machine` is None,
    defaults to the current machine only (not a cross-machine merge)."""
    snapshots = _load_snapshots(subsystem, machine)
    if not snapshots:
        return None
    return snapshots[-1]["metrics"]


def all_latest(subsystem: str) -> dict[str, dict[str, dict]]:
    """Return all machines' latest metrics for `subsystem`.

    Returns {machine: metrics_dict, ...} for all .{machine}.json files found,
    plus any legacy bare {subsystem}.json file under the "legacy" key.
    """
    if not METRICS_DIR.exists():
        return {}

    result = {}

    # Find all machine-specific files: subsystem.{machine}.json
    for path in METRICS_DIR.glob(f"{subsystem}.*.json"):
        parts = path.stem.rsplit(".", 1)
        if len(parts) != 2:
            continue
        _, machine = parts
        m = latest(subsystem, machine)
        if m is not None:
            result[machine] = m

    # Check for legacy bare file: subsystem.json
    legacy_path = METRICS_DIR / f"{subsystem}.json"
    if legacy_path.exists():
        snapshots = json.loads(legacy_path.read_text())
        if snapshots:
            result["legacy"] = snapshots[-1]["metrics"]

    return result


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


def index() -> dict[str, dict[str, dict]]:
    """Recompute, from every per-subsystem JSON file, a nested subsystem ->
    machine -> latest metrics dict, and refresh bench/metrics/index.md as a
    human-readable pointer. Always recomputed live so it can never drift from
    the files it points to.

    Returns {subsystem: {machine: metrics, ...}, ...}
    """
    if not METRICS_DIR.exists():
        return {}

    result = {}
    subsystems = set()

    # Discover all subsystems: extract from both {subsystem}.json and {subsystem}.{machine}.json
    for path in sorted(METRICS_DIR.glob("*.json")):
        parts = path.stem.rsplit(".", 1)
        if len(parts) == 2:
            subsystem, _ = parts
        else:
            subsystem = path.stem
        subsystems.add(subsystem)

    # For each subsystem, gather all machines' latest data
    for subsystem in sorted(subsystems):
        all_data = all_latest(subsystem)
        if all_data:
            result[subsystem] = all_data

    # Generate index.md with nested per-machine listing
    lines = ["# Metrics Index\n\n", "Auto-generated by metrics_registry.index() — do not edit.\n\n"]
    for subsystem in sorted(result.keys()):
        lines.append(f"## {subsystem}\n\n")
        for machine in sorted(result[subsystem].keys()):
            lines.append(f"### {machine}\n\n")
            for name, m in result[subsystem][machine].items():
                lines.append(f"- **{name}**: {m['value']}\n")
            lines.append("\n")
    (METRICS_DIR / "index.md").write_text("".join(lines))

    return result
