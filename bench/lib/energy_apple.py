#!/usr/bin/env python3
"""macOS energy telemetry via powermetrics sampler.

Usage:
    sampler = ApplePowermetricsSampler()
    sampler.start()
    # do work...
    joules = sampler.stop_and_measure()

The sampler runs `powermetrics` in the background, sampling power draw,
and converts the samples to total energy (Joules) when stopped.
Requires passwordless sudo or explicit credentials for /usr/bin/powermetrics.
"""
from __future__ import annotations
import json
import logging
import re
import signal
import subprocess
import time
from pathlib import Path

_LOG = logging.getLogger(__name__)


class ApplePowermetricsSampler:
    """Samples macOS power draw and computes total energy."""

    def __init__(self, interval_ms: int = 500):
        """
        interval_ms: sampling interval for powermetrics (milliseconds).
        """
        self.interval_ms = interval_ms
        self.process = None
        self._output_lines = []
        self._start_time = None
        self._available = None

    def start(self) -> bool:
        """Start the sampler. Returns True if started successfully, False if unavailable.

        Returns:
            bool: True if sampler started, False if sudo password needed or tool unavailable.
        """
        if self.process is not None:
            raise RuntimeError("Sampler already running")

        # Check if powermetrics is available and can run without password
        if not self._check_available():
            _LOG.warning("powermetrics not available passwordless on this machine")
            return False

        # Kill any stray powermetrics from a prior crashed run
        try:
            subprocess.run(
                ["sudo", "pkill", "-f", "[p]owermetrics"],
                capture_output=True,
                timeout=5,
            )
            time.sleep(0.5)
        except Exception as e:
            _LOG.warning(f"Failed to clean up stray powermetrics: {e}")

        # Start powermetrics in the background
        try:
            self.process = subprocess.Popen(
                ["sudo", "/usr/bin/powermetrics", "-s", "cpu_power", "-n", "10000"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._output_lines = []
            self._start_time = time.time()
            _LOG.info(f"powermetrics sampler started (PID {self.process.pid})")
            return True
        except Exception as e:
            _LOG.error(f"Failed to start powermetrics: {e}")
            self.process = None
            return False

    def stop_and_measure(self) -> dict | None:
        """Stop the sampler and compute energy (Joules) from power samples.

        Returns:
            dict with keys:
                - available: False if sampler never ran (no passwordless sudo)
                - joules: total energy in Joules (only if available=True)
                - samples: number of power samples collected
                - wall_s: wall time from start to stop
                - error: str if measurement failed
            or None if sampler was never started
        """
        if self.process is None:
            return None

        wall_s = time.time() - self._start_time

        # Stop the process
        try:
            self.process.terminate()
            stdout, stderr = self.process.communicate(timeout=5)
            self._output_lines = stdout.splitlines() if stdout else []
        except subprocess.TimeoutExpired:
            self.process.kill()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _LOG.error("powermetrics would not terminate")
                self.process = None
                return {
                    "available": True,
                    "joules": 0.0,
                    "samples": 0,
                    "wall_s": wall_s,
                    "error": "process_killed_forcefully",
                }
            self._output_lines = []
        finally:
            self.process = None

        # Parse output and compute energy
        return self._compute_energy(self._output_lines, wall_s)

    def _check_available(self) -> bool:
        """Check if powermetrics can run without a password prompt."""
        if self._available is not None:
            return self._available

        try:
            # Try a single sample with a timeout
            result = subprocess.run(
                ["sudo", "-n", "/usr/bin/powermetrics", "-s", "cpu_power", "-n", "1"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            self._available = result.returncode == 0 or "password" not in (
                result.stderr + result.stdout
            ).lower()
        except subprocess.TimeoutExpired:
            self._available = False
        except Exception as e:
            _LOG.warning(f"Failed to check powermetrics availability: {e}")
            self._available = False

        return self._available

    def _compute_energy(self, output_lines: list[str], wall_s: float) -> dict:
        """Parse powermetrics output and compute total energy (Joules).

        powermetrics -s cpu_power outputs lines like:
          ... CPU Power: 5000 mW ...
        Joules = mW * seconds / 1000
        """
        samples = []
        for line in output_lines:
            # Look for "CPU Power: <mW> mW"
            m = re.search(r"CPU Power:\s*([\d.]+)\s*mW", line)
            if m:
                mw = float(m.group(1))
                samples.append(mw)

        if not samples:
            return {
                "available": True,
                "joules": 0.0,
                "samples": 0,
                "wall_s": wall_s,
                "error": "no_power_samples_found",
            }

        # Average power in mW over wall time in seconds
        avg_mw = sum(samples) / len(samples)
        joules = (avg_mw * wall_s) / 1000.0

        return {
            "available": True,
            "joules": round(joules, 3),
            "samples": len(samples),
            "wall_s": wall_s,
            "error": None,
        }


class FakePowermetricsSampler:
    """Fake sampler for testing (simulates subprocess but is synchronous)."""

    def __init__(self, interval_ms: int = 500):
        self.interval_ms = interval_ms
        self.running = False
        self._start_time = None
        self._fake_samples = None

    def start(self) -> bool:
        self.running = True
        self._start_time = time.time()
        return True

    def stop_and_measure(self) -> dict | None:
        if not self.running:
            return None
        self.running = False
        wall_s = time.time() - self._start_time
        # Return fake energy data
        return {
            "available": True,
            "joules": 5.0,  # dummy value
            "samples": 10,
            "wall_s": wall_s,
            "error": None,
        }

    def set_fake_samples(self, samples: list[float]):
        """For testing: set what samples will be returned."""
        self._fake_samples = samples
