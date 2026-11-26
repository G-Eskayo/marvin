#!/usr/bin/env python3
"""Tests for lib/health_checks.py tool health checking integration."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import health_checks as hc


# ─── Test: _local_tool_health checks local tools ───────────────────────────

def test_local_tool_health_all_available():
    """_local_tool_health returns green when all tools are available."""
    with patch("health_checks.tool_requirements.health") as mock_health:
        mock_health.return_value = MagicMock(
            available={"rg": True, "git": True},
            unavailable=[]
        )
        result = hc._local_tool_health()
        assert result["severity"] == "green"
        assert result["id"] == "tools@local"


def test_local_tool_health_some_missing():
    """_local_tool_health returns yellow when some tools are missing."""
    with patch("health_checks.tool_requirements.health") as mock_health:
        mock_health.return_value = MagicMock(
            available={"rg": False},
            unavailable=["rg"]
        )
        result = hc._local_tool_health()
        assert result["severity"] == "yellow"
        assert "rg" in result["detail"]


# ─── Test: check_tool_requirements_everywhere handles multiple machines ────

def test_check_tool_requirements_everywhere_local():
    """check_tool_requirements_everywhere includes local machine."""
    reachability = {}

    with patch("health_checks.machine_profile.registry_id") as mock_id:
        mock_id.return_value = "laptop"
        with patch("health_checks.machine_profile.remote_macs") as mock_remote:
            mock_remote.return_value = {}
            with patch("health_checks._local_tool_health") as mock_local:
                mock_local.return_value = {
                    "id": "tools@laptop",
                    "label": "Required tools and paths",
                    "severity": "green",
                    "detail": "All good",
                    "checked_at": "2026-11-25T00:00:00+00:00"
                }

                results = hc.check_tool_requirements_everywhere(reachability)
                assert len(results) > 0
                assert any(r["id"].startswith("tools@") for r in results)


def test_check_tool_requirements_everywhere_remote_unreachable():
    """check_tool_requirements_everywhere marks unreachable machines as yellow."""
    reachability = {"machine:mini": "yellow"}

    with patch("health_checks.machine_profile.registry_id") as mock_id:
        mock_id.return_value = "laptop"
        with patch("health_checks.machine_profile.remote_macs") as mock_remote:
            mock_remote.return_value = {
                "mini": {"tailscale_hostname": "mini.local"}
            }
            with patch("health_checks._local_tool_health") as mock_local:
                mock_local.return_value = {
                    "id": "tools@laptop",
                    "label": "Required tools and paths",
                    "severity": "green",
                    "detail": "All good",
                    "checked_at": "2026-11-25T00:00:00+00:00"
                }

                results = hc.check_tool_requirements_everywhere(reachability)
                # Should have local result
                assert any(r["id"] == "tools@laptop" for r in results)
                # Should have remote result marked yellow/unreachable
                mini_results = [r for r in results if "mini" in r["id"]]
                assert len(mini_results) > 0
                assert mini_results[0]["severity"] in ("yellow", "asleep")


def test_check_tool_requirements_everywhere_remote_reachable():
    """check_tool_requirements_everywhere checks remote machines."""
    reachability = {"machine:mini": "green"}

    with patch("health_checks.machine_profile.registry_id") as mock_id:
        mock_id.return_value = "laptop"
        with patch("health_checks.machine_profile.remote_macs") as mock_remote:
            mock_remote.return_value = {
                "mini": {"tailscale_hostname": "mini.local"}
            }
            with patch("health_checks._local_tool_health") as mock_local:
                mock_local.return_value = {
                    "id": "tools@laptop",
                    "label": "Required tools and paths",
                    "severity": "green",
                    "detail": "All good",
                    "checked_at": "2026-11-25T00:00:00+00:00"
                }
            with patch("health_checks._run_tool_health_remote") as mock_remote_check:
                mock_remote_check.return_value = json.dumps({
                    "available": {"rg": True},
                    "unavailable": []
                })

                results = hc.check_tool_requirements_everywhere(reachability)
                # Should have both local and remote results
                assert any(r["id"] == "tools@laptop" for r in results)
                assert any("mini" in r["id"] for r in results)


def test_check_tool_requirements_everywhere_handles_exceptions():
    """check_tool_requirements_everywhere handles exceptions gracefully."""
    reachability = {"machine:mini": "green"}

    with patch("health_checks.machine_profile.registry_id") as mock_id:
        mock_id.return_value = "laptop"
        with patch("health_checks.machine_profile.remote_macs") as mock_remote:
            mock_remote.return_value = {
                "mini": {"tailscale_hostname": "mini.local"}
            }
            with patch("health_checks._local_tool_health") as mock_local:
                mock_local.return_value = {
                    "id": "tools@laptop",
                    "label": "Required tools and paths",
                    "severity": "green",
                    "detail": "All good",
                    "checked_at": "2026-11-25T00:00:00+00:00"
                }
            with patch("health_checks._run_tool_health_remote") as mock_remote_check:
                # Simulate an exception
                mock_remote_check.side_effect = Exception("SSH timeout")

                results = hc.check_tool_requirements_everywhere(reachability)
                # Should still return results, with error for remote
                mini_result = [r for r in results if "mini" in r["id"]]
                assert len(mini_result) > 0
                assert mini_result[0]["severity"] == "yellow"
                assert "could not check" in mini_result[0]["detail"]


# ─── Test: Health check is registered in default_checks ────────────────────

def test_tools_check_in_default_checks():
    """The tools check is registered in default_checks."""
    checks = hc.default_checks()
    check_ids = [c[0] for c in checks]
    assert "tools" in check_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
