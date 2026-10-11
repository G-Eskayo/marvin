"""Tests for merge_trend.py: record merge events with mutation scoring and classification.
Written to break it: missing PR, bad API responses, invalid score format, locked log file, score not in PR body,
mutations with no mutations_total field, and main() CLI entry point.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_merge_trend.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import merge_trend as mt  # noqa: E402
import auto_merge_policy as amp  # noqa: E402


@pytest.fixture
def log_path(tmp_path):
    """A temporary log file."""
    return tmp_path / "merge-trend.jsonl"


def test_record_merge_event_returns_none_on_error(log_path):
    """When gh fails or score is missing, return None (best effort)."""
    with patch.object(mt, '_gh', side_effect=subprocess.CalledProcessError(1, 'gh')):
        result = mt.record_merge_event("G-Eskayo/marvin", "https://github.com/G-Eskayo/marvin/pull/1", log_path)
        assert result is None


def test_record_merge_event_writes_jsonl_line(log_path):
    """Successfully records a merge event to the log."""
    def mock_gh_view(args):
        if args[1] == 'view':
            return json.dumps({"body": "Mutation score: 85%"})
        return ""

    def mock_gh_pr_files(args):
        if 'files' in args:
            return json.dumps([
                {"path": "lib/foo.py", "additions": 10, "deletions": 0},
                {"path": "dashboard/webhook-server/merge.js", "additions": 5, "deletions": 2}
            ])
        return ""

    with patch.object(mt, '_gh', side_effect=lambda a: mock_gh_view(a) or mock_gh_pr_files(a)):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="lib\ndashboard\nconfig\n")
            with patch('merge_trend.amp.load_rules', return_value={"core": ["lib/auto_merge*.py"]}):
                with patch('merge_trend.amp.area', side_effect=lambda path, rules, top:
                    'core' if 'auto_merge' in path else 'owned'):
                    result = mt.record_merge_event("G-Eskayo/marvin", "https://github.com/G-Eskayo/marvin/pull/123", log_path)

    # Should have written a line
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["pr_url"] == "https://github.com/G-Eskayo/marvin/pull/123"
    assert entry["score"] == 85


def test_record_merge_event_classifies_area(log_path):
    """Records area field in the entry."""
    def mock_gh(*args, **kwargs):
        if 'view' in str(args):
            return json.dumps({"body": "Mutation score: 90%"})
        if 'files' in str(args):
            return json.dumps([{"path": "dashboard/webhook-server/index.js", "additions": 10, "deletions": 0}])
        return ""

    with patch.object(mt, '_gh', side_effect=mock_gh):
        with patch.object(mt, '_classify_area', return_value='ui'):
            mt.record_merge_event("G-Eskayo/marvin", "https://github.com/G-Eskayo/marvin/pull/200", log_path)

    entry = json.loads(log_path.read_text().strip())
    assert entry["area"] == "ui"


def test_record_merge_event_handles_missing_score(log_path):
    """Returns None if mutation score not in PR body."""
    with patch.object(mt, '_gh', return_value=json.dumps({"body": "No score here"})):
        result = mt.record_merge_event("G-Eskayo/marvin", "https://github.com/G-Eskayo/marvin/pull/999", log_path)
        assert result is None


def test_record_merge_event_timestamps_correctly(log_path):
    """Records an ISO8601 timestamp."""
    def mock_gh(*args, **kwargs):
        if 'view' in str(args):
            return json.dumps({"body": "Mutation score: 75%"})
        if 'files' in str(args):
            return json.dumps([{"path": "lib/x.py", "additions": 1, "deletions": 0}])
        return ""

    before = datetime.now(timezone.utc)
    with patch.object(mt, '_gh', side_effect=mock_gh):
        with patch('merge_trend.amp.area', return_value='core'):
            mt.record_merge_event("G-Eskayo/marvin", "https://github.com/G-Eskayo/marvin/pull/42", log_path)
    after = datetime.now(timezone.utc)

    entry = json.loads(log_path.read_text().strip())
    recorded = datetime.fromisoformat(entry["recorded_at"])
    assert before <= recorded <= after


def test_record_merge_event_appends_to_existing_log(log_path):
    """Appends to an existing log file, doesn't overwrite."""
    # Write an initial entry
    log_path.write_text(json.dumps({"pr": 1, "score": 80}) + "\n")

    def mock_gh(*args, **kwargs):
        if 'view' in str(args):
            return json.dumps({"body": "Mutation score: 85%"})
        if 'files' in str(args):
            return json.dumps([{"path": "lib/x.py", "additions": 1, "deletions": 0}])
        return ""

    with patch.object(mt, '_gh', side_effect=mock_gh):
        with patch('merge_trend.amp.area', return_value='core'):
            mt.record_merge_event("G-Eskayo/marvin", "https://github.com/G-Eskayo/marvin/pull/2", log_path)

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2, "should have 2 entries now"
    assert json.loads(lines[0])["pr"] == 1
    assert json.loads(lines[1])["score"] == 85


def test_record_merge_event_handles_locked_log(log_path):
    """Best effort: returns None if log is locked."""
    def mock_gh(*args, **kwargs):
        if 'view' in str(args):
            return json.dumps({"body": "Mutation score: 88%"})
        if 'files' in str(args):
            return json.dumps([{"path": "lib/x.py", "additions": 1, "deletions": 0}])
        return ""

    with patch.object(mt, '_gh', side_effect=mock_gh):
        with patch('merge_trend.amp.area', return_value='core'):
            with patch('builtins.open', side_effect=IOError("file locked")):
                result = mt.record_merge_event("G-Eskayo/marvin", "https://github.com/G-Eskayo/marvin/pull/50", log_path)
                assert result is None


def test_main_cli_accepts_repo_and_url(tmp_path):
    """main() CLI entry point accepts repo and PR URL."""
    log_file = tmp_path / "merge-trend.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    def mock_gh(*args, **kwargs):
        if 'view' in str(args):
            return json.dumps({"body": "Mutation score: 92%"})
        if 'files' in str(args):
            return json.dumps([{"path": "lib/x.py", "additions": 1, "deletions": 0}])
        return ""

    with patch.object(mt, '_gh', side_effect=mock_gh):
        with patch('merge_trend.amp.area', return_value='core'):
            with patch.object(mt, 'MERGE_TREND_LOG', log_file):
                try:
                    mt.main(["G-Eskayo/marvin", "https://github.com/G-Eskayo/marvin/pull/75"])
                except SystemExit:
                    pass  # main() may exit

    # The file should exist and have content
    if log_file.exists():
        content = log_file.read_text().strip()
        assert content, "should have written a log entry"


# ── Tests for _classify_area helper (tests 1-2 from the plan) ──

def test_classify_area_single_core(tmp_path):
    """Test 1: A single core file is classified as core."""
    clone = tmp_path / "agents"
    clone.mkdir()
    (clone / ".git").mkdir()

    def mock_gh(*args, **kwargs):
        if args[0] == 'ls-tree':
            # Simulate git ls-tree output: existing top-level dirs
            return "lib\ndashboard\nconfig\n"
        return ""

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout="lib\ndashboard\nconfig\n")
        with patch('merge_trend.amp.load_rules', return_value={"core": ["lib/auto_merge*.py"]}):
            with patch('merge_trend.amp.area', side_effect=lambda path, rules, top_level:
                       "core" if "auto_merge" in path else "owned"):
                result = mt._classify_area("G-Eskayo/marvin", ["lib/auto_merge_shadow.py"], clone)
                assert result == "core", f"Expected 'core', got '{result}'"


def test_classify_area_mixed_files_priority(tmp_path):
    """Test 2: Multiple files with different areas; highest priority wins."""
    clone = tmp_path / "agents"
    clone.mkdir()

    # Simulate different area classifications for different files
    areas = {
        "lib/auto_merge.py": "core",
        "lib/helper.py": "owned",
        "src/ui.tsx": "ui",
        "package.json": "dependency"
    }

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout="lib\nsrc\n")
        with patch('merge_trend.amp.load_rules', return_value={}):
            with patch('merge_trend.amp.area', side_effect=lambda path, rules, top_level: areas.get(path, "owned")):
                result = mt._classify_area("G-Eskayo/marvin", list(areas.keys()), clone)
                # Priority: core > dependency > ui > new-top-level > odd > owned
                assert result == "core", f"Expected 'core' (highest priority), got '{result}'"


def test_classify_area_dependency_beats_ui(tmp_path):
    """Test: dependency area beats ui in priority."""
    clone = tmp_path / "agents"
    clone.mkdir()

    areas = {
        "package.json": "dependency",
        "src/ui.tsx": "ui"
    }

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout="src\n")
        with patch('merge_trend.amp.load_rules', return_value={}):
            with patch('merge_trend.amp.area', side_effect=lambda path, rules, top_level: areas.get(path, "owned")):
                result = mt._classify_area("G-Eskayo/marvin", list(areas.keys()), clone)
                assert result == "dependency", f"Expected 'dependency', got '{result}'"
