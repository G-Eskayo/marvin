"""energy_apple.py — PowerMetrics sampling for Apple Silicon energy measurement.

Wraps `powermetrics --samplers cpu_power,gpu_power` in a background subprocess.
Integrates power samples to compute joules. Returns None on any failure rather than raising.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from typing import Any


# Default sample interval for powermetrics (1 second)
POWERMETRICS_SAMPLE_INTERVAL = 1.0


def start_sampling() -> dict[str, Any] | None:
    """Start background powermetrics sampling subprocess.

    Returns:
        dict with "process" handle and "start_time", or None on failure.
        Never raises.
    """
    if shutil.which("powermetrics") is None:
        return None

    try:
        # Use SUDO_ASKPASS with /bin/false to prevent password prompts
        proc = subprocess.Popen(
            ["sudo", "-n", "powermetrics", "--samplers", "cpu_power,gpu_power", "-n", "100"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        return {
            "process": proc,
            "start_time": time.time(),
        }
    except (PermissionError, FileNotFoundError, OSError):
        return None


def stop_sampling(handle: dict[str, Any] | None) -> dict | None:
    """Stop powermetrics subprocess and extract energy data.

    Args:
        handle: dict from start_sampling(), or None.

    Returns:
        dict with energy stats (e.g., {"joules": 123.45})
        or None if handle is None or parsing fails.
        Never raises.
    """
    if handle is None:
        return None

    proc = handle.get("process")
    start_time = handle.get("start_time")

    if proc is None:
        return None

    try:
        # Terminate and wait for process to finish
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, Exception):
        # Force kill if terminate didn't work
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
        return None

    # Parse powermetrics output for power samples
    # Real output looks like: "CPU Power: 5234 mW" and "GPU Power: 145 mW" (milliwatts)
    # or "CPU Power: 5.23 W" and "GPU Power: 1.45 W" (watts)
    try:
        cpu_powers = []
        gpu_powers = []

        for line in stdout.split("\n"):
            line = line.strip()
            # Match "CPU Power: X.XX W" or "CPU Power: X.XX mW"
            cpu_match = re.search(r"CPU Power:\s*([\d.]+)\s*(mW|W)", line)
            if cpu_match:
                value = float(cpu_match.group(1))
                unit = cpu_match.group(2)
                # Convert mW to W
                if unit == "mW":
                    value = value / 1000.0
                cpu_powers.append(value)

            # Match "GPU Power: X.XX W" or "GPU Power: X.XX mW"
            gpu_match = re.search(r"GPU Power:\s*([\d.]+)\s*(mW|W)", line)
            if gpu_match:
                value = float(gpu_match.group(1))
                unit = gpu_match.group(2)
                # Convert mW to W
                if unit == "mW":
                    value = value / 1000.0
                gpu_powers.append(value)

        # No samples collected
        if not cpu_powers:
            return None

        # Integrate power over time to get energy
        # Energy (J) = Power (W) * Time (s)
        # Assuming each sample is POWERMETRICS_SAMPLE_INTERVAL apart
        elapsed = time.time() - start_time
        num_samples = len(cpu_powers)

        # Average power per component
        avg_cpu_power = sum(cpu_powers) / len(cpu_powers) if cpu_powers else 0
        avg_gpu_power = sum(gpu_powers) / len(gpu_powers) if gpu_powers else 0

        # Total energy = average power * elapsed time
        total_energy = (avg_cpu_power + avg_gpu_power) * elapsed

        return {
            "joules": round(total_energy, 2),
            "samples": num_samples,
            "elapsed_s": round(elapsed, 1),
            "avg_cpu_power_w": round(avg_cpu_power, 2),
            "avg_gpu_power_w": round(avg_gpu_power, 2),
        }
    except (ValueError, AttributeError, IndexError):
        return None
