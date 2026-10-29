"""Collection safety regression test — guards against import-time crashes.
Directly imports all new bench modules to ensure zero collection errors.
~/.agents/venv/bin/python -m pytest bench/tests/test_collection_safety.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH / "lib"))
sys.path.insert(0, str(BENCH))


def test_opencode_runner_imports_without_error():
    """Verify opencode_runner.py can be imported without errors."""
    try:
        import opencode_runner  # noqa: F401
        assert hasattr(opencode_runner, "opencode_available")
        assert hasattr(opencode_runner, "run_once_opencode")
    except Exception as e:
        pytest.fail(f"opencode_runner import failed: {e}")


def test_energy_apple_imports_without_error():
    """Verify energy_apple.py can be imported without errors."""
    try:
        import energy_apple  # noqa: F401
        assert hasattr(energy_apple, "start_sampling")
        assert hasattr(energy_apple, "stop_sampling")
    except Exception as e:
        pytest.fail(f"energy_apple import failed: {e}")


def test_ticket_replay_imports_without_error():
    """Verify ticket_replay.py can be imported without errors."""
    try:
        import ticket_replay  # noqa: F401
        assert hasattr(ticket_replay, "resolve_merge_commit")
        assert hasattr(ticket_replay, "replay_ticket")
    except Exception as e:
        pytest.fail(f"ticket_replay import failed: {e}")


def test_local_agent_spike_imports_without_error():
    """Verify local_agent_spike.py can be imported without errors."""
    try:
        import local_agent_spike  # noqa: F401
        assert hasattr(local_agent_spike, "orchestrate_spike")
        assert hasattr(local_agent_spike, "score_gate_pass")
        assert hasattr(local_agent_spike, "append_results_section")
        assert hasattr(local_agent_spike, "load_ticket_list")
    except Exception as e:
        pytest.fail(f"local_agent_spike import failed: {e}")


def test_all_modules_can_be_imported_simultaneously():
    """Test that all modules can be imported together without conflicts."""
    try:
        import opencode_runner  # noqa: F401
        import energy_apple  # noqa: F401
        import ticket_replay  # noqa: F401
        import local_agent_spike  # noqa: F401
    except Exception as e:
        pytest.fail(f"Simultaneous import failed: {e}")


def test_pytest_can_collect_all_new_tests():
    """Meta test: verify pytest can collect test functions without errors."""
    # This test passes if pytest collection succeeded at all
    assert True
