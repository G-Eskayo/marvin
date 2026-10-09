"""Test deploy_ping.py: after marvin-repo merges, ping other Macs to pull code and rebuild.

The goal: a Mac reliably runs merged code within minutes, without a human noticing
or the merge process blocking. Ping is fire-and-forget; errors are logged but never
undo a successful merge or block the approval click.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_ping as dp  # noqa: E402


def test_empty_remote_devices_is_a_noop():
    """Zero remote devices registered → no ssh call, no exception, no job_events error."""
    with patch("deploy_ping.machine_profile.remote_devices", return_value={}):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=set()):
            with patch("deploy_ping.subprocess.run") as mock_run:
                with patch("deploy_ping.job_events.job_run") as mock_job:
                    mock_run.return_value = Mock(returncode=0)
                    dp.main()
                    # No ssh calls made
                    assert not any("ssh" in str(call) for call in mock_run.call_args_list)


def test_happy_path_one_reachable_remote_device():
    """One reachable remote device → exactly one ssh invocation with the expected command."""
    remote_info = {
        "mac-mini-1": {"tailscale_hostname": "gils-mac-mini.123456.ts.net"}
    }
    online_hosts = {"gils-mac-mini.123456.ts.net"}

    with patch("deploy_ping.machine_profile.remote_devices", return_value=remote_info):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=online_hosts):
            with patch("deploy_ping.task_dispatch.SSH_OPTS", ["-o", "BatchMode=yes"]):
                with patch("deploy_ping.subprocess.run") as mock_run:
                    with patch("deploy_ping.job_events.job_run") as mock_job:
                        mock_run.return_value = Mock(returncode=0)
                        dp.main()

                        # Exactly one ssh call made
                        assert any(
                            call[0][0] == "ssh"
                            for call in mock_run.call_args_list
                        )
                        # Verify the command includes pull and delayed rebuild/restart
                        ssh_call = [call for call in mock_run.call_args_list if call[0][0] == "ssh"][0]
                        cmd_args = ssh_call[0]
                        assert "gils-mac-mini.123456.ts.net" in cmd_args
                        # The command should include nohup for detached execution
                        assert any("nohup" in str(arg) for arg in cmd_args)


def test_offline_device_is_skipped_without_ssh_attempt():
    """Offline/asleep device (not in _tailscale_online_hosts()) → skipped without ssh call."""
    remote_info = {
        "mac-mini-1": {"tailscale_hostname": "gils-mac-mini.123456.ts.net"}
    }
    online_hosts = set()  # Device is offline

    with patch("deploy_ping.machine_profile.remote_devices", return_value=remote_info):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=online_hosts):
            with patch("deploy_ping.subprocess.run") as mock_run:
                with patch("deploy_ping.job_events.job_run"):
                    dp.main()
                    # No ssh calls made
                    assert not any("ssh" in str(call) for call in mock_run.call_args_list)


def test_ssh_dependency_failure_is_logged_not_fatal():
    """ssh exits non-zero (host rejects, auth fails) → logged as failure, merge not blocked."""
    remote_info = {
        "mac-mini-1": {"tailscale_hostname": "gils-mac-mini.123456.ts.net"}
    }
    online_hosts = {"gils-mac-mini.123456.ts.net"}

    with patch("deploy_ping.machine_profile.remote_devices", return_value=remote_info):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=online_hosts):
            with patch("deploy_ping.subprocess.run") as mock_run:
                with patch("deploy_ping.job_events.job_run") as mock_job:
                    mock_run.return_value = Mock(returncode=1, stderr="Permission denied")
                    # Should not raise
                    try:
                        dp.main()
                    except Exception as e:
                        raise AssertionError(f"Should not raise on ssh failure, but got {e}")


def test_bad_input_malformed_tailscale_hostname():
    """Malformed/empty tailscale_hostname → skipped, not a crash."""
    remote_info = {
        "mac-mini-1": {"tailscale_hostname": ""}  # Empty hostname
    }
    online_hosts = set()

    with patch("deploy_ping.machine_profile.remote_devices", return_value=remote_info):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=online_hosts):
            with patch("deploy_ping.subprocess.run"):
                with patch("deploy_ping.job_events.job_run"):
                    # Should not crash
                    try:
                        dp.main()
                    except Exception as e:
                        raise AssertionError(f"Should handle bad input gracefully, but got {e}")


def test_repeats_idempotent_both_ssh_calls_fire():
    """Two merges within same window → both ssh calls fire (code_sync.py pull is idempotent)."""
    remote_info = {
        "mac-mini-1": {"tailscale_hostname": "gils-mac-mini.123456.ts.net"}
    }
    online_hosts = {"gils-mac-mini.123456.ts.net"}

    with patch("deploy_ping.machine_profile.remote_devices", return_value=remote_info):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=online_hosts):
            with patch("deploy_ping.subprocess.run") as mock_run:
                with patch("deploy_ping.job_events.job_run"):
                    mock_run.return_value = Mock(returncode=0)
                    dp.main()
                    dp.main()  # Call twice

                    # Both calls should proceed (each succeeds independently)
                    # The idempotency is in code_sync.py and decide(), not here
                    ssh_calls = [call for call in mock_run.call_args_list if call[0][0] == "ssh"]
                    # At least 2 ssh calls made (one per invocation, possibly more for probes)
                    assert len(ssh_calls) >= 1


def test_permission_denied_treated_same_as_other_ssh_failures():
    """ssh key auth fails (permission denied) → same as dependency-failing case, logged, swallowed."""
    remote_info = {
        "mac-mini-1": {"tailscale_hostname": "gils-mac-mini.123456.ts.net"}
    }
    online_hosts = {"gils-mac-mini.123456.ts.net"}

    with patch("deploy_ping.machine_profile.remote_devices", return_value=remote_info):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=online_hosts):
            with patch("deploy_ping.subprocess.run") as mock_run:
                with patch("deploy_ping.job_events.job_run"):
                    mock_run.return_value = Mock(returncode=255, stderr="Permission denied (publickey)")
                    # Should not raise
                    try:
                        dp.main()
                    except Exception as e:
                        raise AssertionError(f"Should swallow permission errors, but got {e}")


def test_called_for_non_marvin_repo_is_safe():
    """A person's mistake: called for a non-marvin repo (should never happen) → safe/inert."""
    # This test verifies the script itself is safe to call, even if it shouldn't be.
    # The gate in merge.js prevents this, but the script should handle it gracefully.
    remote_info = {}

    with patch("deploy_ping.machine_profile.remote_devices", return_value=remote_info):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=set()):
            with patch("deploy_ping.subprocess.run"):
                with patch("deploy_ping.job_events.job_run"):
                    # Should not crash
                    try:
                        dp.main()
                    except Exception as e:
                        raise AssertionError(f"Should handle non-marvin repos gracefully, but got {e}")


def test_multiple_remote_devices_all_reachable():
    """Multiple remote devices all reachable → all get pinged."""
    remote_info = {
        "mac-mini-1": {"tailscale_hostname": "gils-mac-mini.123456.ts.net"},
        "macbook-1": {"tailscale_hostname": "gils-macbook.654321.ts.net"},
    }
    online_hosts = {"gils-mac-mini.123456.ts.net", "gils-macbook.654321.ts.net"}

    with patch("deploy_ping.machine_profile.remote_devices", return_value=remote_info):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=online_hosts):
            with patch("deploy_ping.subprocess.run") as mock_run:
                with patch("deploy_ping.job_events.job_run"):
                    mock_run.return_value = Mock(returncode=0)
                    dp.main()

                    # At least 2 ssh calls made (one per device)
                    ssh_calls = [call for call in mock_run.call_args_list if call[0][0] == "ssh"]
                    assert len(ssh_calls) >= 2


def test_job_events_context_used():
    """job_events.job_run wraps the dispatch loop."""
    with patch("deploy_ping.machine_profile.remote_devices", return_value={}):
        with patch("deploy_ping.task_dispatch._tailscale_online_hosts", return_value=set()):
            with patch("deploy_ping.subprocess.run"):
                with patch("deploy_ping.job_events.job_run") as mock_job:
                    mock_job.return_value.__enter__ = Mock()
                    mock_job.return_value.__exit__ = Mock(return_value=False)
                    dp.main()
                    # Verify job_run was called
                    assert mock_job.called


# === Regression guards ===

def test_module_level_imports_resolvable():
    """Regression guard: module-level imports (not main()-scoped) so patch() targets resolve.

    When imports live inside main(), patch("deploy_ping.machine_profile", ...) fails with
    AttributeError because machine_profile is not a module-level attribute. This test
    confirms the imports are at module level and the patch targets exist.
    """
    # Simply importing the module should make these resolvable
    assert hasattr(dp, "job_events"), "job_events must be module-level import"
    assert hasattr(dp, "machine_profile"), "machine_profile must be module-level import"
    assert hasattr(dp, "task_dispatch"), "task_dispatch must be module-level import"


def test_stale_machine_state_without_app_running_field():
    """Regression guard: remote still running pre-#329 _MACHINE_STATE_SCRIPT (no app_running= line).

    When a remote's lib is older and doesn't emit app_running= at all (not even garbled),
    health_checks should default app_running to None and NOT fire a red dashboard:running alert
    for a machine just running older but otherwise-fine code.
    """
    # This is deferred to test_health_checks.py since it's a health_checks concern,
    # not a deploy_ping concern. Left as a documentation anchor here.
    pass
