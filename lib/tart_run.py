#!/usr/bin/env python3
"""VM lifecycle management for tart (M4 Mini): golden-image clone → run → cleanup.

Similar shape to vm_run.py (virsh/qemu-img for mac-mini-2012), but targeting tart
on the M4 Mini instead. Used by clean-install test driver for isolating setup.sh
tests and demos."""

from __future__ import annotations
import subprocess
import uuid
from dataclasses import dataclass
from typing import Callable


@dataclass
class RunResult:
    """Result of running a command in a tart VM."""
    returncode: int
    stdout: str
    stderr: str


def tart_run(
    golden_image: str,
    cmd: list[str],
    run: Callable = subprocess.run,
    vm_name: str | None = None,
) -> RunResult:
    """Clone a tart golden image, run a command, clean up the VM.

    Args:
        golden_image: Name of the golden tart image (e.g., "macOS-13-golden")
        cmd: Command to run inside the VM (list of args)
        run: Subprocess.run function (injectable for testing)
        vm_name: Optional VM name (default: auto-generated UUID)

    Returns:
        RunResult with returncode, stdout, stderr from the command execution.

    The VM is deleted after the command completes, regardless of success/failure.
    """
    vm_name = vm_name or f"test-{uuid.uuid4().hex[:12]}"

    try:
        # Clone the golden image
        clone_result = run(
            ["tart", "clone", golden_image, vm_name],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if clone_result.returncode != 0:
            return RunResult(
                returncode=1,
                stdout="",
                stderr=f"Failed to clone VM: {clone_result.stderr}"
            )

        # Run the command inside the VM
        # Use tart run to execute the command
        run_result = run(
            ["tart", "run", vm_name, *cmd],
            capture_output=True,
            text=True,
            timeout=600,  # 10-minute timeout for setup.sh
        )

        return RunResult(
            returncode=run_result.returncode,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
        )
    finally:
        # Always clean up the VM
        run(
            ["tart", "delete", vm_name],
            capture_output=True,
            timeout=60,
        )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: tart_run.py <golden-image> <command...>")
        sys.exit(1)

    golden_image = sys.argv[1]
    cmd = sys.argv[2:]

    result = tart_run(golden_image, cmd)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    sys.exit(result.returncode)
