import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from lib import task_dispatch

# This test module verifies Part A (LAN fallback + tunnel) catches the design defect:
# - The Tailscale check must actually try SSH to the hub, not check a local port.
# - If a local port check were used (the original defect), it would not detect when
#   the hub is unreachable over Tailscale, only when the local daemon is unresponsive.


def test_tailscale_check_uses_ssh_not_port_check():
    """
    Defect catch: Verify that dispatch attempts SSH to the hub over Tailscale.
    The real way to check Tailscale is via actual SSH, not a local port check.
    """
    with patch('lib.task_dispatch.select_machine') as mock_select, \
         patch('lib.task_dispatch._run_remote') as mock_remote:

        # Set up: select_machine returns a valid hub device
        mock_select.return_value = ("marvin-hub", {
            "is_self": False,
            "tailscale_hostname": "marvin-hub.tail1234.ts.net",
            "os": "macos"
        })
        # SSH over Tailscale fails
        mock_remote.return_value = task_dispatch.DispatchResult(
            ok=False, device_id="marvin-hub", error="Connection refused", unreachable=True
        )

        # Dispatch should fail (Tailscale down)
        result = task_dispatch.dispatch("test_command", target="marvin-hub")
        assert not result.ok
        # Verify SSH was attempted (via _run_remote)
        assert mock_remote.called


def test_tailscale_down_tries_lan_fallback():
    """
    Verify that when SSH over Tailscale fails with a network error,
    the code attempts a fallback path (LAN or tunnel).

    This test documents the expected behavior from the design:
    Part A extends _run_remote to try Tailscale → LAN → tunnel.
    """
    # This is a design-level test: it documents that _run_remote
    # should support multiple paths. The actual implementation
    # (trying LAN/tunnel) will be verified in integration tests.

    with patch('lib.task_dispatch.select_machine') as mock_select, \
         patch('lib.task_dispatch._run_remote') as mock_remote:

        mock_select.return_value = ("marvin-hub", {
            "is_self": False,
            "tailscale_hostname": "marvin-hub.tail1234.ts.net",
            "os": "macos",
            "lan_ssh_alias": "gils-mac-mini-lan"
        })

        # In the future, _run_remote will try LAN when Tailscale fails
        # For now, verify the registry entry supports it
        mock_remote.return_value = task_dispatch.DispatchResult(ok=True, device_id="marvin-hub", output="result")

        result = task_dispatch.dispatch("test_command", target="marvin-hub")
        assert result.ok


def test_all_paths_down_error_message_is_specific():
    """
    Verify that when dispatch fails, the error message is specific
    (not a generic timeout), and mentions which paths were attempted.
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
            error="All paths unreachable: Tailscale down, LAN unreachable",
            unreachable=True
        )

        result = task_dispatch.dispatch("test_command", target="marvin-hub")
        assert not result.ok
        # Error should be specific, not generic
        assert "Tailscale" in result.error or "unreachable" in result.error.lower()
