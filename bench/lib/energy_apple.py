"""Measure power consumption on Apple silicon using powermetrics.

Runs powermetrics alongside a subprocess and measures CPU/GPU/ANE power in joules.
"""
from __future__ import annotations
import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class EnergyMeasure:
    """Result of energy measurement."""
    joules: float  # total energy in joules
    wh: float  # energy in watt-hours
    duration_s: float  # wall time in seconds

    def to_dict(self) -> dict:
        return {
            "joules": self.joules,
            "wh": self.wh,
            "duration_s": self.duration_s,
        }


def measure_subprocess(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int | None = None,
) -> tuple[int, EnergyMeasure | None, str]:
    """Run a subprocess while measuring power with powermetrics.

    Returns (exit_code, energy_measure, error_reason).
    energy_measure is None if sampling couldn't be started; error_reason explains why.
    """
    # Check if powermetrics is available
    try:
        result = subprocess.run(
            ["which", "powermetrics"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return -1, None, "powermetrics not found in PATH"
    except Exception as e:
        return -1, None, f"powermetrics check failed: {e}"

    # Start powermetrics sampling in the background
    # We need to sample and redirect to a file for later parsing
    power_samples: list[dict] = []
    power_lock = threading.Lock()
    power_error: list[str] = []

    def sample_power():
        """Background thread to collect power samples."""
        try:
            # Run powermetrics with JSON output; this requires sudo
            proc = subprocess.Popen(
                ["sudo", "powermetrics", "-n", "1", "-f", "json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            for line in iter(proc.stdout.readline, ""):
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                    with power_lock:
                        power_samples.append(sample)
                except json.JSONDecodeError:
                    continue

            proc.terminate()
            proc.wait(timeout=5)
        except Exception as e:
            with power_lock:
                power_error.append(str(e))

    power_thread = threading.Thread(target=sample_power, daemon=True)
    power_thread.start()

    # Give powermetrics a moment to start
    time.sleep(0.5)

    start = time.time()
    try:
        result = subprocess.run(cmd, cwd=cwd, timeout=timeout, capture_output=False)
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        exit_code = -1
    except Exception as e:
        return -1, None, f"subprocess failed: {e}"
    finally:
        duration = time.time() - start
        # powermetrics thread will exit when powermetrics process terminates

    # Wait for power sampling to finish
    power_thread.join(timeout=5)

    if power_error:
        return exit_code, None, "; ".join(power_error)

    if not power_samples:
        return exit_code, None, "no power samples collected (sudo required)"

    # Parse power samples and sum energy
    total_joules = 0.0
    try:
        for sample in power_samples:
            # Powermetrics JSON format varies; look for cpu_power, gpu_power, etc.
            cpu_w = sample.get("processor", {}).get("cpu_power", 0)
            gpu_w = sample.get("processor", {}).get("gpu_power", 0)
            total_w = cpu_w + gpu_w
            # Assuming 1 sample per second (powermetrics default)
            total_joules += total_w * 1.0
    except Exception as e:
        return exit_code, None, f"power parse failed: {e}"

    wh = total_joules / 3600.0
    energy = EnergyMeasure(joules=total_joules, wh=wh, duration_s=duration)
    return exit_code, energy, ""
