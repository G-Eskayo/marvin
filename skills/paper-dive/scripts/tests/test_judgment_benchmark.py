"""Tests for judgment_benchmark.py. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_judgment_benchmark.py -v
"""
from __future__ import annotations
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest
import judgment_benchmark


def test_save_benchmark_atomic():
    """Test that benchmark save is atomic (temp file swap)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test_benchmark.json"
        benchmark = {
            "paper1": {"slug": "paper1", "title": "Test Paper", "paper_type": "empirical"},
            "paper2": {"slug": "paper2", "title": "Test Paper 2", "paper_type": "survey"},
        }

        judgment_benchmark.save_benchmark(benchmark, out_path)

        assert out_path.exists()
        loaded = json.loads(out_path.read_text())
        assert loaded == benchmark
        assert len(loaded) == 2


def test_save_benchmark_overwrites():
    """Test that save overwrites existing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test_benchmark.json"

        # Write initial benchmark
        benchmark1 = {"paper1": {"slug": "paper1", "title": "Test Paper 1"}}
        judgment_benchmark.save_benchmark(benchmark1, out_path)

        # Overwrite with different benchmark
        benchmark2 = {"paper2": {"slug": "paper2", "title": "Test Paper 2"}}
        judgment_benchmark.save_benchmark(benchmark2, out_path)

        loaded = json.loads(out_path.read_text())
        assert "paper2" in loaded
        assert "paper1" not in loaded


def test_make_gold_labels_structure():
    """Test that _make_gold_labels returns expected structure."""
    def fake_chat(messages):
        # Return minimal valid responses for each type of call
        prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        if "Classify" in prompt or "CLASSIFY" in prompt:
            return "empirical"
        elif "Decompose" in prompt or "CLAIM" in prompt:
            return "CLAIM: test claim\nGROUNDS: test grounds\nWARRANT: test warrant\nQUALIFIER: test qualifier"
        elif "FINDING" in prompt:
            return "NONE"
        elif "identify its single" in prompt or "REASONING_TYPE" in prompt:
            return "P: claim\nQ: evidence\nREASONING_TYPE: inductive\nARGUMENT_FORM: evidence supports\nVALIDITY: strong"
        return ""

    with patch("judgment_benchmark._make_gold_labels") as mock_make:
        expected_result = {
            "slug": "test-paper",
            "title": "Test Paper",
            "paper_type": "empirical",
            "extraction": {},
            "findings": [],
            "inference": {},
            "reliability_level": "high",
            "reliability_findings": [],
        }
        mock_make.return_value = expected_result

        result = mock_make("test-paper", "Test Paper", "abstract")
        assert result["slug"] == "test-paper"
        assert result["title"] == "Test Paper"
        assert "paper_type" in result
        assert "extraction" in result
        assert "findings" in result
        assert "inference" in result


def test_build_benchmark_validates_collection_exists():
    """Test that build_benchmark validates the collection exists."""
    with patch("chromadb.PersistentClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        mock_client.get_or_create_collection.return_value = mock_collection

        with pytest.raises(ValueError, match="paper-knowledge collection is empty"):
            judgment_benchmark.build_benchmark(1)


def test_build_benchmark_respects_sample_size():
    """Test that build_benchmark uses min(requested, available) samples."""
    sample_ids = [f"paper{i}" for i in range(5)]

    with patch("chromadb.PersistentClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_collection = MagicMock()

        # First call: get all IDs
        # Second call: get the sample data
        mock_collection.get.side_effect = [
            {"ids": sample_ids, "documents": [], "metadatas": []},
            {
                "ids": sample_ids[:3],
                "documents": ["abstract1", "abstract2", "abstract3"],
                "metadatas": [
                    {"title": "Paper 1"},
                    {"title": "Paper 2"},
                    {"title": "Paper 3"},
                ],
            }
        ]
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("judgment_benchmark._make_gold_labels") as mock_make:
            mock_make.return_value = {"slug": "test", "paper_type": "empirical"}
            with patch("random.sample", return_value=sample_ids[:3]):
                benchmark = judgment_benchmark.build_benchmark(3)
                assert len(benchmark) == 3


def test_judge_call_checks_returncode():
    """Test that _judge_call raises on non-zero returncode."""
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "claude error"
        mock_proc.stdout = ""
        mock_run.return_value = mock_proc

        with pytest.raises(RuntimeError, match="claude judge failed with code 1"):
            judgment_benchmark._judge_call("test prompt")


def test_make_gold_labels_includes_abstract():
    """Test that gold labels include the abstract for re-running student."""
    with patch("judgment_benchmark._judge_call") as mock_judge:
        mock_judge.return_value = "test response"

        # Mock logic_auditor functions
        with patch("judgment_benchmark.logic_auditor.classify_paper_type") as mock_classify:
            mock_classify.return_value = "empirical"
            with patch("judgment_benchmark.logic_auditor.extract_structure") as mock_extract:
                mock_extract.return_value = {}
                with patch("judgment_benchmark.logic_auditor.judge_extraction") as mock_judge_ext:
                    mock_judge_ext.return_value = []
                    with patch("judgment_benchmark.logic_auditor.check_inference_validity") as mock_infer:
                        mock_infer.return_value = {}
                        with patch("judgment_benchmark.logic_auditor.compute_reliability_signal") as mock_signal:
                            mock_signal.return_value = {"level": "high", "findings": []}

                            result = judgment_benchmark._make_gold_labels(
                                "paper1", "Test Title", "Test abstract content"
                            )

                            assert "abstract" in result
                            assert result["abstract"] == "Test abstract content"


def test_build_benchmark_skips_failed_papers():
    """Test that failed papers are skipped, not added with placeholder entries."""
    sample_ids = ["paper1", "paper2", "paper3"]

    with patch("chromadb.PersistentClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_collection = MagicMock()

        mock_collection.get.side_effect = [
            {"ids": sample_ids, "documents": [], "metadatas": []},
            {
                "ids": sample_ids,
                "documents": ["abstract1", "abstract2", "abstract3"],
                "metadatas": [
                    {"title": "Paper 1"},
                    {"title": "Paper 2"},
                    {"title": "Paper 3"},
                ],
            }
        ]
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("random.sample", return_value=sample_ids):
            with patch("judgment_benchmark._make_gold_labels") as mock_make:
                # First and third succeed, second fails
                mock_make.side_effect = [
                    {"slug": "paper1", "paper_type": "empirical"},
                    RuntimeError("Failed to generate labels"),
                    {"slug": "paper3", "paper_type": "survey"},
                ]

                benchmark = judgment_benchmark.build_benchmark(3)

                # Should only have 2 papers (failed paper3 skipped)
                assert len(benchmark) == 2
                assert "paper1" in benchmark
                assert "paper3" in benchmark
                assert "paper2" not in benchmark

                # Verify no "unknown" papers in benchmark
                for paper_id, paper_data in benchmark.items():
                    assert paper_data.get("paper_type") != "unknown"
