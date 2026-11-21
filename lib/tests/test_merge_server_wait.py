"""Wait-for-merge tests: polling /merge-queue until no merge is running or the bound is hit.

Covers decide(), _merge_running(), and the main() loop that calls them repeatedly.
Follows the same d(**kw) test idiom as test_webhook_restart.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import merge_server_wait as msw  # noqa: E402


BOUND_S = 2700


def d(**kw) -> tuple[str, str]:
    """Helper to call decide() with defaults."""
    base = dict(running=False, waited_s=0, bound_s=BOUND_S)
    base.update(kw)
    return msw.decide(**base)


# ---- decide() tests ----

def test_restarts_when_no_merge_is_running():
    action, reason = d()
    assert action == "restart"
    assert "no merge" in reason.lower()


def test_waits_while_a_merge_is_running_and_under_the_bound():
    action, reason = d(running=True, waited_s=0)
    assert action == "wait"
    assert "running" in reason.lower()


def test_restarts_anyway_once_the_bound_is_reached_even_if_still_running():
    """The ticket's explicit break-it case: waited_s >= bound_s with running=True."""
    action, reason = d(running=True, waited_s=BOUND_S)
    assert action == "restart"
    assert "bound" in reason.lower()

    # Also test slightly over the bound
    action, reason = d(running=True, waited_s=BOUND_S + 10)
    assert action == "restart"


def test_every_decision_carries_a_human_readable_reason():
    """Every branch of decide() must return a non-empty reason."""
    for kw in ({}, {"running": True, "waited_s": 0}, {"running": True, "waited_s": BOUND_S}):
        action, reason = d(**kw)
        assert isinstance(reason, str)
        assert len(reason) > 0


# ---- _merge_running() tests ----

def test_merge_running_false_when_the_server_is_unreachable_after_retrying():
    """urlopen fails on every attempt; never raises."""
    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.side_effect = OSError("Connection refused")
        result = msw._merge_running(timeout=0.001, retries=2)
        assert result is False
        assert mock_urlopen.call_count == 2


def test_merge_running_true_on_the_first_successful_attempt_after_an_earlier_failure():
    """First attempt fails, second succeeds with running set."""
    with patch('urllib.request.urlopen') as mock_urlopen:
        # First call fails, second succeeds with running=True
        second_response = MagicMock()
        second_response.read.return_value = b'{"repos": {"owner/repo": {"running": true}}}'

        # Configure side effects
        mock_urlopen.side_effect = [OSError("Connection refused"), second_response]

        result = msw._merge_running(timeout=0.001, retries=2)
        assert result is True
        assert mock_urlopen.call_count == 2


def test_merge_running_false_on_malformed_json():
    """Non-JSON body returns False, never raises."""
    with patch('urllib.request.urlopen') as mock_urlopen:
        response = MagicMock()
        response.read.return_value = b'not valid json'
        mock_urlopen.return_value = response

        result = msw._merge_running(timeout=0.001, retries=1)
        assert result is False


def test_merge_running_true_when_any_repo_has_a_running_pr():
    """Parses {repos: {...}} shape correctly."""
    with patch('urllib.request.urlopen') as mock_urlopen:
        response = MagicMock()
        response.read.return_value = b'{"repos": {"owner1/repo1": {"running": false}, "owner2/repo2": {"running": true}}}'
        mock_urlopen.return_value = response

        result = msw._merge_running(timeout=0.001, retries=1)
        assert result is True


def test_merge_running_false_when_nothing_is_running():
    """All repos have running=false returns False."""
    with patch('urllib.request.urlopen') as mock_urlopen:
        response = MagicMock()
        response.read.return_value = b'{"repos": {"owner/repo": {"running": false}}}'
        mock_urlopen.return_value = response

        result = msw._merge_running(timeout=0.001, retries=1)
        assert result is False


def test_decide_calls_are_independent():
    """Two decide() calls with different args give independent answers (statelessness)."""
    result1 = d(running=True, waited_s=0)
    result2 = d(running=False, waited_s=BOUND_S)

    assert result1[0] == "wait"
    assert result2[0] == "restart"


# ---- main() loop tests ----

def test_main_polls_until_restart_then_exits():
    """main() sleeps and polls until decide() returns 'restart', then exits."""
    poll_results = [True, True, False]  # running, running, not running → restart
    poll_index = [0]
    sleep_calls = []

    def mock_merge_running(*args, **kwargs):
        result = poll_results[poll_index[0]]
        poll_index[0] += 1
        return result

    def mock_sleep(seconds):
        sleep_calls.append(seconds)

    mock_job_context = MagicMock()
    mock_job = MagicMock()
    mock_job.job_run.return_value.__enter__ = MagicMock(return_value=mock_job_context)
    mock_job.job_run.return_value.__exit__ = MagicMock(return_value=None)

    with patch.object(msw, '_merge_running', side_effect=mock_merge_running):
        with patch.object(msw, 'time') as mock_time_module:
            mock_time_module.sleep = mock_sleep
            mock_time_module.monotonic.side_effect = [0, 5, 10, 10]
            with patch.dict('sys.modules', {'job_events': mock_job}):
                msw.main()

    # Should have slept twice (after first and second poll)
    assert len(sleep_calls) == 2
    assert poll_index[0] == 3  # Polled 3 times


def test_main_exits_immediately_when_nothing_is_running():
    """_merge_running returns False on first call; assert zero sleeps."""
    sleep_calls = []

    def mock_sleep(seconds):
        sleep_calls.append(seconds)

    mock_job_context = MagicMock()
    mock_job = MagicMock()
    mock_job.job_run.return_value.__enter__ = MagicMock(return_value=mock_job_context)
    mock_job.job_run.return_value.__exit__ = MagicMock(return_value=None)

    with patch.object(msw, '_merge_running', return_value=False):
        with patch.object(msw, 'time') as mock_time_module:
            mock_time_module.sleep = mock_sleep
            mock_time_module.monotonic.side_effect = [0, 0]
            with patch.dict('sys.modules', {'job_events': mock_job}):
                msw.main()

    # Should not have slept
    assert len(sleep_calls) == 0


def test_main_restarts_at_the_bound_even_if_still_running():
    """main() respects the monotonic-time bound, restarting when elapsed >= bound_s."""
    poll_results = [True, True, True]  # Always running
    poll_index = [0]

    def mock_merge_running(*args, **kwargs):
        result = poll_results[poll_index[0]]
        poll_index[0] += 1
        return result

    sleep_calls = []

    def mock_sleep(seconds):
        sleep_calls.append(seconds)

    mock_job_context = MagicMock()
    mock_job = MagicMock()
    mock_job.job_run.return_value.__enter__ = MagicMock(return_value=mock_job_context)
    mock_job.job_run.return_value.__exit__ = MagicMock(return_value=None)

    with patch.object(msw, '_merge_running', side_effect=mock_merge_running):
        with patch.object(msw, 'time') as mock_time_module:
            mock_time_module.sleep = mock_sleep
            # Simulate: 0s, 5s (still waiting), 15s (bound crossed, restart)
            mock_time_module.monotonic.side_effect = [0, 5, 15, 15]
            with patch.dict('sys.modules', {'job_events': mock_job}):
                # Patch the bound to be small for testing
                with patch.object(msw, 'WAIT_BOUND_S', 10):
                    msw.main()

    # Should have slept once (after first poll), then on second poll the bound was hit
    assert len(sleep_calls) == 1
    assert poll_index[0] == 2  # Polled twice before bound was hit
