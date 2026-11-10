import pytest
from unittest.mock import patch, MagicMock
import urllib.error
import json

# Import the module under test
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from merge_server_wait import _merge_running, decide


class TestDecide:
    """Tests for the decide() function."""

    def test_no_running_merge_returns_restart(self):
        """Test 1: When no merge is running, return 'restart'."""
        result = decide(running=False, waited_s=0, bound_s=2700)
        assert result == "restart"

    def test_running_merge_with_time_left_returns_none(self):
        """Test 2: When merge is running with time left, return None."""
        result = decide(running=True, waited_s=100, bound_s=2700)
        assert result is None

    def test_running_merge_at_time_bound_returns_restart(self):
        """Test 3: When time bound is reached, return 'restart' even if merge running."""
        result = decide(running=True, waited_s=2700, bound_s=2700)
        assert result == "restart"

    def test_running_merge_exceeds_time_bound_returns_restart(self):
        """Test 3b: When waited time exceeds bound, return 'restart'."""
        result = decide(running=True, waited_s=2800, bound_s=2700)
        assert result == "restart"


class TestMergeRunning:
    """Tests for the _merge_running() function."""

    def test_empty_repos_returns_false(self):
        """Test 4: Empty repos object means no merge running."""
        response_data = {'repos': {}}
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(response_data).encode('utf-8')
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = _merge_running()
            assert result is False

    def test_repo_with_running_merge_returns_true(self):
        """Test 5: When a merge is running, return True."""
        response_data = {
            'repos': {
                'G-Eskayo/marvin': {
                    'running': 'https://github.com/G-Eskayo/marvin/pull/123'
                }
            }
        }
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(response_data).encode('utf-8')
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = _merge_running()
            assert result is True

    def test_network_error_returns_false_fail_open(self):
        """Test 6: Network error fails open, returns False."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError('Connection refused')

            result = _merge_running()
            assert result is False

    def test_json_decode_error_returns_false_fail_open(self):
        """Test 7: Invalid JSON fails open, returns False."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'not valid json'
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = _merge_running()
            assert result is False

    def test_timeout_returns_false_fail_open(self):
        """Test 8: Timeout fails open, returns False."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError('Request timed out')

            result = _merge_running()
            assert result is False

    def test_repo_without_running_returns_false(self):
        """Test 5b: Repo exists but no running merge."""
        response_data = {
            'repos': {
                'G-Eskayo/marvin': {
                    'items': [],
                    'failed': {}
                }
            }
        }
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(response_data).encode('utf-8')
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = _merge_running()
            assert result is False
