#!/usr/bin/env python3
"""Shared harness for device-link bakeoff benchmarking.

Provides:
- Payload generation with checksums for integrity verification
- Network simulation helpers (packet loss, reorder) wrapping dnctl/pfctl
- Metrics recording wrapper around metrics_registry.py
- CLI client orchestration across variants
"""
import json
import hashlib
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import lib.metrics_registry as metrics_registry


class PayloadGenerator:
    """Generate deterministic payloads with checksums for integrity verification."""

    @staticmethod
    def generate_payload(size_bytes: int, seed: int = 0) -> Dict[str, Any]:
        """Generate a payload of specified size with checksum."""
        data = bytes([(seed + i) % 256 for i in range(size_bytes)])
        checksum = hashlib.sha256(data).hexdigest()
        return {
            "size": size_bytes,
            "seed": seed,
            "data": data.hex(),
            "checksum": checksum,
        }

    @staticmethod
    def verify_payload(payload: Dict[str, Any]) -> bool:
        """Verify payload integrity via checksum."""
        data = bytes.fromhex(payload["data"])
        expected = hashlib.sha256(data).hexdigest()
        return payload["checksum"] == expected


class NetworkSimulation:
    """Helpers for simulating packet loss and reordering via dnctl/pfctl."""

    @staticmethod
    def enable_packet_loss(interface: str, percentage: float) -> None:
        """Enable packet loss on an interface using dnctl/pfctl."""
        if percentage < 0 or percentage > 100:
            raise ValueError(f"Invalid packet loss percentage: {percentage}")

        cmd = [
            "sudo",
            "dnctl",
            "pipe",
            "config",
            "1",
            "plr",
            str(percentage / 100.0),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    @staticmethod
    def enable_packet_reorder(interface: str, percentage: float) -> None:
        """Enable packet reordering on an interface using dnctl/pfctl."""
        # pfctl can introduce latency and reordering via pipes
        # This is a placeholder; actual implementation depends on macOS version
        pass

    @staticmethod
    def disable_simulation() -> None:
        """Disable all network simulation."""
        subprocess.run(["sudo", "dnctl", "-f", "flush"], check=False)


class MetricsRecorder:
    """Wrapper around metrics_registry for recording bakeoff measurements."""

    def __init__(self, subsystem: str):
        self.subsystem = subsystem
        self.start_time = None
        self.measurements = {}

    def start(self) -> None:
        """Mark the start of a measurement period."""
        self.start_time = time.time()

    def record_metric(self, name: str, value: float, higher_is_better: bool = True) -> None:
        """Record a single metric."""
        self.measurements[name] = {"value": value, "higher_is_better": higher_is_better}

    def finalize(self) -> None:
        """Write all recorded metrics to the registry."""
        if self.measurements:
            metrics_registry.record(self.subsystem, self.measurements)
        self.measurements = {}


class CliClientRunner:
    """Orchestrate CLI client runs with timeout and result capture."""

    def __init__(self, cmd: list[str], timeout: int = 30):
        self.cmd = cmd
        self.timeout = timeout
        self.result = None
        self.error = None

    def run(self) -> Dict[str, Any]:
        """Run the CLI client and return result."""
        try:
            result = subprocess.run(
                self.cmd,
                timeout=self.timeout,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                try:
                    self.result = json.loads(result.stdout)
                except json.JSONDecodeError:
                    self.result = {"stdout": result.stdout}
            else:
                self.error = result.stderr
            return {
                "success": result.returncode == 0,
                "result": self.result,
                "error": self.error,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            self.error = f"Timeout after {self.timeout}s"
            return {"success": False, "error": self.error, "returncode": -1}
        except Exception as e:
            self.error = str(e)
            return {"success": False, "error": self.error, "returncode": -1}


def wait_for_server(host: str, port: int, timeout: int = 10) -> bool:
    """Wait for a server to be ready."""
    import socket

    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout):
            time.sleep(0.1)
    return False
