import pytest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import box_runner


@pytest.fixture
def tmp_log(tmp_path):
    """Temporarily redirect LOG to a test location."""
    log_path = tmp_path / "box-runs.jsonl"
    with patch.object(box_runner, "LOG", log_path):
        yield log_path


@pytest.fixture
def tmp_proposals(tmp_path):
    """Temporarily redirect PROPOSALS_ROOT to a test location."""
    proposals_root = tmp_path / "proposals"
    with patch.object(box_runner, "PROPOSALS_ROOT", proposals_root):
        yield proposals_root


def box_line(event: str, **kw) -> dict:
    """Helper to create a box_runner log entry."""
    return {"event": event, **kw}


def verdict(outcome: str, sha: str = "abc123") -> dict:
    """Helper to create a verdict log entry."""
    return {"event": "verdict", "outcome": outcome, "sha": sha}


class TestAgreementStreak:
    """Tests for the agreement_streak() function."""

    def test_agreement_streak_counts_consecutive_trues_from_the_end(self, tmp_log):
        """Rows [T,T,F,T,T,T] should return streak of 3 (the last three trues)."""
        rows = [
            box_line("compare", agree=True),
            box_line("compare", agree=True),
            box_line("compare", agree=False),
            box_line("compare", agree=True),
            box_line("compare", agree=True),
            box_line("compare", agree=True),
        ]
        assert box_runner.agreement_streak(rows) == 3

    def test_agreement_streak_skips_none_without_breaking_it(self, tmp_log):
        """A None in the middle of trues doesn't end the streak."""
        rows = [
            box_line("compare", agree=True),
            box_line("compare", agree=True),
            box_line("compare", agree=None),
            box_line("compare", agree=True),
            box_line("compare", agree=True),
        ]
        assert box_runner.agreement_streak(rows) == 4

    def test_agreement_streak_is_zero_on_an_empty_log(self, tmp_log):
        """Empty or missing log should return 0."""
        assert box_runner.agreement_streak([]) == 0
        assert box_runner.agreement_streak(None) == 0

    def test_a_corrupt_log_line_is_skipped_when_counting_the_streak(self, tmp_log):
        """Malformed JSON is ignored, not crashed on."""
        # Write some corrupt data to the log
        tmp_log.parent.mkdir(parents=True, exist_ok=True)
        with tmp_log.open("w") as f:
            f.write('{"event": "compare", "agree": true}\n')
            f.write('this is not json\n')
            f.write('{"event": "compare", "agree": true}\n')
        rows = box_runner._lines()
        assert box_runner.agreement_streak(rows) == 2


class TestTrustProposal:
    """Tests for the trust proposal mechanism."""

    def test_19_clean_gates_do_not_propose(self, tmp_log, tmp_proposals):
        """19 agreeing compares should not trigger a proposal."""
        # Add 19 compare records with agree=True
        for i in range(19):
            box_runner._append({"event": "compare", "agree": True, "sha": f"sha{i}"})

        box_runner._maybe_propose_trust()

        # No proposal file should be created
        assert list(tmp_proposals.glob("*.json")) == []
        # No trust-proposed marker should exist
        rows = box_runner._lines()
        assert not any(r.get("event") == "trust-proposed" for r in rows)

    def test_the_20th_clean_gate_proposes_once(self, tmp_log, tmp_proposals):
        """The 20th agreeing compare should create exactly one proposal and one marker."""
        # Add 20 compare records with agree=True
        for i in range(20):
            box_runner._append({"event": "compare", "agree": True, "sha": f"sha{i}"})

        box_runner._maybe_propose_trust()

        # Exactly one proposal file should be created
        proposal_files = list(tmp_proposals.glob("*.json"))
        assert len(proposal_files) == 1

        # The proposal file should contain valid content
        content = proposal_files[0].read_text()
        assert "Gate box runner" in content or "mac-mini-2012" in content

        # Exactly one successful trust-proposed marker should exist
        rows = box_runner._lines()
        proposed = [r for r in rows if r.get("event") == "trust-proposed" and r.get("ok") is True]
        assert len(proposed) == 1

    def test_the_21st_clean_gate_does_not_propose_again(self, tmp_log, tmp_proposals):
        """After 20 gates propose once, the 21st should not create another proposal."""
        # Add 21 compare records
        for i in range(21):
            box_runner._append({"event": "compare", "agree": True, "sha": f"sha{i}"})

        # Propose once
        box_runner._maybe_propose_trust()
        proposal_files_after_20 = list(tmp_proposals.glob("*.json"))
        assert len(proposal_files_after_20) == 1

        # Try to propose again (simulating a restart or next call)
        box_runner._maybe_propose_trust()
        proposal_files_after_21 = list(tmp_proposals.glob("*.json"))
        assert len(proposal_files_after_21) == 1

        # Only one successful marker should exist
        rows = box_runner._lines()
        proposed = [r for r in rows if r.get("event") == "trust-proposed" and r.get("ok") is True]
        assert len(proposed) == 1

    def test_a_disagreement_then_a_fresh_streak_of_20_does_not_re_propose(self, tmp_log, tmp_proposals):
        """Proposing is one-shot forever, not per-streak."""
        # Add 20 agrees, propose
        for i in range(20):
            box_runner._append({"event": "compare", "agree": True, "sha": f"sha{i}"})
        box_runner._maybe_propose_trust()

        # Add a disagreement
        box_runner._append({"event": "compare", "agree": False, "sha": "shaf"})

        # Add 20 more agrees
        for i in range(20, 40):
            box_runner._append({"event": "compare", "agree": True, "sha": f"sha{i}"})

        # Try to propose again
        box_runner._maybe_propose_trust()

        # Still only one proposal file and one marker
        proposal_files = list(tmp_proposals.glob("*.json"))
        assert len(proposal_files) == 1
        rows = box_runner._lines()
        proposed = [r for r in rows if r.get("event") == "trust-proposed" and r.get("ok") is True]
        assert len(proposed) == 1

    def test_proposals_add_failing_does_not_crash_compare(self, tmp_log, tmp_proposals):
        """If proposals.add() raises, _maybe_propose_trust() should log an error and not crash."""
        # Add 19 agrees (not 20 yet) with corresponding verdicts and create compare records via compare()
        for i in range(19):
            box_runner._append({"event": "passed", "sha": f"sha{i}"})
            box_runner._append({"event": "verdict", "sha": f"sha{i}", "outcome": "passed", "tests": []})
            box_runner.compare(f"sha{i}")

        # Mock sys.modules to make proposals.add fail when called
        import sys
        mock_proposals = Mock()
        mock_proposals.add = Mock(side_effect=RuntimeError("proposals module broke"))

        with patch.dict(sys.modules, {"proposals": mock_proposals}):
            # Call compare for the 20th time to trigger _maybe_propose_trust inside the mock context
            box_runner._append({"event": "passed", "sha": "sha19"})
            box_runner._append({"event": "verdict", "sha": "sha19", "outcome": "passed", "tests": []})
            result = box_runner.compare("sha19")
            # The compare should succeed
            assert result is not None

        # An error marker should be logged
        rows = box_runner._lines()
        errors = [r for r in rows if r.get("event") == "trust-proposed" and "error" in r]
        assert len(errors) == 1
        assert "proposals module broke" in errors[0].get("error", "")

        # On the 21st compare, _maybe_propose_trust should NOT retry (marker prevents it)
        box_runner._append({"event": "passed", "sha": "sha20"})
        box_runner._append({"event": "verdict", "sha": "sha20", "outcome": "passed", "tests": []})
        result2 = box_runner.compare("sha20")
        assert result2 is not None

        # proposals.add should only have been called once (not twice)
        assert mock_proposals.add.call_count == 1

    def test_an_unwritable_proposals_root_does_not_crash_compare(self, tmp_log, tmp_proposals):
        """Read-only PROPOSALS_ROOT should not crash; error logged but not retried."""
        # Add 19 agrees (not 20 yet) with corresponding verdicts and create compare records via compare()
        for i in range(19):
            box_runner._append({"event": "passed", "sha": f"sha{i}"})
            box_runner._append({"event": "verdict", "sha": f"sha{i}", "outcome": "passed", "tests": []})
            box_runner.compare(f"sha{i}")

        # Mock sys.modules to simulate permission error
        import sys
        mock_proposals = Mock()
        mock_proposals.add = Mock(side_effect=PermissionError("cannot write to proposals root"))

        with patch.dict(sys.modules, {"proposals": mock_proposals}):
            # Call compare for the 20th time to trigger _maybe_propose_trust inside the mock context
            box_runner._append({"event": "passed", "sha": "sha19"})
            box_runner._append({"event": "verdict", "sha": "sha19", "outcome": "passed", "tests": []})
            result = box_runner.compare("sha19")
            # The compare should succeed
            assert result is not None

        # Error should be logged
        rows = box_runner._lines()
        errors = [r for r in rows if r.get("event") == "trust-proposed" and "error" in r]
        assert len(errors) == 1

        # On the 21st compare, should NOT retry (the marker prevents it)
        box_runner._append({"event": "passed", "sha": "sha20"})
        box_runner._append({"event": "verdict", "sha": "sha20", "outcome": "passed", "tests": []})
        result2 = box_runner.compare("sha20")
        assert result2 is not None

        # proposals.add should only have been called once (not twice)
        assert mock_proposals.add.call_count == 1

    def test_a_stale_trust_proposed_marker_from_a_restart_still_suppresses_a_new_proposal(self, tmp_log, tmp_proposals):
        """A restart with a successful marker in the log should not re-propose."""
        # Pre-seed with 20 agrees and a successful marker
        for i in range(20):
            box_runner._append({"event": "compare", "agree": True, "sha": f"sha{i}"})
        box_runner._append({"event": "trust-proposed", "ok": True, "sha": "HEAD"})

        # Try to propose again (simulating process restart)
        box_runner._maybe_propose_trust()

        # No new proposal file should be created
        proposal_files = list(tmp_proposals.glob("*.json"))
        assert len(proposal_files) == 0  # Never created due to marker check

        # Only one successful marker
        rows = box_runner._lines()
        proposed = [r for r in rows if r.get("event") == "trust-proposed" and r.get("ok") is True]
        assert len(proposed) == 1

    def test_two_gates_crossing_the_threshold_at_once_propose_only_once(self, tmp_log, tmp_proposals):
        """Concurrent compare() calls at the 20th threshold should create only one proposal."""
        import threading

        # Set up 19 agreed compares so the next one will trigger the threshold
        for i in range(19):
            box_runner._append({"event": "passed", "sha": f"sha{i}"})
            box_runner._append({"event": "verdict", "sha": f"sha{i}", "outcome": "passed", "tests": []})
            box_runner.compare(f"sha{i}")

        proposal_count = [0]

        def counting_add(*args, **kwargs):
            proposal_count[0] += 1
            (tmp_proposals).mkdir(parents=True, exist_ok=True)
            (tmp_proposals / f"proposal_{proposal_count[0]}.json").write_text("test")

        import sys
        mock_proposals = Mock()
        mock_proposals.add = counting_add

        with patch.dict(sys.modules, {"proposals": mock_proposals}):
            # Simulate two threads calling compare() at the same time from the 20th compare
            barrier = threading.Barrier(2)
            barrier2 = threading.Barrier(2)

            def thread_func(i):
                # Set up the condition first (both threads do this independently)
                box_runner._append({"event": "passed", "sha": f"sha{20+i}"})
                box_runner._append({"event": "verdict", "sha": f"sha{20+i}", "outcome": "passed", "tests": []})
                # Wait for both threads to be ready
                barrier.wait()
                # Both call compare at the same time (with locking, only one should win the lock first)
                box_runner.compare(f"sha{20+i}")
                barrier2.wait()

            threads = [threading.Thread(target=thread_func, args=(i,)) for i in range(2)]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Only one proposal should be created (proposals.add called once, thanks to the lock)
        assert proposal_count[0] == 1, f"proposals.add called {proposal_count[0]} times, expected 1"
        rows = box_runner._lines()
        proposed = [r for r in rows if r.get("event") == "trust-proposed" and r.get("ok") is True]
        assert len(proposed) == 1  # Only one successful proposal marker


class TestCompare:
    """Tests for the compare() function."""

    def test_compare_sets_agree_to_none_on_box_timeout(self, tmp_log):
        """When the box times out, agree should be None (no result)."""
        box_runner._append({"event": "timeout", "sha": "sha1"})
        box_runner._append({"event": "verdict", "sha": "sha1", "outcome": "passed", "tests": []})
        result = box_runner.compare("sha1")
        assert result is not None
        assert result.get("agree") is None

    def test_compare_sets_agree_to_none_on_box_offline(self, tmp_log):
        """When the box is offline, agree should be None (no result)."""
        box_runner._append({"event": "offline", "sha": "sha1"})
        box_runner._append({"event": "verdict", "sha": "sha1", "outcome": "failed", "tests": []})
        result = box_runner.compare("sha1")
        assert result is not None
        assert result.get("agree") is None

    def test_compare_sets_agree_to_none_on_box_error(self, tmp_log):
        """When the box has an error, agree should be None (no result)."""
        box_runner._append({"event": "error", "sha": "sha1"})
        box_runner._append({"event": "verdict", "sha": "sha1", "outcome": "passed", "tests": []})
        result = box_runner.compare("sha1")
        assert result is not None
        assert result.get("agree") is None

    def test_compare_returns_none_if_already_compared(self, tmp_log):
        """Calling compare() twice for the same sha should skip on the second call."""
        box_runner._append({"event": "passed", "sha": "sha1"})
        box_runner._append({"event": "verdict", "sha": "sha1", "outcome": "passed", "tests": []})

        result1 = box_runner.compare("sha1")
        assert result1 is not None

        result2 = box_runner.compare("sha1")
        assert result2 is None

    def test_compare_finds_earlier_compares_not_just_the_last(self, tmp_log):
        """If sha was compared before (but not most recently), it should not be re-compared."""
        box_runner._append({"event": "passed", "sha": "sha1"})
        box_runner._append({"event": "verdict", "sha": "sha1", "outcome": "passed", "tests": []})
        box_runner.compare("sha1")  # Compare sha1

        # Add compares for other shas
        box_runner._append({"event": "passed", "sha": "sha2"})
        box_runner._append({"event": "verdict", "sha": "sha2", "outcome": "passed", "tests": []})
        box_runner.compare("sha2")

        # Try to compare sha1 again - should return None because it's already been compared
        result = box_runner.compare("sha1")
        assert result is None

    def test_compare_returns_true_on_agreement(self, tmp_log):
        """When box and mac both pass, agree should be True."""
        box_runner._append({"event": "passed", "sha": "sha1"})
        box_runner._append({"event": "verdict", "sha": "sha1", "outcome": "passed", "tests": []})
        result = box_runner.compare("sha1")
        assert result is not None
        assert result.get("agree") is True

    def test_compare_returns_false_on_disagreement(self, tmp_log):
        """When box and mac disagree, agree should be False."""
        box_runner._append({"event": "passed", "sha": "sha1"})
        box_runner._append({"event": "verdict", "sha": "sha1", "outcome": "failed", "tests": ["test1"]})
        result = box_runner.compare("sha1")
        assert result is not None
        assert result.get("agree") is False


class TestRunExitCodes:
    """Tests for exit code handling in run()."""

    def test_exit_code_3_is_classified_as_error_not_failed(self, tmp_log):
        """Exit code 3 should be error (hand-off failed), not failed (tests failed)."""
        import subprocess

        # Mock subprocess.run to return exit code 3 (hand-off failure)
        mock_process = Mock()
        mock_process.returncode = 3
        mock_process.stdout = b"some output"

        with patch("subprocess.run", return_value=mock_process):
            with patch("box_runner.box_head", return_value="abc123def45"):
                with patch("box_runner.make_bundle", return_value=b"bundle_data"):
                    # Call run() which should handle exit code 3 as "error"
                    box_runner.run("run_id_1", "/path/to/repo", "sha123", "test-label")

        # Check that the outcome was logged as "error", not "failed"
        rows = box_runner._lines()
        run_events = [r for r in rows if r.get("event") == "error" and r.get("id") == "run_id_1"]
        assert len(run_events) >= 1, "Should have logged an error event for exit code 3"


class TestFailingTests:
    """Tests for the failing_tests() function."""

    def test_failing_tests_extracts_from_pytest_output(self):
        """Test names should be extracted from pytest short summary."""
        output = """FAILED tests/foo.py::test_bar - reason
ERROR tests/baz.py::test_qux
some other output
FAILED tests/qux.py::test_zap - another reason"""
        tests = box_runner.failing_tests(output)
        assert sorted(tests) == ["tests/baz.py::test_qux", "tests/foo.py::test_bar", "tests/qux.py::test_zap"]

    def test_failing_tests_returns_empty_on_no_failures(self):
        """When there are no failures, return empty list."""
        output = "all tests passed"
        tests = box_runner.failing_tests(output)
        assert tests == []


class TestShow:
    """Tests for the show() function."""

    def test_show_puts_disagreements_first(self, tmp_log, capsys):
        """Disagreements should be printed before agreements."""
        box_runner._append({"event": "compare", "agree": True, "sha": "sha1"})
        box_runner._append({"event": "compare", "agree": False, "sha": "sha2"})
        box_runner._append({"event": "compare", "agree": True, "sha": "sha3"})

        box_runner.show()
        captured = capsys.readouterr()

        lines = captured.out.strip().split("\n")
        # Disagreement should come first
        assert "sha2" in lines[0]
        assert "✗" in lines[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
