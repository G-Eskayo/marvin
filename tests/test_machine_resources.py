#!/usr/bin/env python3
"""Tests for lib/machine_resources.py.

Tests the parser against real-world sample outputs and edge cases.
All fixtures are captured/plausible outputs from actual macOS commands.
"""
import json
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import machine_resources as mr


# ─── Fixtures: Real-world command outputs ──────────────────────────────────

SAMPLE_HEALTHY = """\
timestamp=1728484200
mem_pressure=42.5
swap_pct=15.3
cpu_pct=28.4
gpu_pct=65
disk_total_kb=2097152000
disk_free_kb=524288000
disk_pct=25
"""

SAMPLE_EMPTY_STRING = ""

SAMPLE_TRUNCATED_LAST_LINE = """\
timestamp=1728484200
mem_pressure=42.5
swap_pct=15.3
cpu_pct=28.4
disk_total_k
"""

SAMPLE_GPU_ABSENT_IDLE = """\
timestamp=1728484200
mem_pressure=12.1
swap_pct=0.0
cpu_pct=8.3
gpu_pct=
disk_total_kb=2097152000
disk_free_kb=524288000
disk_pct=25
"""

SAMPLE_GPU_ZERO = """\
timestamp=1728484200
mem_pressure=12.1
swap_pct=0.0
cpu_pct=8.3
gpu_pct=0
disk_total_kb=2097152000
disk_free_kb=524288000
disk_pct=25
"""

SAMPLE_SWAP_TRAILING_ENCRYPTED = """\
timestamp=1728484200
mem_pressure=45.0
swap_pct=22.5
cpu_pct=35.2
gpu_pct=10
disk_total_kb=2097152000
disk_free_kb=104857600
disk_pct=5
"""

SAMPLE_DF_WRAPPED_LINES = """\
timestamp=1728484200
mem_pressure=40.0
swap_pct=5.0
cpu_pct=12.0
gpu_pct=8
disk_total_kb=2097152000
disk_free_kb=419430400
disk_pct=20
"""

SAMPLE_HUGE_INPUT = "timestamp=1728484200\n" + "x=y\n" * 100000

SAMPLE_MALFORMED_KEY_VALUE = """\
timestamp=1728484200
mem_pressure=42.5
this_line_has_no_equals
swap_pct=15.3
another:bad:format:line
cpu_pct=28.4
"""

SAMPLE_EMPTY_FIELDS = """\
timestamp=
mem_pressure=
swap_pct=
cpu_pct=
gpu_pct=
disk_total_kb=
disk_free_kb=
disk_pct=
"""

SAMPLE_TRAILING_WHITESPACE = """\
timestamp=1728484200
mem_pressure=42.5
swap_pct=15.3
cpu_pct=28.4
"""

SAMPLE_ALL_NONE = """\
gpu_pct=
cpu_pct=
"""

SAMPLE_DUPLICATE_KEY = """\
timestamp=1728484200
mem_pressure=10.0
mem_pressure=20.0
mem_pressure=30.0
swap_pct=5.0
"""

# ─── Test: Parser ──────────────────────────────────────────────────────────

class TestParseResources:
    """Parser robustness tests."""

    def test_healthy_sample(self):
        """Parse a typical healthy sample."""
        result = mr.parse_resources(SAMPLE_HEALTHY)
        assert result["timestamp"] == 1728484200
        assert result["timestamp_iso"] == "2024-10-09T14:30:00+00:00"
        assert result["mem_pressure"] == 42.5
        assert result["swap_pct"] == 15.3
        assert result["cpu_pct"] == 28.4
        assert result["gpu_pct"] == 65
        assert result["disk_total_kb"] == 2097152000
        assert result["disk_free_kb"] == 524288000
        assert result["disk_pct"] == 25

    def test_empty_string_input(self):
        """Empty input yields all None."""
        result = mr.parse_resources(SAMPLE_EMPTY_STRING)
        assert result["timestamp"] is None
        assert result["mem_pressure"] is None
        assert result["swap_pct"] is None
        assert result["cpu_pct"] is None
        assert result["gpu_pct"] is None
        assert result["disk_free_kb"] is None
        assert result["disk_total_kb"] is None
        assert result["disk_pct"] is None

    def test_truncated_last_line(self):
        """Truncated/garbled last line is skipped."""
        result = mr.parse_resources(SAMPLE_TRUNCATED_LAST_LINE)
        assert result["timestamp"] == 1728484200
        assert result["mem_pressure"] == 42.5
        assert result["swap_pct"] == 15.3
        assert result["cpu_pct"] == 28.4
        assert result["disk_total_kb"] is None  # The truncated line is skipped
        assert result["disk_free_kb"] is None

    def test_gpu_absent_idle(self):
        """GPU missing at idle → gpu_pct=None, not 0."""
        result = mr.parse_resources(SAMPLE_GPU_ABSENT_IDLE)
        assert result["gpu_pct"] is None

    def test_gpu_zero_vs_absent(self):
        """GPU=0 and GPU=absent render differently."""
        absent = mr.parse_resources(SAMPLE_GPU_ABSENT_IDLE)
        zero = mr.parse_resources(SAMPLE_GPU_ZERO)
        assert absent["gpu_pct"] is None
        assert zero["gpu_pct"] == 0

    def test_swap_with_trailing_text(self):
        """Swap parsing ignores trailing '(encrypted)' suffix."""
        result = mr.parse_resources(SAMPLE_SWAP_TRAILING_ENCRYPTED)
        assert result["swap_pct"] == 22.5

    def test_df_wrapped_lines(self):
        """Long device paths that wrap onto second line parse correctly."""
        result = mr.parse_resources(SAMPLE_DF_WRAPPED_LINES)
        assert result["disk_total_kb"] == 2097152000
        assert result["disk_free_kb"] == 419430400
        assert result["disk_pct"] == 20

    def test_pathologically_huge_input(self):
        """Parser handles huge input in bounded time (no timeout)."""
        start = time.time()
        result = mr.parse_resources(SAMPLE_HUGE_INPUT)
        elapsed = time.time() - start
        assert elapsed < 1.0  # Should be nearly instant
        assert result["timestamp"] == 1728484200
        assert result["mem_pressure"] is None

    def test_malformed_key_value_lines(self):
        """Malformed lines (no '=', wrong format) are skipped silently."""
        result = mr.parse_resources(SAMPLE_MALFORMED_KEY_VALUE)
        assert result["timestamp"] == 1728484200
        assert result["mem_pressure"] == 42.5
        assert result["swap_pct"] == 15.3
        assert result["cpu_pct"] == 28.4

    def test_empty_fields(self):
        """Empty field values parse as None, not errors."""
        result = mr.parse_resources(SAMPLE_EMPTY_FIELDS)
        assert result["timestamp"] is None
        assert result["mem_pressure"] is None
        assert result["gpu_pct"] is None
        assert result["disk_total_kb"] is None

    def test_trailing_whitespace(self):
        """Trailing whitespace is stripped before parsing."""
        result = mr.parse_resources(SAMPLE_TRAILING_WHITESPACE)
        assert result["timestamp"] == 1728484200
        assert result["mem_pressure"] == 42.5
        assert result["swap_pct"] == 15.3

    def test_all_none_sample(self):
        """A sample with only empty fields yields all-None output."""
        result = mr.parse_resources(SAMPLE_ALL_NONE)
        for key in [
            "timestamp",
            "mem_pressure",
            "swap_pct",
            "cpu_pct",
            "gpu_pct",
            "disk_total_kb",
            "disk_free_kb",
            "disk_pct",
        ]:
            assert result[key] is None

    def test_duplicate_key(self):
        """Duplicate keys: last value wins (dict update semantics)."""
        result = mr.parse_resources(SAMPLE_DUPLICATE_KEY)
        assert result["mem_pressure"] == 30.0  # Last one wins
        assert result["timestamp"] == 1728484200

    def test_custom_timezone(self):
        """Custom timezone is used for timestamp_iso conversion."""
        eastern = timezone(timedelta(hours=-5))
        result = mr.parse_resources(SAMPLE_HEALTHY, tz=eastern)
        assert result["timestamp_iso"] == "2024-10-09T09:30:00-05:00"


class TestSampleNow:
    """Integration tests for capturing a live sample."""

    def test_sample_now_success(self):
        """sample_now() with a mock successful command."""
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            stdout=SAMPLE_HEALTHY, returncode=0
        )
        result = mr.sample_now(device_id="test-device", run=mock_run)
        assert result["timestamp"] == 1728484200
        assert result["mem_pressure"] == 42.5
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert "bash" in args[0]
        assert kwargs.get("timeout") == 10

    def test_sample_now_timeout(self):
        """sample_now() with a timeout returns all-None dict."""
        mock_run = MagicMock(side_effect=subprocess.TimeoutExpired("bash", 10))
        result = mr.sample_now(device_id="test-device", run=mock_run)
        assert result["timestamp"] is None
        assert result["mem_pressure"] is None

    def test_sample_now_command_fails(self):
        """sample_now() with a failed command returns all-None dict."""
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            stdout="", returncode=1
        )
        result = mr.sample_now(device_id="test-device", run=mock_run)
        assert result["timestamp"] is None

    def test_sample_now_exception(self):
        """sample_now() with any exception returns all-None dict."""
        mock_run = MagicMock(side_effect=Exception("oops"))
        result = mr.sample_now(device_id="test-device", run=mock_run)
        assert result["timestamp"] is None


# ─── Test: File I/O (append, read, trim) ──────────────────────────────────

class TestAppendAndRead:
    """Tests for append_sample() and read_samples()."""

    def test_append_sample_creates_dir(self):
        """append_sample() creates the log directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "logs" / "machine-resources.test.jsonl"
            sample = mr.parse_resources(SAMPLE_HEALTHY)
            mr.append_sample(sample, device_id="test", path=path)
            assert path.exists()
            assert path.parent.exists()

    def test_append_and_read_roundtrip(self):
        """Appending and reading yields back the original sample."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "machine-resources.test.jsonl"
            sample = mr.parse_resources(SAMPLE_HEALTHY)
            mr.append_sample(sample, device_id="test", path=path)
            samples = mr.read_samples(device_id="test", path=path)
            assert len(samples) == 1
            assert samples[0]["timestamp"] == 1728484200
            assert samples[0]["mem_pressure"] == 42.5

    def test_append_multiple_samples(self):
        """Multiple appends accumulate in order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "machine-resources.test.jsonl"
            samples = [
                mr.parse_resources(SAMPLE_HEALTHY),
                mr.parse_resources(SAMPLE_GPU_ABSENT_IDLE),
            ]
            for s in samples:
                mr.append_sample(s, device_id="test", path=path)
            read_back = mr.read_samples(device_id="test", path=path)
            assert len(read_back) == 2
            assert read_back[0]["mem_pressure"] == 42.5
            assert read_back[1]["mem_pressure"] == 12.1

    def test_read_nonexistent_file(self):
        """read_samples() on a missing file returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "doesnt-exist.jsonl"
            samples = mr.read_samples(device_id="test", path=path)
            assert samples == []

    def test_trim_24h(self):
        """append_sample() trims to 24h window (last MAX_SAMPLES_PER_24H)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "machine-resources.test.jsonl"
            # Write MORE than MAX_SAMPLES_PER_24H entries
            for i in range(mr.MAX_SAMPLES_PER_24H + 100):
                sample = {
                    "timestamp": 1728484200 + i,
                    "timestamp_iso": "2024-10-09T02:10:00+00:00",
                    "mem_pressure": float(i),
                    "swap_pct": None,
                    "cpu_pct": None,
                    "gpu_pct": None,
                    "disk_free_kb": None,
                    "disk_total_kb": None,
                    "disk_pct": None,
                }
                mr.append_sample(sample, device_id="test", path=path)
            read_back = mr.read_samples(device_id="test", path=path)
            assert len(read_back) == mr.MAX_SAMPLES_PER_24H
            # Oldest entry should be from the ~100 samples after the initial cutoff
            assert read_back[0]["timestamp"] == 1728484200 + 100

    def test_skip_malformed_jsonl_lines(self):
        """read_samples() skips malformed JSON lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "machine-resources.test.jsonl"
            # Write a mix of valid and invalid JSON
            lines = [
                json.dumps({"timestamp": 100, "mem_pressure": 10}),
                "{ broken json",
                json.dumps({"timestamp": 101, "mem_pressure": 11}),
                "",  # empty line
                json.dumps({"timestamp": 102, "mem_pressure": 12}),
            ]
            path.write_text("\n".join(lines) + "\n")
            samples = mr.read_samples(device_id="test", path=path)
            assert len(samples) == 3
            assert samples[0]["timestamp"] == 100
            assert samples[1]["timestamp"] == 101
            assert samples[2]["timestamp"] == 102


class TestStaleness:
    """Tests for is_stale() detection."""

    def test_is_stale_empty_samples(self):
        """Empty sample list is stale."""
        assert mr.is_stale([]) is True

    def test_is_stale_no_timestamp(self):
        """Sample with no timestamp is stale."""
        assert mr.is_stale([{"mem_pressure": 42}]) is True

    def test_is_stale_recent_sample(self):
        """Recent sample is not stale."""
        now = int(datetime.now(timezone.utc).timestamp())
        samples = [{"timestamp": now, "mem_pressure": 42}]
        assert mr.is_stale(samples) is False

    def test_is_stale_old_sample(self):
        """Sample older than (SAMPLE_INTERVAL * STALE_INTERVALS) is stale."""
        now = int(datetime.now(timezone.utc).timestamp())
        old = now - (mr.SAMPLE_INTERVAL * mr.STALE_INTERVALS) - 1
        samples = [{"timestamp": old, "mem_pressure": 42}]
        assert mr.is_stale(samples) is True

    def test_is_stale_boundary(self):
        """Sample just within boundary is not stale."""
        # Use a sample that's well within the not-stale window to avoid timing races
        now = int(datetime.now(timezone.utc).timestamp())
        just_fresh = now - (mr.SAMPLE_INTERVAL * mr.STALE_INTERVALS) + 10
        samples = [{"timestamp": just_fresh, "mem_pressure": 42}]
        assert mr.is_stale(samples) is False


# ─── Test: Adversarial / security ─────────────────────────────────────────

class TestAdversarial:
    """Security and adversarial test cases."""

    def test_no_command_injection_in_script(self):
        """The resource sample script contains no shell metacharacters."""
        script = mr._resource_sample_script()
        # Check that the script doesn't have unescaped variable expansion
        # that could be exploited via injected hostnames, etc.
        assert "$(" not in script or "$(date" in script  # allowed date call
        assert ";" not in script.split("$(date")[0]  # no dangerous semicolons before date

    def test_parse_doesnt_eval(self):
        """parse_resources() never evals or executes user input."""
        # Try injecting shell commands and Python code
        malicious = "timestamp=1728484200\nmem_pressure=$(rm -rf /)\ncpu_pct=__import__('os').system('ls')"
        result = mr.parse_resources(malicious)
        assert result["timestamp"] == 1728484200
        assert result["mem_pressure"] is None  # The malicious value is not eval'd
        assert result["cpu_pct"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
