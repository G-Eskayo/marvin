"""tart_run module tests (28-30): VM lifecycle management for clean-install testing.

Similar shape to vm_run.py/virsh operations but targeting tart on M4 Mini.
Tests the golden-image clone → run → cleanup pattern."""

import subprocess
import pytest
from pathlib import Path


def test_28_tart_run_result_captures_exit_code_and_output(tmp_path):
    """RunResult should capture exit code, stdout, stderr from VM run."""
    # Import the module
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tart_run import RunResult

    result = RunResult(returncode=0, stdout="success", stderr="")
    assert result.returncode == 0
    assert result.stdout == "success"
    assert result.stderr == ""

    result_fail = RunResult(returncode=1, stdout="", stderr="failed")
    assert result_fail.returncode == 1
    assert "failed" in result_fail.stderr


def test_29_tart_run_executes_command_in_vm(tmp_path, monkeypatch):
    """tart_run should clone golden image, execute cmd, clean up."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tart_run import tart_run

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        # Simulate successful clone, run, delete
        if "clone" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if any(x in cmd for x in ["set", "export"]):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "output", "")

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = tart_run("macOS-13-golden", ["echo", "test"], run=subprocess.run)

    # Should have called clone, run, and delete
    clone_calls = [c for c in calls if "clone" in str(c)]
    delete_calls = [c for c in calls if "delete" in str(c)]

    assert len(clone_calls) >= 1, "Should clone golden image"
    assert len(delete_calls) >= 1, "Should delete VM after run"


def test_30_tart_run_cleans_up_on_failure(tmp_path, monkeypatch):
    """tart_run should delete VM even if command fails."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tart_run import tart_run

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        # Command fails
        if any(x in str(cmd) for x in ["set", "export", "run"]):
            return subprocess.CompletedProcess(cmd, 1, "", "failed")
        # Clone and delete succeed
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = tart_run("macOS-13-golden", ["sh", "-c", "exit 1"], run=subprocess.run)

    # Even though the command failed, should have cleaned up
    delete_calls = [c for c in calls if "delete" in str(c)]
    assert len(delete_calls) >= 1, "Should delete VM even when command fails"
