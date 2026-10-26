"""Energy sampling via Apple's powermetrics tool.

Samples CPU/GPU/ANE power consumption for a subprocess's duration and
integrates watts × wall-seconds → joules. Gracefully handles missing
passwordless sudo by probing `sudo -n true` before invoking the binary.

Usage:
    with PowerSampler() as sampler:
        subprocess.run(["some-command"], ...)
    joules = sampler.joules()
    # Returns float joules, or None if unavailable/error
"""
from __future__ import annotations
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))


class PowerSampler:
    """Context manager for sampling power via Apple's powermetrics.

    Wraps a subprocess and measures its energy consumption. Returns None
    if passwordless sudo isn't configured, the binary is missing, or the
    output is malformed.
    """

    def __init__(self, interval_ms: int = 100):
        self.interval_ms = interval_ms
        self.t0: float | None = None
        self.t1: float | None = None
        self.has_sudo: bool | None = None
        self.power_samples: list[dict] = []
        self.error: str | None = None
        self.pmeter_proc: subprocess.Popen | None = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def start(self) -> None:
        """Start timing and probe sudo. Launch powermetrics if available."""
        self.t0 = time.time()
        self._probe_sudo()
        if self.has_sudo:
            self._start_powermetrics()

    def stop(self) -> None:
        """Stop timing. Terminate and collect powermetrics samples if running."""
        self.t1 = time.time()
        if self.pmeter_proc is not None:
            self._stop_powermetrics()

    def _probe_sudo(self) -> None:
        """Check if passwordless sudo is available. Must complete quickly."""
        try:
            result = subprocess.run(
                ["sudo", "-n", "true"],
                capture_output=True,
                timeout=2,
                text=True,
            )
            self.has_sudo = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            self.has_sudo = False
            self.error = str(e)

    def _start_powermetrics(self) -> None:
        """Start powermetrics subprocess. Runs concurrently with the measured task."""
        # Start with a large sample count; we'll terminate early in stop()
        # Interval is passed via -i (in ms)
        try:
            self.pmeter_proc = subprocess.Popen(
                ["sudo", "-n", "powermetrics",
                 "-n", "1000",  # Large count; we kill it early
                 "-i", str(self.interval_ms),
                 "--samplers", "cpu_power,gpu_power,ane_power",
                 "-o", "plist"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            self.error = "powermetrics binary not found"
            self.pmeter_proc = None
        except Exception as e:
            self.error = f"failed to start powermetrics: {e}"
            self.pmeter_proc = None

    def _stop_powermetrics(self) -> None:
        """Terminate powermetrics and collect output."""
        if self.pmeter_proc is None:
            return

        try:
            # Give it a moment to write final samples, then terminate
            self.pmeter_proc.terminate()
            stdout_data, stderr_data = self.pmeter_proc.communicate(timeout=5)
            if self.pmeter_proc.returncode is None:
                self.pmeter_proc.kill()
                self.pmeter_proc.wait(timeout=2)
            if stdout_data:
                self._parse_plist(stdout_data)
            if self.pmeter_proc.returncode not in (0, -15):  # -15 is SIGTERM
                self.error = f"powermetrics exited {self.pmeter_proc.returncode}"
        except subprocess.TimeoutExpired:
            if self.pmeter_proc.poll() is None:
                self.pmeter_proc.kill()
            self.error = "powermetrics termination timeout"
        except Exception as e:
            self.error = f"error collecting powermetrics output: {e}"

    def _parse_plist(self, data: bytes) -> None:
        """Parse powermetrics plist output (NUL-separated plists per sample)."""
        if not data:
            return

        try:
            # powermetrics outputs one NUL-separated plist per sample
            samples = data.split(b'\x00')
            for sample_bytes in samples:
                if not sample_bytes.strip():
                    continue
                try:
                    plist = plistlib.loads(sample_bytes)
                    if isinstance(plist, dict):
                        self.power_samples.append(plist)
                except Exception:
                    # Skip malformed individual samples
                    pass
        except Exception as e:
            self.error = f"plist parse error: {e}"

    def joules(self) -> float | None:
        """Compute integrated energy in joules (watts × seconds).

        Returns None if passwordless sudo wasn't available, the binary is
        missing, or sampling failed. Otherwise returns a float >= 0.
        """
        if self.has_sudo is False or self.error or not self.power_samples:
            return None

        if self.t0 is None or self.t1 is None:
            return None

        wall_s = self.t1 - self.t0
        if wall_s <= 0:
            return 0.0

        # Integrate power readings: sum watts from each sample
        total_watts = 0.0
        for sample in self.power_samples:
            # powermetrics plist keys: cpu_power, gpu_power, ane_power (in watts)
            watts = 0.0
            for key in ("cpu_power", "gpu_power", "ane_power"):
                if key in sample:
                    val = sample[key]
                    if isinstance(val, (int, float)):
                        watts += val
            total_watts += watts

        # Average power × duration = energy in joules
        if not self.power_samples:
            return None
        avg_watts = total_watts / len(self.power_samples)
        return avg_watts * wall_s
