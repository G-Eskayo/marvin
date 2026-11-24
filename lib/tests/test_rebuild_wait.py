import pytest
from unittest.mock import patch, MagicMock

# Import the module under test
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rebuild_wait import decide, _rebuild_running


class TestDecide:
    """Tests for the decide() function."""

    def test_no_running_rebuild_returns_proceed(self):
        """Test 1: When no rebuild is running, return 'proceed'."""
        result = decide(running=False, waited_s=0, bound_s=600)
        assert result == "proceed"

    def test_running_rebuild_with_time_left_returns_none(self):
        """Test 2: When rebuild is running with time left, return None."""
        result = decide(running=True, waited_s=100, bound_s=600)
        assert result is None

    def test_running_rebuild_at_time_bound_returns_proceed(self):
        """Test 3: When time bound is reached, return 'proceed' even if rebuild running."""
        result = decide(running=True, waited_s=600, bound_s=600)
        assert result == "proceed"

    def test_running_rebuild_exceeds_time_bound_returns_proceed(self):
        """Test 3b: When waited time exceeds bound, return 'proceed'."""
        result = decide(running=True, waited_s=700, bound_s=600)
        assert result == "proceed"


class TestRebuildRunning:
    """Tests for the _rebuild_running() function."""

    def test_no_running_process_returns_false(self):
        """Test 4: When pgrep finds no matching process, return False."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = _rebuild_running()
            assert result is False

    def test_running_process_returns_true(self):
        """Test 5: When pgrep finds a matching process, return True."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='12345\n')
            result = _rebuild_running()
            assert result is True

    def test_exclude_own_pid(self):
        """Test 6: When only our own PID is running, return False."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='12345\n')
            result = _rebuild_running(exclude_pid=12345)
            assert result is False

    def test_multiple_pids_with_exclude(self):
        """Test 7: When multiple PIDs are running but only ours is excluded, return True."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='12345\n67890\n')
            result = _rebuild_running(exclude_pid=12345)
            assert result is True

    def test_exception_returns_false_fail_open(self):
        """Test 8: On exception, fail open and return False."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception('Process error')
            result = _rebuild_running()
            assert result is False

    def test_empty_pids_list(self):
        """Test 9: When stdout is empty, return False."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='')
            result = _rebuild_running()
            assert result is False
