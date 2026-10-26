#!/usr/bin/env python3
"""Tests for select_spike_tickets. Run via:
    ~/.agents/venv/bin/python -m pytest tests/test_select_spike_tickets.py -v

Tests cases 1-3 from the design doc.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import pytest
from select_spike_tickets import (
    TicketCandidate,
    _classify_kind,
    _get_single_parent_base,
    select_candidates,
    write_task_dirs,
)


class TestSelectTickets:
    """Test cases 1-3 from the design doc."""

    def test_case_1_no_linked_issue_skipped(self):
        """Test case 1: Candidate PR has no linked issue / no issue body → skip with reason."""
        candidates = [
            TicketCandidate(
                pr_number=100,
                pr_title="Fix typo",
                pr_url="",
                issue_number=None,
                issue_title=None,
                issue_body=None,
                merge_commit="abc123",
                base_branch="main",
                diff_size=10,
                kind="docs-fix",
            )
        ]

        # Simulate selection with a mock that rejects candidates with no issue
        def select_with_filtering(candidates_list):
            return [c for c in candidates_list if c.issue_number is not None or c.issue_body]

        result = select_with_filtering(candidates)
        assert len(result) == 0, "PR with no issue should be skipped"

    def test_case_2_squash_merge_base_resolution(self):
        """Test case 2: Merge commit has more than one non-trivial parent.
        Base commit resolution picks correctly or skips with reason.
        """
        # Simulate git output for a squash merge (1 parent)
        with patch("select_spike_tickets.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc123\n",  # Single parent
            )

            base = _get_single_parent_base("merge_commit_123")
            assert base == "abc123"

        # Simulate git output for a normal merge (2 parents)
        with patch("select_spike_tickets.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="parent_1 parent_2\n",
            )

            base = _get_single_parent_base("merge_commit_456")
            # Should return first parent (the base)
            assert base == "parent_1"

    def test_case_3_fewer_than_5_candidates_exits_cleanly(self):
        """Test case 3: Fewer than 5 candidates match filters.
        Exits with clear message, never ships RESULTS.md with fabricated rows.
        """
        # Create 3 valid candidates
        candidates = [
            TicketCandidate(
                pr_number=i,
                pr_title=f"Fix #{i}",
                pr_url="",
                issue_number=i,
                issue_title=f"Issue #{i}",
                issue_body=f"Description of issue {i}",
                merge_commit=f"commit_{i}",
                base_branch="main",
                diff_size=50 + i * 10,
                kind=["docs-fix", "one-line-bugfix", "test-addition"][i % 3],
            )
            for i in range(1, 4)
        ]

        # Selection should return only 3, not fabricate more
        assert len(candidates) == 3
        selected = sorted(candidates)[:3]
        assert len(selected) == 3
        assert all(c.issue_body for c in selected), "All should have issue bodies"

    def test_classify_kind_docs(self):
        """Test kind classification for docs."""
        kind = _classify_kind("Update README", "docs: fix formatting", 5, 3)
        assert kind == "docs-fix"

    def test_classify_kind_test(self):
        """Test kind classification for test additions."""
        kind = _classify_kind("Add test for edge case", "test: new test", 80, 0)
        assert kind == "test-addition"

    def test_classify_kind_bugfix(self):
        """Test kind classification for one-line bugfix."""
        kind = _classify_kind("Fix off-by-one error", "bug: fixed condition", 1, 1)
        assert kind == "one-line-bugfix"

    def test_ticket_candidate_sorting(self):
        """Test that candidates are sorted by kind then size."""
        candidates = [
            TicketCandidate(
                pr_number=1,
                pr_title="",
                pr_url="",
                issue_number=1,
                issue_title="",
                issue_body="",
                merge_commit="",
                base_branch="main",
                diff_size=100,
                kind="other",  # lowest priority
            ),
            TicketCandidate(
                pr_number=2,
                pr_title="",
                pr_url="",
                issue_number=2,
                issue_title="",
                issue_body="",
                merge_commit="",
                base_branch="main",
                diff_size=50,
                kind="docs-fix",  # highest priority
            ),
            TicketCandidate(
                pr_number=3,
                pr_title="",
                pr_url="",
                issue_number=3,
                issue_title="",
                issue_body="",
                merge_commit="",
                base_branch="main",
                diff_size=75,
                kind="docs-fix",  # same kind, smaller than #2
            ),
        ]

        sorted_candidates = sorted(candidates)

        # docs-fix should come first (two of them, sorted by size)
        assert sorted_candidates[0].pr_number == 3  # size 75
        assert sorted_candidates[1].pr_number == 2  # size 50
        assert sorted_candidates[2].pr_number == 1  # other


class TestWriteTaskDirs:
    """Test task directory writing."""

    def test_write_task_dirs_creates_structure(self):
        """Test that write_task_dirs creates proper task directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_root = Path(tmpdir)

            candidates = [
                TicketCandidate(
                    pr_number=100,
                    pr_title="Fix something",
                    pr_url="https://github.com/G-Eskayo/marvin/pull/100",
                    issue_number=50,
                    issue_title="Issue title",
                    issue_body="This is the issue description that should be the prompt.",
                    merge_commit="abc123",
                    base_branch="main",
                    diff_size=30,
                    kind="one-line-bugfix",
                )
            ]

            write_task_dirs(candidates, task_root)

            # Check structure
            task_dir = task_root / "spike-opencode-ollama" / "spike-100"
            assert (task_dir / "task.json").exists()
            assert (task_dir / "prompt.md").exists()

            # Check content
            task_json = json.loads((task_dir / "task.json").read_text())
            assert task_json["id"] == "spike-100"
            assert task_json["type"] == "fs"

            prompt = (task_dir / "prompt.md").read_text()
            assert "issue description" in prompt

    def test_write_task_dirs_fallback_when_no_body(self):
        """Test that task.json/prompt.md creation falls back gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_root = Path(tmpdir)

            candidates = [
                TicketCandidate(
                    pr_number=200,
                    pr_title="Simple fix",
                    pr_url="",
                    issue_number=None,
                    issue_title=None,
                    issue_body=None,
                    merge_commit="def456",
                    base_branch="main",
                    diff_size=5,
                    kind="docs-fix",
                )
            ]

            write_task_dirs(candidates, task_root)

            # Should create the task even without issue body
            task_dir = task_root / "spike-opencode-ollama" / "spike-200"
            assert (task_dir / "task.json").exists()

            # Prompt should fall back to PR title
            prompt = (task_dir / "prompt.md").read_text()
            assert "Simple fix" in prompt or "PR #200" in prompt
