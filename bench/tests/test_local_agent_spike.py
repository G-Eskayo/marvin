"""Tests for local_agent_spike.py — orchestration of opencode + energy + ticket replay.
~/.agents/venv/bin/python -m pytest bench/tests/test_local_agent_spike.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH / "lib"))
sys.path.insert(0, str(BENCH))

import local_agent_spike as las


class TestLoadFixtureAndDefaults:
    def test_load_ticket_list_from_instance_file(self):
        """Test that instance-private JSON fixture is loaded if present."""
        fixture_data = {"tickets": ["#720", "#627", "#654", "#414", "#541"]}

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(fixture_data)
                with patch("json.load", return_value=fixture_data):
                    tickets = las.load_ticket_list("/tmp/instance.json", default=[])
                    # Should have loaded from the file and stripped '#'
                    assert tickets is not None
                    assert len(tickets) == 5

    def test_load_ticket_list_falls_back_to_default_when_file_absent(self):
        """Test fallback to public default list if instance file absent."""
        default_list = ["720", "627", "654", "414", "541"]

        with patch("pathlib.Path.exists", return_value=False):
            tickets = las.load_ticket_list("/tmp/instance.json", default=default_list)
            assert tickets == default_list

    def test_load_ticket_list_strips_hash_prefix(self):
        """Test that '#' prefix is stripped from ticket numbers."""
        fixture_data = {"tickets": ["#720", "#627"]}

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", create=True):
                with patch("json.load", return_value=fixture_data):
                    tickets = las.load_ticket_list("/tmp/instance.json", default=[])
                    # Should have stripped '#'
                    assert all("#" not in t for t in tickets)

    def test_load_ticket_list_returns_default_on_json_error(self):
        """Test that default is returned if JSON is invalid."""
        default_list = ["720", "627"]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", create=True):
                with patch("json.load", side_effect=json.JSONDecodeError("msg", "doc", 0)):
                    tickets = las.load_ticket_list("/tmp/instance.json", default=default_list)
                    assert tickets == default_list

    def test_default_ticket_list_is_reasonable(self):
        """Test that default ticket list has some candidates."""
        tickets = las.DEFAULT_TICKET_LIST
        assert len(tickets) >= 5


class TestGateScoring:
    def test_score_gate_pass_marked_as_pass(self):
        """Test that gate-pass scoring works when score == 1.0."""
        result = {
            "correctness": {"score": 1.0},
            "result_text": "successful completion",
        }

        gate_pass = las.score_gate_pass(result)
        assert gate_pass is True

    def test_score_gate_fail_marked_as_fail(self):
        """Test that gate-fail is marked correctly when score < 1.0."""
        result = {
            "correctness": {"score": 0.5},
            "result_text": "partial result",
        }

        gate_pass = las.score_gate_pass(result)
        assert gate_pass is False

    def test_score_gate_infra_error_marked_as_none(self):
        """Test that infra errors are marked as None (not a pass/fail)."""
        result = {
            "spawn_error": "hit session limit",
            "correctness": {"score": None},
        }

        gate_pass = las.score_gate_pass(result)
        assert gate_pass is None

    def test_score_gate_computes_correctness_if_missing(self):
        """Test that score_gate_pass computes correctness if not present."""
        # Result with output but no correctness computed yet
        result = {
            "result_text": "some output",
            "spawn_error": None,
        }

        gate_pass = las.score_gate_pass(result)

        # Should have computed correctness
        assert "correctness" in result
        # Output present and no error markers → score 1.0 → pass
        assert gate_pass is True

    def test_score_gate_returns_none_for_empty_output(self):
        """Test that empty output results in 0.0 score (fail, not None)."""
        result = {
            "result_text": "",
            "spawn_error": None,
        }

        gate_pass = las.score_gate_pass(result)

        # No output → score 0.0 → fail (not None)
        assert gate_pass is False

    def test_score_gate_fails_on_error_output(self):
        """Test that output containing error markers is marked as fail."""
        result = {
            "result_text": "Error: unable to process request",
            "spawn_error": None,
        }

        gate_pass = las.score_gate_pass(result)

        # Output with error marker → score 0.0 → fail
        assert gate_pass is False

    def test_score_gate_fails_on_refusal(self):
        """Test that output containing refusal is marked as fail."""
        result = {
            "result_text": "I cannot help with that. Refused request.",
            "spawn_error": None,
        }

        gate_pass = las.score_gate_pass(result)

        # Output with refusal marker → score 0.0 → fail
        assert gate_pass is False

    def test_score_gate_fails_on_exception(self):
        """Test that output containing 'exception' is marked as fail."""
        result = {
            "result_text": "Exception occurred in processing",
            "spawn_error": None,
        }

        gate_pass = las.score_gate_pass(result)

        # Output with exception marker → score 0.0 → fail
        assert gate_pass is False


class TestResultsAppend:
    def test_get_next_run_number_returns_one_if_file_absent(self):
        """Test that get_next_run_number returns 1 if file doesn't exist."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False

        num = las.get_next_run_number(mock_path)
        assert num == 1

    def test_get_next_run_number_increments_from_existing(self):
        """Test that get_next_run_number finds max run number and increments."""
        content = """# Results

## Run 1 — 2026-10-01
results here

## Run 5 — 2026-10-02
more results

## Run 3 — 2026-10-03
even more
"""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = content

        num = las.get_next_run_number(mock_path)
        # Should find max (5) and return 6
        assert num == 6

    def test_append_results_creates_file_if_absent(self):
        """Test that append_results_section creates file with header if absent."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        # After first write, subsequent read returns the header
        mock_path.read_text.return_value = "# marvin-bench — results log\n\n"

        las.append_results_section(mock_path, "## Run 1\ntest")

        # Should have written at least once (the final append)
        assert mock_path.write_text.call_count >= 1
        # Check final write has the content
        final_write = mock_path.write_text.call_args_list[-1][0][0]
        assert "Run 1" in final_write
        assert "test" in final_write

    def test_append_results_appends_to_existing_file(self):
        """Test that append_results_section appends to existing file."""
        existing_content = "# Results\n\n## Run 1\nold"

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = existing_content

        las.append_results_section(mock_path, "## Run 2\nnew")

        written = mock_path.write_text.call_args[0][0]
        # Should contain both old and new
        assert "Run 1" in written
        assert "Run 2" in written


class TestFormatResultsTable:
    def test_format_results_table_creates_markdown_table(self):
        """Test that format_results_table creates a valid markdown table."""
        results = [
            {
                "pr_number": "720",
                "model": "qwen2.5:7b",
                "gate_pass": True,
                "wall_s": 12.5,
                "total_tokens": 500,
                "error": "",
            }
        ]

        table = las.format_results_table(results)

        assert "|" in table  # markdown table format
        assert "720" in table
        assert "qwen2.5:7b" in table
        assert "pass" in table.lower()

    def test_format_results_table_handles_pass_fail_error(self):
        """Test that gate_pass True/False/None are formatted correctly."""
        results = [
            {"pr_number": "1", "model": "m", "gate_pass": True, "wall_s": 1, "total_tokens": 0, "error": ""},
            {"pr_number": "2", "model": "m", "gate_pass": False, "wall_s": 1, "total_tokens": 0, "error": ""},
            {"pr_number": "3", "model": "m", "gate_pass": None, "wall_s": 1, "total_tokens": 0, "error": ""},
        ]

        table = las.format_results_table(results)

        assert "pass" in table.lower()
        assert "fail" in table.lower()
        assert "error" in table.lower()


class TestOrchestrateSpike:
    def test_orchestrate_loads_and_replays_tickets(self):
        """Test that orchestrate loads tickets and replays each."""
        mock_cleanup = Mock()
        ticket_data = {
            "prompt": "test prompt",
            "test_files": ["test.py"],
            "worktree_path": "/tmp/wt",
            "cleanup_fn": mock_cleanup,
        }

        with patch("local_agent_spike.tr.replay_ticket", return_value=ticket_data):
            with patch("local_agent_spike.ocr.run_once_opencode") as mock_run:
                mock_run.return_value = {
                    "result_text": "output",
                    "wall_s": 10.0,
                    "total_tokens": 100,
                    "spawn_error": None,
                }

                results = las.orchestrate_spike(
                    tickets=["720"],
                    model="qwen2.5:7b",
                    workdir=Path("/tmp"),
                )

                assert len(results) == 1
                # Cleanup should have been called
                mock_cleanup.assert_called_once()

    def test_orchestrate_handles_replay_error(self):
        """Test that orchestrate handles replay_ticket errors gracefully."""
        with patch("local_agent_spike.tr.replay_ticket") as mock_replay:
            mock_replay.return_value = {"error": "Could not resolve PR"}

            results = las.orchestrate_spike(
                tickets=["720"],
                model="qwen2.5:7b",
                workdir=Path("/tmp"),
            )

            assert len(results) == 1
            assert results[0].get("error") is not None
            assert results[0].get("gate_pass") is None

    def test_orchestrate_scores_gate_for_each_result(self):
        """Test that orchestrate calls score_gate_pass for each result."""
        mock_cleanup = Mock()
        ticket_data = {
            "prompt": "test",
            "test_files": [],
            "worktree_path": "/tmp/wt",
            "cleanup_fn": mock_cleanup,
        }

        with patch("local_agent_spike.tr.replay_ticket", return_value=ticket_data):
            with patch("local_agent_spike.ocr.run_once_opencode") as mock_run:
                mock_run.return_value = {
                    "result_text": "output",
                    "wall_s": 10.0,
                    "total_tokens": 100,
                    "spawn_error": None,
                }

                with patch("local_agent_spike.score_gate_pass", return_value=True) as mock_score:
                    results = las.orchestrate_spike(
                        tickets=["720", "627"],
                        model="qwen2.5:7b",
                        workdir=Path("/tmp"),
                    )

                    # score_gate_pass should be called for each ticket
                    assert mock_score.call_count == 2

    def test_orchestrate_runs_in_worktree_not_workdir(self):
        """Test that opencode runs in the worktree, not the default workdir."""
        mock_cleanup = Mock()
        ticket_data = {
            "prompt": "test",
            "test_files": [],
            "worktree_path": "/tmp/bench-wt-xyz",
            "cleanup_fn": mock_cleanup,
        }

        with patch("local_agent_spike.tr.replay_ticket", return_value=ticket_data):
            with patch("local_agent_spike.ocr.run_once_opencode") as mock_run:
                mock_run.return_value = {
                    "result_text": "output",
                    "wall_s": 10.0,
                    "total_tokens": 0,
                    "spawn_error": None,
                }

                las.orchestrate_spike(
                    tickets=["720"],
                    model="qwen2.5:7b",
                    workdir=Path("/tmp/default"),
                )

                # Check that opencode was called with the worktree path
                call_args = mock_run.call_args
                assert call_args[0][1] == "/tmp/bench-wt-xyz"

    def test_orchestrate_returns_results_list(self):
        """Test that orchestrate returns a list of result dicts."""
        mock_cleanup = Mock()
        ticket_data = {
            "prompt": "test",
            "test_files": [],
            "worktree_path": "/tmp/wt",
            "cleanup_fn": mock_cleanup,
        }

        with patch("local_agent_spike.tr.replay_ticket", return_value=ticket_data):
            with patch("local_agent_spike.ocr.run_once_opencode") as mock_run:
                mock_run.return_value = {
                    "result_text": "output",
                    "wall_s": 10.0,
                    "total_tokens": 100,
                    "spawn_error": None,
                }

                results = las.orchestrate_spike(
                    tickets=["720", "627"],
                    model="qwen2.5:7b",
                    workdir=Path("/tmp"),
                )

                assert isinstance(results, list)
                assert len(results) == 2


class TestCollectionSafety:
    def test_all_modules_import(self):
        """Test that all modules can be imported without errors."""
        import local_agent_spike
        assert local_agent_spike is not None
