#!/usr/bin/env python3
"""energy_apple.py — power sampling on macOS via powermetrics (requires sudo).

EnergySampler is a context manager that measures CPU+GPU energy consumption
during a code block's execution by wrapping powermetrics subprocess.
Degrades gracefully to None + reason when sudo is unavailable.
"""
from __future__ import annotations
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


class EnergySampler:
    """Context manager for measuring energy via powermetrics subprocess.

    Usage:
        sampler = EnergySampler()
        with sampler:
            # code to measure
            pass
        result = sampler.get_energy()  # {"energy_j": 123.45} or {"energy_j": None, "reason": "..."}
    """

    def __init__(self):
        self.energy_j = None
        self.reason = None
        self.proc = None
        self.t0 = None
        self.output = None

    def __enter__(self):
        """Start powermetrics subprocess."""
        # Start powermetrics sampling with passwordless sudo (-n prevents password prompt)
        # No -n flag: sample continuously until process exits, integrate over all samples.
        try:
            self.t0 = time.time()
            self.proc = subprocess.Popen(
                ["sudo", "-n", "/usr/bin/powermetrics", "--samplers", "cpu_power,gpu_power"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            self.reason = "powermetrics not found (shipped with macOS, already installed)"
            return self
        except Exception as e:
            self.reason = f"powermetrics failed to start: {e}"
            return self

        return self

    def __exit__(self, *args):
        """Stop powermetrics and parse output."""
        if self.proc is None:
            # Sampler was never started; energy remains None with reason already set
            return

        try:
            stdout, stderr = self.proc.communicate(timeout=10)
            self.output = stdout
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.reason = "powermetrics timeout"
            return
        except Exception as e:
            self.reason = f"powermetrics subprocess error: {e}"
            return

        # Check if sudo was denied (returncode != 0 and stderr indicates permission error)
        if self.proc.returncode != 0:
            if "not allowed" in stderr or "permission denied" in stderr.lower():
                self.reason = "sudo passwordless not configured; configure with: echo '$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/powermetrics' | sudo tee /etc/sudoers.d/powermetrics"
            else:
                self.reason = f"powermetrics exited with code {self.proc.returncode}: {stderr[:100]}"
            return

        # Parse power samples and integrate to joules
        try:
            self.energy_j = self._parse_and_integrate(stdout)
        except Exception as e:
            self.reason = f"power parsing failed: {e}"

    def _parse_and_integrate(self, output: str) -> float | None:
        """Parse powermetrics output and integrate power samples to energy (joules).

        powermetrics outputs lines like:
            CPU Power: 1234 mW
            GPU Power: 567 mW
        We sum CPU + GPU power each sample, then integrate over wall-clock time.
        Returns joules, or None if no valid samples found.
        """
        lines = output.split("\n")
        cpu_power = None
        gpu_power = None
        power_samples = []  # List of total watts (CPU + GPU) per sample

        for line in lines:
            # Match "CPU Power: 1234 mW" or "GPU Power: 567 mW"
            m = re.search(r"(CPU|GPU) Power:\s*(\d+)\s*mW", line)
            if m:
                watts = int(m.group(2)) / 1000.0  # Convert mW to W
                if m.group(1) == "CPU":
                    cpu_power = watts
                else:  # GPU
                    gpu_power = watts

                # When we have both CPU and GPU, sum them as one sample
                if cpu_power is not None and gpu_power is not None:
                    power_samples.append(cpu_power + gpu_power)
                    cpu_power = None
                    gpu_power = None

        if not power_samples:
            return None

        # Simple integration: average power × wall-clock time
        # powermetrics with "-n 1" gives one sample; with "-n 5" gives multiple
        avg_power_w = sum(power_samples) / len(power_samples)
        wall_time_s = time.time() - self.t0 if self.t0 else 0

        if wall_time_s <= 0:
            return None

        energy_j = avg_power_w * wall_time_s
        return energy_j

    def get_energy(self) -> dict:
        """Return energy measurement result: {"energy_j": float|None, "reason": str|None}."""
        result = {"energy_j": self.energy_j}
        if self.reason:
            result["reason"] = self.reason
        return result
