#!/usr/bin/env python3
"""Deep module for recording and comparing subsystem metrics (G-Eskayo/marvin#2).

Formalizes the pattern bench/RESULTS.md already uses informally for route.py's
classifier — baseline, change, re-measure, iterate until genuinely better, not
just different. Every future MR pipeline stage (sandbox orchestration's tune
loop, the MR raiser's evidence, the metrics dashboard) reads/writes through
this same three-function interface, so its own correctness matters more than
any one caller's.

Storage: one JSON file per subsystem per machine (bench/metrics/<subsystem>.<machine>.json,
a list of timestamped snapshots) is the machine-readable source of truth `latest()`
and `index()` read from. Legacy flat files (bench/metrics/<subsystem>.json) are
kept as frozen history and included in queries via `_load_all_snapshots()`, so
historical data before the per-machine split remains visible. A parallel markdown
narrative (bench/metrics/<subsystem>.<machine>.md) mirrors RESULTS.md's
human-readable style, and bench/metrics/index.md is a refreshed-on-every-call
pointer file, not a separately-maintained cache -- index() always recomputes
from all per-subsystem JSON files so it can never drift out of sync with them.

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


def _machine() -> str:
    """Lazy import to avoid touching hardware probe / cache file unless needed."""
    import machine_profile
    return machine_profile.machine_label()


def _parse_filename(stem: str) -> tuple[str, str | None]:
    """Parse a metrics filename stem into (subsystem, machine).

    Convention: subsystem names never contain dots. Filenames are:
    - "<subsystem>.<machine>.json" -> ("subsystem", "machine")
    - "<subsystem>.json" (legacy) -> ("subsystem", None)
    """
    if "." not in stem:
        return stem, None
    parts = stem.rsplit(".", 1)
    subsystem, candidate_machine = parts[0], parts[1]
    # Check if it looks like a machine label (known patterns: mac-mini, macbook-pro)
    # or a file extension remnant. Known good machine names are alphabetic+hyphen.
    if candidate_machine and all(c.isalnum() or c == "-" for c in candidate_machine):
        return subsystem, candidate_machine
    return stem, None


def _snapshot_path(subsystem: str, machine: str | None = None) -> Path:
    """Path to the JSON snapshot file for a subsystem on a specific machine."""
    if machine is None:
        machine = _machine()
    return METRICS_DIR / f"{subsystem}.{machine}.json"


def _narrative_path(subsystem: str, machine: str | None = None) -> Path:
    """Path to the markdown narrative file for a subsystem on a specific machine."""
    if machine is None:
        machine = _machine()
    return METRICS_DIR / f"{subsystem}.{machine}.md"


def _load_snapshots(subsystem: str, machine: str | None = None) -> list[dict]:
    """Load snapshots from a single per-machine file."""
    path = _snapshot_path(subsystem, machine)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _load_all_snapshots(subsystem: str) -> list[dict]:
    """Load and merge all snapshots for a subsystem across all machines + legacy file.

    Returns chronologically sorted list of {timestamp, metrics} dicts.
    """
    all_snapshots = []

    # Load per-machine files
    if METRICS_DIR.exists():
        for path in METRICS_DIR.glob(f"{subsystem}.*.json"):
            try:
                snapshots = json.loads(path.read_text())
                if isinstance(snapshots, list):
                    all_snapshots.extend(snapshots)
            except (json.JSONDecodeError, OSError):
                continue

    # Load legacy flat file if it exists
    legacy_path = METRICS_DIR / f"{subsystem}.json"
    if legacy_path.exists():
        try:
            snapshots = json.loads(legacy_path.read_text())
            if isinstance(snapshots, list):
                all_snapshots.extend(snapshots)
        except (json.JSONDecodeError, OSError):
            pass

    # Sort by timestamp so later entries override earlier ones in queries
    all_snapshots.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
    return all_snapshots


def record(subsystem: str, metrics: dict[str, dict], machine: str | None = None) -> None:
    """Append a timestamped metrics snapshot for `subsystem` on `machine`.

    `metrics` maps metric name -> {"value": float, "higher_is_better": bool}.
    `machine` defaults to the current machine's label.
    """
    machine = machine or _machine()
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = _load_snapshots(subsystem, machine)
    timestamp = datetime.now(timezone.utc).isoformat()
    snapshots.append({"timestamp": timestamp, "metrics": metrics})
    _snapshot_path(subsystem, machine).write_text(json.dumps(snapshots, indent=2))

    narrative_lines = [f"## {timestamp} — {subsystem}\n"]
    for name, m in metrics.items():
        narrative_lines.append(f"- **{name}**: {m['value']}\n")
    narrative_lines.append("\n")
    narrative_path = _narrative_path(subsystem, machine)
    with narrative_path.open("a") as f:
        f.writelines(narrative_lines)


def latest(subsystem: str, machine: str | None = None) -> dict[str, dict] | None:
    """Return the most recently recorded metrics dict for `subsystem` on `machine`.

    `machine` defaults to the current machine. Returns None if nothing has been
    recorded on that machine. Falls back to legacy flat file for that subsystem
    if this machine has never recorded under the new per-machine scheme.
    """
    machine = machine or _machine()
    snapshots = _load_snapshots(subsystem, machine)
    if not snapshots:
        # Fall back to legacy flat file only if this machine has no per-machine records
        legacy_path = METRICS_DIR / f"{subsystem}.json"
        if legacy_path.exists():
            try:
                legacy_snapshots = json.loads(legacy_path.read_text())
                if isinstance(legacy_snapshots, list) and legacy_snapshots:
                    return legacy_snapshots[-1]["metrics"]
            except (json.JSONDecodeError, OSError):
                pass
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
    """Recompute, from every per-subsystem JSON file (per-machine and legacy),
    a subsystem -> latest (cross-machine) metrics dict, and refresh
    bench/metrics/index.md as a human-readable pointer. Always recomputed live
    so it can never drift from the files it points to."""
    if not METRICS_DIR.exists():
        return {}

    # Group filenames by subsystem (before the machine/extension)
    subsystems = set()
    for path in METRICS_DIR.glob("*.json"):
        subsystem, machine = _parse_filename(path.stem)
        subsystems.add(subsystem)

    result = {}
    for subsystem in sorted(subsystems):
        # Load all snapshots (per-machine + legacy) and get the latest
        snapshots = _load_all_snapshots(subsystem)
        if snapshots:
            result[subsystem] = snapshots[0]["metrics"]  # Already sorted descending

    lines = ["# Metrics Index\n\n", "Auto-generated by metrics_registry.index() — do not edit.\n\n"]
    for subsystem, metrics in sorted(result.items()):
        lines.append(f"## {subsystem}\n\n")
        for name, m in metrics.items():
            lines.append(f"- **{name}**: {m['value']}\n")
        lines.append("\n")
    (METRICS_DIR / "index.md").write_text("".join(lines))

    return result
