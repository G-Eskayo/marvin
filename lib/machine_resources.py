#!/usr/bin/env python3
"""Live per-machine resources monitoring: disk/mem/swap/CPU/GPU with 30s cadence.

Phase 1 of ticket #130. Collects resource metrics locally every 30s, appends to
~/.claude/logs/machine-resources.<device_id>.jsonl, trims to 24h rolling window.
No SSH: collector runs locally only. Cross-machine visibility via existing
~/.claude sync layer: dashboard reads both machines' files off local disk.

Reachability (asleep/unreachable) comes from existing health:status() channel.
Asleep/unreachable is not re-derived here; staleness (no sample in 2+ intervals)
is a secondary signal for greying out numbers, not for classification.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402

HOME = Path.home()
RESOURCES_LOG_DIR = HOME / ".claude" / "logs"
RESOURCES_LOG_SUFFIX = ".jsonl"

# Sample interval (seconds): how often the launchd job runs
SAMPLE_INTERVAL = 30

# 24-hour window: trim to last N entries (assume ~2880 samples/day at 30s intervals)
MAX_SAMPLES_PER_24H = 2880

# Stale threshold: after N intervals of silence, considered stale (for UI opacity)
STALE_INTERVALS = 2


def _resource_sample_script() -> str:
    """The one script that samples resources, run locally on each machine.

    Outputs key=value lines. Used by parse_resources() to extract metrics.
    All paths absolute (launchd PATHs omit homebrew /opt/homebrew/bin).
    """
    return r'''
# Timestamp
echo "timestamp=$(date -u +%s)"

# Memory pressure (all in pages; macOS PageSize=4096)
if /usr/bin/memory_pressure 2>/dev/null | /usr/bin/grep -q "System-wide memory"; then
  echo "mem_pressure=$(/usr/bin/memory_pressure 2>/dev/null | /usr/bin/grep "System-wide memory" | /usr/bin/awk '{print $NF}' | /usr/bin/sed 's/%//')"
else
  echo "mem_pressure="
fi

# Swap usage: vm.swapusage outputs "total = 100M  used = 50M  free = 50M  (encrypted)"
SWAPUSAGE=$(/usr/sbin/sysctl -n vm.swapusage 2>/dev/null || echo "")
if [ -n "$SWAPUSAGE" ]; then
  SWAP_TOTAL=$(/bin/echo "$SWAPUSAGE" | /usr/bin/awk '{print $3}' | /usr/bin/sed 's/M$//')
  SWAP_USED=$(/bin/echo "$SWAPUSAGE" | /usr/bin/awk '{print $8}' | /usr/bin/sed 's/M$//')
  if [ -n "$SWAP_TOTAL" ] && [ "$SWAP_TOTAL" != "0" ]; then
    echo "swap_pct=$(/usr/bin/awk "BEGIN {printf \"%.0f\", 100.0 * $SWAP_USED / $SWAP_TOTAL}")"
  else
    echo "swap_pct=0"
  fi
else
  echo "swap_pct="
fi

# CPU usage: top -l 1 -n 1 outputs CPU % on the second line
CPU_LINE=$(top -l 1 -n 1 2>/dev/null | /usr/bin/head -2 | /usr/bin/tail -1 | /usr/bin/grep -oE '[0-9.]+%' | /usr/bin/head -1)
if [ -n "$CPU_LINE" ]; then
  echo "cpu_pct=${CPU_LINE%?}"
else
  echo "cpu_pct="
fi

# GPU: ioreg -r for AGXAccelerator (Apple Silicon GPU) or other GPU classes.
# The entry looks like: | | +-o ACIO@0  <class ACIO>
# Try to extract GPU utilization; if not available, report None.
GPU_UTIL=$(/usr/sbin/ioreg -r -l -d 1 -c AGXAccelerator 2>/dev/null | /usr/bin/grep -i "utilization" | /usr/bin/grep -oE '[0-9]+' | /usr/bin/tail -1)
if [ -n "$GPU_UTIL" ]; then
  echo "gpu_pct=$GPU_UTIL"
else
  echo "gpu_pct="
fi

# Disk free/total
/bin/df -k "$HOME" | /usr/bin/awk 'NR==2 {
  total=$2; free=$4
  printf "disk_total_kb=%d\n", total
  printf "disk_free_kb=%d\n", free
  if (total > 0) printf "disk_pct=%.0f\n", 100.0 * free / total
}'
'''


def parse_resources(text: str, tz: timezone | None = None) -> dict:
    """Parse resource sample output into a dict.

    Handles:
    - Empty/missing fields (returns None)
    - Truncated output (skips bad lines, doesn't raise)
    - Malformed numeric fields (skips, doesn't crash)
    - Trailing whitespace / wrapped fields (robust split)

    Returns: {
      'timestamp': int (epoch seconds) or None,
      'mem_pressure': float (0-100%) or None,
      'swap_pct': float (0-100%) or None,
      'cpu_pct': float (0-100%) or None,
      'gpu_pct': float (0-100%) or None,
      'disk_free_kb': int or None,
      'disk_total_kb': int or None,
      'disk_pct': float (0-100%) or None,
    }
    """
    tz = tz or timezone.utc
    raw = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        try:
            key, val = line.split("=", 1)
            raw[key.strip()] = val.strip()
        except ValueError:
            continue

    def float_or_none(key):
        v = raw.get(key, "").strip()
        try:
            return float(v) if v else None
        except ValueError:
            return None

    def int_or_none(key):
        v = raw.get(key, "").strip()
        try:
            return int(v) if v else None
        except ValueError:
            return None

    ts = int_or_none("timestamp")
    return {
        "timestamp": ts,
        "timestamp_iso": datetime.fromtimestamp(ts, tz=tz).isoformat() if ts else None,
        "mem_pressure": float_or_none("mem_pressure"),
        "swap_pct": float_or_none("swap_pct"),
        "cpu_pct": float_or_none("cpu_pct"),
        "gpu_pct": float_or_none("gpu_pct"),
        "disk_free_kb": int_or_none("disk_free_kb"),
        "disk_total_kb": int_or_none("disk_total_kb"),
        "disk_pct": float_or_none("disk_pct"),
    }


def sample_now(device_id: str | None = None, run=subprocess.run) -> dict:
    """Capture one resource sample on this machine (local only, no SSH).

    Returns parsed resources dict. On error (timeout, command fails),
    returns dict with all None values, never raises.
    """
    device_id = device_id or machine_profile.registry_id()
    script = _resource_sample_script()
    try:
        proc = run(["bash", "-s"], input=script, capture_output=True, text=True, timeout=10)
        return parse_resources(proc.stdout)
    except Exception:
        return {
            "timestamp": None,
            "timestamp_iso": None,
            "mem_pressure": None,
            "swap_pct": None,
            "cpu_pct": None,
            "gpu_pct": None,
            "disk_free_kb": None,
            "disk_total_kb": None,
            "disk_pct": None,
        }


def append_sample(sample: dict, device_id: str | None = None, path: Path | None = None) -> None:
    """Append one sample to the JSONL history file, trim to 24h.

    Same-file writes are atomic via rename. Handles missing log dir.
    """
    device_id = device_id or machine_profile.registry_id()
    path = path or (RESOURCES_LOG_DIR / f"machine-resources.{device_id}{RESOURCES_LOG_SUFFIX}")

    path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing entries
    existing = []
    if path.exists():
        try:
            for line in path.read_text().splitlines():
                if line.strip():
                    try:
                        existing.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # Skip malformed lines
        except OSError:
            existing = []

    # Add new sample
    entry = {
        "timestamp": sample.get("timestamp"),
        "timestamp_iso": sample.get("timestamp_iso"),
        "mem_pressure": sample.get("mem_pressure"),
        "swap_pct": sample.get("swap_pct"),
        "cpu_pct": sample.get("cpu_pct"),
        "gpu_pct": sample.get("gpu_pct"),
        "disk_free_kb": sample.get("disk_free_kb"),
        "disk_total_kb": sample.get("disk_total_kb"),
        "disk_pct": sample.get("disk_pct"),
    }
    existing.append(entry)

    # Trim to 24h: keep last N entries
    cutoff_idx = max(0, len(existing) - MAX_SAMPLES_PER_24H)
    trimmed = existing[cutoff_idx:]

    # Write atomically (write to temp, rename)
    temp_path = path.with_suffix(".tmp")
    try:
        temp_path.write_text("\n".join(json.dumps(e) for e in trimmed) + "\n")
        temp_path.replace(path)
    except OSError:
        pass  # Silently fail if unwritable (log dir missing after mkdir failed, etc)


def read_samples(device_id: str | None = None, path: Path | None = None) -> list[dict]:
    """Read all samples from the JSONL history file.

    Returns list of sample dicts, oldest first. Empty list if file doesn't exist.
    Skips malformed lines.
    """
    device_id = device_id or machine_profile.registry_id()
    path = path or (RESOURCES_LOG_DIR / f"machine-resources.{device_id}{RESOURCES_LOG_SUFFIX}")

    if not path.exists():
        return []

    samples = []
    try:
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return samples


def is_stale(samples: list[dict]) -> bool:
    """True if the most recent sample is older than (SAMPLE_INTERVAL * STALE_INTERVALS) seconds."""
    if not samples:
        return True
    latest = samples[-1]
    ts = latest.get("timestamp")
    if ts is None:
        return True
    age_s = time.time() - ts
    return age_s > SAMPLE_INTERVAL * STALE_INTERVALS


if __name__ == "__main__":
    # Standalone: capture one sample and append to history
    device = machine_profile.registry_id()
    sample = sample_now(device)
    if sample.get("timestamp"):
        append_sample(sample, device)
        print(f"Sampled {device}: {sample.get('disk_pct'):.0f}% disk free")
