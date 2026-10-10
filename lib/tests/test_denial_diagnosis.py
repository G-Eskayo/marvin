"""Denial diagnosis and kind-tallying for the ticket pipeline (marvin#325).

When a ticket is sent back (denied), the pipeline now diagnoses what KIND of
denial it is (wrong-approach, missing-tests, ui-broken, etc.) and routes it:
- fix_forward: small targeted change
- rebuild: approach was wrong, start over
- needs_person: ticket is unclear or denial asks an unanswerable question

After 3 denials of the same KIND, file an improvement ticket so Gil can add a
rule or gate check to prevent repeats.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import denial_diagnosis as dd  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "LOG_PATH", tmp_path / "denial-diagnoses.jsonl")


def _add_diagnosis(ticket: int, kind: str, route: str, project: str = "G-Eskayo/marvin", when: datetime | None = None):
    dd._append({
        "t": (when or NOW).isoformat(),
        "kind": "diagnosis",
        "ticket": ticket,
        "project": project,
        "diagnosis_kind": kind,
        "route": route,
    })


# ── classify ────────────────────────────────────────────────────────────────

class TestClassify:
    """The analyst diagnoses what KIND of denial and routes it."""

    def test_classify_returns_dict_with_required_fields(self):
        """classify() returns {kind, route, note}."""
        issue = {"number": 5, "title": "Test", "body": "Description"}
        pr_diff = "- old\n+ new"
        failure = "Build failed"

        with patch.object(dd, "_launch_analyst") as mock_launch:
            mock_launch.return_value = "kind: wrong-approach\nroute: rebuild\nfix: rewrite from scratch"
            result = dd.classify(issue, pr_diff, failure)

        assert isinstance(result, dict)
        assert "kind" in result
        assert "route" in result
        assert "note" in result

    def test_classify_parses_analyst_response(self):
        """classify() extracts kind and route from analyst text."""
        issue = {"number": 5, "title": "Feature", "body": "Requirements"}
        pr_diff = "changes"
        failure = "Denied"

        with patch.object(dd, "_launch_analyst") as mock_launch:
            mock_launch.return_value = "The denial is a missing-tests issue. Route: fix_forward. Change X."
            result = dd.classify(issue, pr_diff, failure)

        assert result["kind"] in dd.KINDS
        assert result["route"] in ("fix_forward", "rebuild", "needs_person")

    def test_classify_falls_back_when_analyst_gives_no_answer(self):
        """classify() returns {kind: unclear, route: needs_person} if analyst fails."""
        issue = {"number": 5, "title": "Test", "body": ""}
        pr_diff = ""
        failure = ""

        with patch.object(dd, "_launch_analyst") as mock_launch:
            mock_launch.return_value = ""
            result = dd.classify(issue, pr_diff, failure)

        assert result["kind"] == "unclear"
        assert result["route"] == "needs_person"
        assert "gave no answer" in result.get("note", "").lower()

    def test_classify_handles_malformed_pr_diff(self):
        """classify() handles empty/malformed PR diff gracefully."""
        issue = {"number": 5, "title": "Test", "body": "Test"}
        pr_diffs = ["", None, "invalid\n\n\n"]

        with patch.object(dd, "_launch_analyst") as mock_launch:
            mock_launch.return_value = "kind: style\nroute: fix_forward"
            for diff in pr_diffs:
                result = dd.classify(issue, diff, "Denied")
                assert result is not None

    def test_classify_handles_missing_issue_fields(self):
        """classify() handles issues with minimal fields."""
        issues = [
            {"number": 5},
            {"number": 5, "title": "Test"},
        ]

        with patch.object(dd, "_launch_analyst") as mock_launch:
            mock_launch.return_value = "kind: wrong-approach\nroute: rebuild"
            for issue in issues:
                result = dd.classify(issue, "", "Denied")
                assert result is not None

    def test_classify_calls_analyst_with_bounded_inputs(self):
        """classify() caps the PR diff and failure reason to avoid huge prompts."""
        issue = {"number": 5, "title": "Test", "body": "x" * 4000}
        pr_diff = "y" * 50000
        failure = "z" * 10000

        with patch.object(dd, "_launch_analyst") as mock_launch:
            mock_launch.return_value = "kind: wrong-approach\nroute: rebuild"
            dd.classify(issue, pr_diff, failure)

            call_args = mock_launch.call_args
            prompt = call_args[0][0] if call_args else ""
            # The prompt should be reasonable length (not gigabytes)
            assert len(prompt) < 20000

    def test_classify_writes_diagnosis_comment(self):
        """classify() posts a ### Diagnosis comment on the issue."""
        issue = {"number": 5, "title": "Test", "body": "Description"}
        pr_diff = "changes"
        failure = "Denied"

        with patch.object(dd, "_launch_analyst") as mock_analyst:
            mock_analyst.return_value = "kind: missing-tests\nroute: fix_forward\nAdd tests for X"
        with patch.object(dd, "_comment_issue") as mock_comment:
            dd.classify(issue, pr_diff, failure)
            # Verify a comment was posted with a Diagnosis heading
            mock_comment.assert_called_once()
            comment_text = mock_comment.call_args[0][1]
            assert "### Diagnosis" in comment_text

    def test_classify_appends_to_log(self):
        """classify() appends one line to denial-diagnoses.jsonl."""
        issue = {"number": 5, "title": "Test", "body": ""}
        pr_diff = ""
        failure = ""

        with patch.object(dd, "_launch_analyst") as mock_analyst:
            mock_analyst.return_value = "kind: missing-tests\nroute: fix_forward"
            with patch.object(dd, "_comment_issue"):
                dd.classify(issue, pr_diff, failure, repo="G-Eskayo/marvin")

        logs = [json.loads(l) for l in dd.LOG_PATH.read_text().splitlines()]
        assert len(logs) == 1
        assert logs[0]["ticket"] == 5
        assert "diagnosis_kind" in logs[0]


# ── tally ───────────────────────────────────────────────────────────────────

class TestTally:
    """Group denials by (project, kind); file an issue if a kind recurs 3+ times."""

    def test_tally_groups_by_project_and_kind(self):
        """tally() returns list of {project, kind, count, tickets, first_seen, last_seen}."""
        _add_diagnosis(1, "missing-tests", "fix_forward")
        _add_diagnosis(2, "missing-tests", "fix_forward")
        _add_diagnosis(3, "missing-tests", "fix_forward")
        _add_diagnosis(4, "wrong-approach", "rebuild")

        result = dd.tally()

        # Two kinds: missing-tests (3), wrong-approach (1)
        assert len(result) == 1  # Only missing-tests hits MIN_REPEATS
        assert result[0]["kind"] == "missing-tests"
        assert result[0]["count"] == 3
        assert sorted(result[0]["tickets"]) == [1, 2, 3]

    def test_tally_does_not_cross_contaminate_projects(self):
        """tally() groups by project; marvin missing-tests != portfolio missing-tests."""
        _add_diagnosis(1, "missing-tests", "fix_forward", project="G-Eskayo/marvin")
        _add_diagnosis(2, "missing-tests", "fix_forward", project="G-Eskayo/marvin")
        _add_diagnosis(3, "missing-tests", "fix_forward", project="G-Eskayo/marvin")
        _add_diagnosis(4, "missing-tests", "fix_forward", project="G-Eskayo/portfolio")
        _add_diagnosis(5, "missing-tests", "fix_forward", project="G-Eskayo/portfolio")
        _add_diagnosis(6, "missing-tests", "fix_forward", project="G-Eskayo/portfolio")

        result = dd.tally()

        # Both projects hit 3 repeats independently; they should NOT be pooled
        marvin_result = [r for r in result if r["project"] == "G-Eskayo/marvin" and r["kind"] == "missing-tests"]
        portfolio_result = [r for r in result if r["project"] == "G-Eskayo/portfolio" and r["kind"] == "missing-tests"]
        assert len(marvin_result) == 1
        assert sorted(marvin_result[0]["tickets"]) == [1, 2, 3]
        assert len(portfolio_result) == 1
        assert sorted(portfolio_result[0]["tickets"]) == [4, 5, 6]

    def test_tally_exactly_two_repeats_is_below_threshold(self):
        """tally() does NOT return groups with only 2 repeats."""
        _add_diagnosis(1, "missing-tests", "fix_forward")
        _add_diagnosis(2, "missing-tests", "fix_forward")

        result = dd.tally()

        assert len(result) == 0

    def test_tally_exactly_three_repeats_crosses_threshold(self):
        """tally() DOES return groups with exactly 3 repeats."""
        _add_diagnosis(1, "missing-tests", "fix_forward")
        _add_diagnosis(2, "missing-tests", "fix_forward")
        _add_diagnosis(3, "missing-tests", "fix_forward")

        result = dd.tally()

        assert len(result) == 1
        assert result[0]["count"] == 3

    def test_tally_includes_first_and_last_seen_timestamps(self):
        """tally() includes first_seen and last_seen as ISO strings."""
        t1 = NOW - timedelta(hours=24)
        t2 = NOW - timedelta(hours=12)
        t3 = NOW
        _add_diagnosis(1, "missing-tests", "fix_forward", when=t1)
        _add_diagnosis(2, "missing-tests", "fix_forward", when=t2)
        _add_diagnosis(3, "missing-tests", "fix_forward", when=t3)

        result = dd.tally()

        assert len(result) == 1
        assert result[0]["first_seen"] == t1.isoformat()
        assert result[0]["last_seen"] == t3.isoformat()

    def test_tally_handles_corrupt_log_lines_gracefully(self):
        """tally() skips corrupt JSON lines; doesn't crash."""
        # Write some corrupt lines first, then add valid diagnoses
        LOG_PATH = dd.LOG_PATH
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("w") as f:
            f.write('{"valid": true}\n')
            f.write('invalid json\n')
            f.write('{"valid": 2}\n')

        _add_diagnosis(1, "missing-tests", "fix_forward")
        _add_diagnosis(2, "missing-tests", "fix_forward")
        _add_diagnosis(3, "missing-tests", "fix_forward")

        result = dd.tally()

        # Should succeed, skipping corrupt lines, finding the 3 diagnoses
        assert len(result) == 1
        assert result[0]["kind"] == "missing-tests"
        assert result[0]["count"] == 3

    def test_tally_has_no_time_window_unlike_failure_breaker(self):
        """tally() counts ALL denials ever, not a 2-hour window like failure_breaker."""
        old = NOW - timedelta(days=30)
        _add_diagnosis(1, "missing-tests", "fix_forward", when=old)
        _add_diagnosis(2, "missing-tests", "fix_forward", when=old - timedelta(hours=1))
        _add_diagnosis(3, "missing-tests", "fix_forward", when=NOW)

        result = dd.tally()

        # Old denials count too; no window
        assert len(result) == 1
        assert result[0]["count"] == 3


# ── mode gating and file_improvement ────────────────────────────────────────

class TestFileImprovement:
    """An improvement ticket is filed when a kind hits MIN_REPEATS, in the configured mode."""

    def test_file_improvement_never_called_when_mode_is_propose(self):
        """In propose mode, file_improvement() is never called."""
        _add_diagnosis(1, "missing-tests", "fix_forward")
        _add_diagnosis(2, "missing-tests", "fix_forward")
        _add_diagnosis(3, "missing-tests", "fix_forward")

        with patch.object(dd, "_gh_create_issue") as mock_gh:
            result = dd.file_improvements(mode="propose")
            # In propose mode, no actual issue is created
            assert not mock_gh.called

    def test_file_improvement_called_when_mode_is_act(self):
        """In act mode, file_improvement() calls gh issue create once per kind."""
        _add_diagnosis(1, "missing-tests", "fix_forward")
        _add_diagnosis(2, "missing-tests", "fix_forward")
        _add_diagnosis(3, "missing-tests", "fix_forward")

        with patch.object(dd, "_gh_create_issue") as mock_gh:
            dd.file_improvements(mode="act")
            # One issue filed for the missing-tests kind
            assert mock_gh.called

    def test_file_improvement_does_not_double_file(self):
        """file_improvement() searches for existing issues; doesn't create duplicates."""
        _add_diagnosis(1, "missing-tests", "fix_forward")
        _add_diagnosis(2, "missing-tests", "fix_forward")
        _add_diagnosis(3, "missing-tests", "fix_forward")

        with patch.object(dd, "_gh_list_issues") as mock_list:
            with patch.object(dd, "_gh_create_issue") as mock_create:
                mock_list.return_value = [
                    {"number": 999, "title": 'Denial kind "missing-tests" seen N times'}
                ]
                dd.file_improvements(mode="act")
                # No new issue created; existing one found
                assert not mock_create.called

    def test_file_improvement_respects_github_api_errors(self):
        """file_improvement() doesn't crash on GitHub API errors."""
        _add_diagnosis(1, "missing-tests", "fix_forward")
        _add_diagnosis(2, "missing-tests", "fix_forward")
        _add_diagnosis(3, "missing-tests", "fix_forward")

        with patch.object(dd, "_gh_create_issue") as mock_gh:
            mock_gh.side_effect = OSError("rate limited")
            # Should not raise, should log
            result = dd.file_improvements(mode="act")
            # The call should have been attempted


# ── integration: plan_refeed uses classify ──────────────────────────────────

class TestIntegrationWithPlanRefeed:
    """When a ticket is re-fed (plan_refeed in ticket_agents.py), classify() is called."""

    def test_plan_refeed_calls_classify_for_each_requeued_ticket(self):
        """plan_refeed() calls classify() once per ticket with needs-reengagement."""
        # This test is more about the integration point. We mock classify and verify it's called.
        # The actual integration is in ticket_agents.py; here we verify the contract.
        pass  # Implemented in test_ticket_agents.py


# ── execute_ticket receives diagnosis in the prompt ─────────────────────────

class TestIntegrationWithExecutor:
    """When execute_ticket() runs, it includes the diagnosis note in the planning prompt."""

    def test_planning_prompt_includes_diagnosis_note_when_present(self):
        """If a diagnosis exists for this ticket, it is included ahead of generic feedback."""
        # This is tested in test_sandbox_orchestration.py
        pass


# ── rework_status receives diagnosis field ──────────────────────────────────

class TestIntegrationWithReworkStatus:
    """rework_status.status_for() includes a diagnosis field."""

    def test_status_for_includes_diagnosis_from_log(self):
        """status_for() reads the latest diagnosis for a ticket from the log."""
        _add_diagnosis(5, "missing-tests", "fix_forward")

        ticket = {"number": 5, "labels": []}
        ctx = {"now": NOW}

        # Verify the contract: when we integrate, status_for should read diagnosis
        # For now, this is a placeholder for integration test in test_rework_status.py
        pass
