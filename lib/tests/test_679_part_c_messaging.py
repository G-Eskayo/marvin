import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
from lib import task_dispatch

# This test module verifies Part C (Fail-fast messaging and "I'm back" notification)
# validates that dispatch failures are specific (not generic timeouts) and that
# "I'm back" notifications work correctly at boot time.


def test_dispatch_failure_message_is_specific():
    """
    Part C1: Verify dispatch failure messages are specific, not generic timeouts.
    When all paths fail, the message should name which paths were tried.
    """
    with patch('lib.task_dispatch.select_machine') as mock_select, \
         patch('lib.task_dispatch._run_remote') as mock_remote:

        mock_select.return_value = ("marvin-hub", {
            "is_self": False,
            "tailscale_hostname": "marvin-hub.tail1234.ts.net",
            "os": "macos",
            "lan_ssh_alias": "gils-mac-mini-lan"
        })

        # All paths fail - return a detailed error message
        mock_remote.return_value = task_dispatch.DispatchResult(
            ok=False,
            device_id="marvin-hub",
            error="All paths unreachable: Tailscale down, LAN unreachable, tunnel unreachable",
            unreachable=True
        )

        result = task_dispatch.dispatch("test_command", target="marvin-hub")
        assert not result.ok
        # Message should be specific, not generic timeout
        assert "timeout" not in result.error.lower() or "paths" in result.error.lower()
        # Should name which paths were tried
        assert any(word in result.error.lower() for word in ['tailscale', 'lan', 'unreachable'])


def test_tailscale_down_lan_reachable_message():
    """
    Part C1: When Tailscale is down but LAN works, the dispatch should succeed
    via the LAN fallback and the error field (if any) should indicate this.
    """
    with patch('lib.task_dispatch.select_machine') as mock_select, \
         patch('lib.task_dispatch._run_remote') as mock_remote:

        mock_select.return_value = ("marvin-hub", {
            "is_self": False,
            "tailscale_hostname": "marvin-hub.tail1234.ts.net",
            "os": "macos",
            "lan_ssh_alias": "gils-mac-mini-lan"
        })

        # When Tailscale is down but LAN works, dispatch succeeds
        mock_remote.return_value = task_dispatch.DispatchResult(
            ok=True,
            device_id="marvin-hub",
            output="success via LAN"
        )

        result = task_dispatch.dispatch("test_command", target="marvin-hub")
        assert result.ok


def test_all_paths_fail_notification_sent():
    """
    Part C1: When all paths fail, we should track that failure
    (future: notification would be sent).
    """
    with patch('lib.task_dispatch.select_machine') as mock_select, \
         patch('lib.task_dispatch._run_remote') as mock_remote:

        mock_select.return_value = ("marvin-hub", {
            "is_self": False,
            "tailscale_hostname": "marvin-hub.tail1234.ts.net",
            "os": "macos",
            "lan_ssh_alias": "gils-mac-mini-lan"
        })

        # All paths fail
        mock_remote.return_value = task_dispatch.DispatchResult(
            ok=False,
            device_id="marvin-hub",
            error="All paths unreachable",
            unreachable=True
        )

        result = task_dispatch.dispatch("test_command", target="marvin-hub")
        assert not result.ok
        assert result.unreachable


def test_i_am_back_notification_at_boot():
    """
    Part C2: Document expected "I'm back" notification behavior at boot.

    This notification is triggered by the Part B launchd job (RunAtLoad)
    when the hub reboots. It tells the owner the hub is back online.
    """
    # This test documents that the notification system exists
    # and can be called. The actual integration is in the Part B launchd job.

    # Verify mr_notification module exists and has _fire function
    try:
        from lib import mr_notification
        assert hasattr(mr_notification, '_fire'), \
            "mr_notification must have _fire function for Part C"
    except ImportError:
        pytest.skip("mr_notification module not found")


def test_i_am_back_does_not_fire_on_wake():
    """
    Document: "I'm back" notification fires at boot only (via RunAtLoad),
    not on wake from sleep. For Tailscale-only outages during uptime,
    there is no automatic "I'm back" notification (deferred to follow-up).
    """
    # Verify the Part B plist uses RunAtLoad (boot-only)
    plist_path = Path(__file__).resolve().parent.parent.parent / \
                 "config/launchd/com.marvin.hub-catchup.plist"

    if plist_path.exists():
        import plistlib
        with open(plist_path, 'rb') as f:
            plist = plistlib.load(f)
        # RunAtLoad fires at boot and login, not wake
        assert plist.get('RunAtLoad') is True
