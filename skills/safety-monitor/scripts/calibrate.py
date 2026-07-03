#!/usr/bin/env python3
"""Risk-controlled threshold calibration for safety-monitor.

Per-loop tau (score >= tau -> quarantine), recomputed from Giles's
approve/deny labels once enough exist. See ../ARCHITECTURE.md.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "safety-monitor"
CALIBRATION_FILE = STATE_DIR / "calibration.jsonl"
TAU_FILE = STATE_DIR / "tau.json"

DEFAULT_TAU = 0.3       # conservative: used until enough labeled data exists
TARGET_RISK = 0.05      # max tolerated false-accept rate among labeled-bad rows
MIN_LABELS = 20


def _read_calibration_rows(loop_name: str) -> list[dict]:
    if not CALIBRATION_FILE.exists():
        return []
    rows = []
    for line in CALIBRATION_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("loop") == loop_name:
            rows.append(row)
    return rows


def record_label(loop_name: str, score: float, label: int) -> None:
    """label: 0 = approved (was actually fine), 1 = denied (was actually bad).

    Intended caller: the quarantine review workflow, once built — this is
    what lets calibrate() improve over time instead of being stuck on
    DEFAULT_TAU forever.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    row = {"loop": loop_name, "score": score, "label": label}
    with CALIBRATION_FILE.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _write_tau(loop_name: str, tau: float) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if TAU_FILE.exists():
        try:
            data = json.loads(TAU_FILE.read_text())
        except json.JSONDecodeError:
            data = {}
    data[loop_name] = tau
    TAU_FILE.write_text(json.dumps(data, indent=2))


def calibrate(loop_name: str, target_risk: float = TARGET_RISK,
              min_labels: int = MIN_LABELS) -> float:
    """Smallest tau such that the false-accept rate on labeled-bad rows <= target_risk.

    False-accept = a labeled-bad (label=1) row whose score was < tau (i.e. it
    would have shipped instead of being quarantined). Falls back to
    DEFAULT_TAU until there are at least `min_labels` rows for this loop.
    """
    rows = _read_calibration_rows(loop_name)
    if len(rows) < min_labels:
        return DEFAULT_TAU

    bad = [r for r in rows if r["label"] == 1]
    if not bad:
        return DEFAULT_TAU  # nothing bad labeled yet — no basis to tighten

    for tau in sorted({r["score"] for r in rows}):
        false_accept_rate = sum(1 for r in bad if r["score"] < tau) / len(bad)
        if false_accept_rate <= target_risk:
            _write_tau(loop_name, tau)
            return tau

    _write_tau(loop_name, 1.0)
    return 1.0  # nothing passes if no threshold hits the bound


def get_tau(loop_name: str) -> float:
    """Fast path for verify.py: use the cached tau if present, else calibrate."""
    if TAU_FILE.exists():
        try:
            data = json.loads(TAU_FILE.read_text())
            if loop_name in data:
                return data[loop_name]
        except json.JSONDecodeError:
            pass
    return calibrate(loop_name)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: calibrate.py <loop_name>", file=sys.stderr)
        sys.exit(1)
    name = sys.argv[1]
    tau = calibrate(name)
    print(f"tau({name}) = {tau:.2f}  ({len(_read_calibration_rows(name))} labeled rows)")
