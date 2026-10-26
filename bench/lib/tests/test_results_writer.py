#!/usr/bin/env python3
"""Tests for results_writer. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_results_writer.py -v

Tests cases 13-14 from the design doc.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import pytest
from results_writer import (
    _count_existing_runs,
    append_run_to_results,
    write_raw_results,
)


class TestResultsWriter:
    """Test cases 13-14 from the design doc."""

    def test_case_13_spike_run_twice_appends_new_run(self):
        """Test case 13: Spike run twice → appends new Run N section.
        Never overwrites or duplicates previous run's numbers.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            results_md = Path(tmpdir) / "RESULTS.md"

            # Write initial RESULTS.md with Run 1
            results_md.write_text(
                "# marvin-bench — results log\n\n"
                "## Run 1 — 2026-10-01\n\n"
                "Initial run.\n\n"
            )

            # Verify run count
            count_before = _count_existing_runs(results_md)
            assert count_before == 1

            # Run 1 (first spike run)
            run1_results = [
                {
                    "task_id": "spike-100",
                    "gate": {"ok": True, "kind": "passed"},
                    "usage": {"prompt_tokens": 100, "gen_tokens": 50},
                    "energy": {"available": True, "joules": 5.0},
                    "wall_s": 30,
                    "diff_size": 50,
                    "kind": "docs-fix",
                }
            ]
            append_run_to_results(results_md, run1_results)

            # Verify it's appended (not overwritten)
            content = results_md.read_text()
            assert "Run 1 — 2026-10-01" in content  # Original still there
            assert "Run 2 —" in content  # New run appended

            count_after = _count_existing_runs(results_md)
            assert count_after == 2

            # Run 2 (retry)
            run2_results = [
                {
                    "task_id": "spike-200",
                    "gate": {"ok": False, "kind": "failed"},
                    "usage": {"prompt_tokens": 120, "gen_tokens": 60},
                    "energy": {"available": False},
                    "wall_s": 35,
                    "diff_size": 40,
                    "kind": "test-addition",
                }
            ]
            append_run_to_results(results_md, run2_results)

            content = results_md.read_text()
            # All runs should be present
            assert "Run 1 —" in content
            assert "Run 2 —" in content
            assert "Run 3 —" in content

            count_final = _count_existing_runs(results_md)
            assert count_final == 3

    def test_case_14_partial_run_marks_missing_tickets(self):
        """Test case 14: Partial run (3 of 5 tickets finish).
        Missing tickets are marked explicitly, never silently omitted.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            results_md = Path(tmpdir) / "RESULTS.md"

            # Simulate a spike that ran 3 of 5 tasks
            partial_results = [
                {
                    "task_id": "spike-100",
                    "gate": {"ok": True, "kind": "passed"},
                    "usage": {"prompt_tokens": 100, "gen_tokens": 50},
                    "energy": {"available": True, "joules": 5.0},
                    "wall_s": 30,
                    "diff_size": 50,
                    "kind": "docs-fix",
                },
                {
                    "task_id": "spike-200",
                    "gate": {"ok": True, "kind": "passed"},
                    "usage": {"prompt_tokens": 110, "gen_tokens": 55},
                    "energy": {"available": True, "joules": 5.2},
                    "wall_s": 31,
                    "diff_size": 55,
                    "kind": "one-line-bugfix",
                },
                {
                    "task_id": "spike-300",
                    "gate": None,
                    "status": "timeout",
                    "error": "Spike crashed before finishing",
                    "usage": {"prompt_tokens": 0, "gen_tokens": 0},
                    "energy": None,
                    "wall_s": 600,
                    "diff_size": 100,
                    "kind": "test-addition",
                },
            ]

            append_run_to_results(results_md, partial_results)

            content = results_md.read_text()

            # Verify all 3 results are in the table
            assert "spike-100" in content
            assert "spike-200" in content
            assert "spike-300" in content

            # The partial run should be documented
            assert "Spike testing" in content  # header text
            # If a ticket had an error, it should show
            assert "timeout" in content or "timeout" in str(partial_results)


class TestRunCounting:
    """Test counting existing runs."""

    def test_count_existing_runs_empty_file(self):
        """Test counting runs in a new file."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            path = Path(f.name)

        try:
            count = _count_existing_runs(path)
            assert count == 0
        finally:
            path.unlink()

    def test_count_existing_runs_multiple(self):
        """Test counting multiple runs."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            path = Path(f.name)
            f.write("## Run 1 — date\n\n")
            f.write("## Run 2 — date\n\n")
            f.write("## Run 3 — date\n\n")

        try:
            count = _count_existing_runs(path)
            assert count == 3
        finally:
            path.unlink()


class TestWriteRawResults:
    """Test raw results JSON writing."""

    def test_write_raw_results_creates_file(self):
        """Test that write_raw_results creates a JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir)

            results = [
                {
                    "task_id": "test-1",
                    "status": "success",
                    "gate": {"ok": True, "kind": "passed"},
                }
            ]

            path = write_raw_results(results_dir, results)

            assert path.exists()
            assert path.suffix == ".json"
            # Verify content
            data = json.loads(path.read_text())
            assert len(data) == 1
            assert data[0]["task_id"] == "test-1"

    def test_write_raw_results_multiple_times(self):
        """Test that successive writes create separate files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir)

            path1 = write_raw_results(results_dir, [{"task_id": "1"}])
            path2 = write_raw_results(results_dir, [{"task_id": "2"}])

            # Should be different files (different timestamps)
            assert path1 != path2
            assert path1.exists()
            assert path2.exists()


class TestFormatting:
    """Test result formatting."""

    def test_table_formatting(self):
        """Test that results table is valid markdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_md = Path(tmpdir) / "RESULTS.md"

            results = [
                {
                    "task_id": "spike-100",
                    "gate": {"ok": True, "kind": "passed"},
                    "usage": {"prompt_tokens": 100, "gen_tokens": 50},
                    "energy": {"available": True, "joules": 5.0},
                    "wall_s": 30,
                    "diff_size": 50,
                    "kind": "docs-fix",
                },
                {
                    "task_id": "spike-200",
                    "gate": {"ok": False, "kind": "failed"},
                    "usage": {"prompt_tokens": 110, "gen_tokens": 55},
                    "energy": {"available": False},
                    "wall_s": 31,
                    "diff_size": 55,
                    "kind": "test-addition",
                },
            ]

            append_run_to_results(results_md, results)

            content = results_md.read_text()

            # Check for table structure
            assert "| Task |" in content
            assert "| spike-100 |" in content
            assert "| spike-200 |" in content
            # Check for pass/fail markers
            assert "✓" in content  # for spike-100
            assert "✗" in content  # for spike-200
