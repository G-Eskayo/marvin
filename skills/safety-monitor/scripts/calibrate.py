#!/usr/bin/env python3
"""Risk-controlled threshold calibration for safety-monitor.

Per-loop tau (score >= tau -> quarantine), recomputed from the owner's
approve/deny labels. See ../ARCHITECTURE.md.

Shared across machines (decided 2026-10-26): every Mac's review answers are
recorded into ONE calibration file on the primary host (shared_labels.py
delivers them; a Mac that can't reach it queues them). Tau is computed per
loop once that loop has MIN_LABELS labels; until then the loop uses the
global tau (all loops' labels together, once those reach MIN_LABELS), and
until then DEFAULT_TAU. Every recorded label recomputes the whole tau map
(G-Eskayo/marvin#599: it used to be cached once and never move).
"""
from __future__ import annotations
import fcntl
import json
import math
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "safety-monitor"
CALIBRATION_FILE = STATE_DIR / "calibration.jsonl"
TAU_FILE = STATE_DIR / "tau.json"

DEFAULT_TAU = 0.3       # conservative: used until enough labeled data exists
TARGET_RISK = 0.05      # max tolerated false-accept rate among labeled-bad rows
MIN_LABELS = 20         # per loop, and for the global fallback
GLOBAL = "*"            # tau.json key for the all-loops tau (never a valid loop name)
LOOP_RE = re.compile(r"^[a-z0-9_]{1,64}$")
ENTRY_ID_RE = re.compile(r"^[0-9a-f]{16}$")
NOTE_CAP = 1_000


def _rows() -> list[dict]:
    """Every well-formed row; a malformed line is skipped, never raised."""
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
        if (isinstance(row, dict) and isinstance(row.get("loop"), str) and row.get("label") in (0, 1)
                and isinstance(row.get("score"), (int, float)) and not isinstance(row.get("score"), bool)):
            rows.append(row)
    return rows


def _read_calibration_rows(loop_name: str) -> list[dict]:
    return [r for r in _rows() if r["loop"] == loop_name]


@contextmanager
def _locked():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(STATE_DIR / ".calibration.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def valid_label(loop_name, score, label, note=None, entry_id=None) -> str | None:
    """Why this label can't be recorded, or None. Labels arrive over the network from other Macs: checked here."""
    if not isinstance(loop_name, str) or not LOOP_RE.match(loop_name):
        return "loop"
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
        return "score"
    if label not in (0, 1) or isinstance(label, bool):
        return "label"
    if note is not None and (not isinstance(note, str) or len(note) > NOTE_CAP or "\n" in note):
        return "note"
    if entry_id is not None and (not isinstance(entry_id, str) or not ENTRY_ID_RE.match(entry_id)):
        return "entry_id"
    return None


def record_label(loop_name: str, score: float, label: int, note: str | None = None,
                 entry_id: str | None = None) -> bool:
    """label: 0 = approved (was actually fine), 1 = denied (was actually bad).
    note: the reviewer's "modify" text, kept with the label so a typed correction is never thrown away.
    entry_id: the quarantine entry's hash; a second answer for the same entry (two Macs, or a re-delivery) is
    ignored. Returns True if recorded, False for a duplicate. Recomputes the tau map after recording.
    """
    why = valid_label(loop_name, score, label, note, entry_id)
    if why:
        raise ValueError(f"invalid label: {why}")
    with _locked():
        if entry_id and any(r.get("entry_id") == entry_id for r in _rows()):
            return False
        row = {"loop": loop_name, "score": float(score), "label": label}
        if note:
            row["note"] = note
        if entry_id:
            row["entry_id"] = entry_id
        with CALIBRATION_FILE.open("a") as f:
            f.write(json.dumps(row) + "\n")
        recalibrate_all()
    return True


def _risk_controlled(rows: list[dict], target_risk: float) -> float:
    """The LARGEST tau whose false-accept rate on labeled-bad rows stays <= target_risk, never below DEFAULT_TAU.

    False-accept = a labeled-bad row whose score is < tau (it would have shipped). The rate only grows with tau, so
    the largest feasible candidate is found scanning down. The old code scanned up and returned the first (smallest)
    candidate, which is always feasible: tau was pinned to the lowest labeled score (#599). Clamped at DEFAULT_TAU:
    labels only come from quarantined items, so there is no evidence about scores under the old threshold.
    """
    bad = [r for r in rows if r["label"] == 1]
    if not bad:
        return DEFAULT_TAU  # nothing bad labeled yet: no basis to move
    for tau in sorted({float(r["score"]) for r in rows} | {1.0}, reverse=True):
        if sum(1 for r in bad if r["score"] < tau) / len(bad) <= target_risk:
            return max(DEFAULT_TAU, tau)
    return 1.0  # unreachable with any bad row (the lowest candidate always passes); kept as the safe answer


def tau_map(rows: list[dict] | None = None, target_risk: float = TARGET_RISK, min_labels: int = MIN_LABELS) -> dict:
    """{GLOBAL: tau, loop: tau, ...} for every loop with labels. A loop under min_labels gets the global tau; the
    global tau is DEFAULT_TAU until all loops together have min_labels."""
    rows = _rows() if rows is None else rows
    glob = _risk_controlled(rows, target_risk) if len(rows) >= min_labels else DEFAULT_TAU
    out = {GLOBAL: glob}
    for loop in sorted({r["loop"] for r in rows}):
        mine = [r for r in rows if r["loop"] == loop]
        out[loop] = _risk_controlled(mine, target_risk) if len(mine) >= min_labels else glob
    return out


def _write_taus(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, prefix=".tau.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, TAU_FILE)


def recalibrate_all() -> dict:
    data = tau_map()
    _write_taus(data)
    print(f"[calibrate] tau now {json.dumps(data, sort_keys=True)}", file=sys.stderr)
    return data


def calibrate(loop_name: str, target_risk: float = TARGET_RISK, min_labels: int = MIN_LABELS) -> float:
    """This loop's tau from the labels now on disk (see tau_map), and rewrites tau.json."""
    data = tau_map(target_risk=target_risk, min_labels=min_labels)
    _write_taus(data)
    return data.get(loop_name, data[GLOBAL])


def read_taus() -> dict:
    try:
        data = json.loads(TAU_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return {k: float(v) for k, v in data.items() if isinstance(k, str) and isinstance(v, (int, float))
            and not isinstance(v, bool) and 0 <= v <= 1} if isinstance(data, dict) else {}


def store_taus(data) -> dict:
    """A tau map from the primary host (shared_labels.sync), checked and cached locally."""
    clean = {k: float(v) for k, v in (data or {}).items() if isinstance(k, str) and (k == GLOBAL or LOOP_RE.match(k))
             and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1} if isinstance(data, dict) else {}
    if clean:
        _write_taus(clean)
    return clean


def get_tau(loop_name: str) -> float:
    """Fast path for verify.py: the cached map (rewritten on every label), this loop's tau, else the global one, else
    DEFAULT_TAU. An unknown loop gets the global tau."""
    data = read_taus()
    return data.get(loop_name, data.get(GLOBAL, DEFAULT_TAU))


def _cli(argv: list[str]) -> int:
    if argv[:1] == ["record"] and len(argv) == 2:
        # The primary host's webhook hands one delivered label here (shared_labels.py sends it): JSON in, JSON out.
        try:
            p = json.loads(argv[1])
            ok = record_label(p.get("loop"), p.get("score"), p.get("label"), p.get("note"), p.get("entry_id"))
            print(json.dumps({"ok": True, "recorded": ok, "taus": read_taus()}))
        except (ValueError, AttributeError, TypeError) as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        return 0
    if argv[:1] == ["taus"]:
        print(json.dumps(read_taus() or tau_map()))
        return 0
    if len(argv) != 1:
        print("usage: calibrate.py <loop_name> | record '<json>' | taus", file=sys.stderr)
        return 1
    name = argv[0]
    tau = calibrate(name)
    print(f"tau({name}) = {tau:.2f}  ({len(_read_calibration_rows(name))} labeled rows)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
