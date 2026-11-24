import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import plistlib
import tempfile

# This test module verifies Part B (Boot-triggered catch-up):
# - The launchd plist uses RunAtLoad (boot/login trigger), not wake-based triggers
# - The plist configuration is correct for boot-only operation


def test_launchd_plist_uses_runattload_only():
    """
    Verify that the Part B launchd job uses RunAtLoad (boot/login trigger),
    not any wake-based trigger like StartOnMount or other sleep-related keys.
    """
    plist_path = Path(__file__).resolve().parent.parent.parent / \
                 "config/launchd/com.marvin.hub-catchup.plist"

    # Verify plist exists
    assert plist_path.exists(), f"Plist not found at {plist_path}"

    # Load and verify contents
    with open(plist_path, 'rb') as f:
        plist = plistlib.load(f)

    # Must have RunAtLoad = true
    assert plist.get('RunAtLoad') is True, \
        "Part B job must use RunAtLoad for boot/login trigger"

    # Must NOT have sleep-related triggers
    assert 'StartOnMount' not in plist, \
        "RunAtLoad does not fire on wake; don't use StartOnMount"

    # Label should identify this as the hub-catchup job
    assert 'hub-catchup' in plist.get('Label', '').lower(), \
        "Plist Label should identify this as hub-catchup for clarity"


def test_boot_trigger_does_not_fire_on_wake():
    """
    Verify that Part B uses RunAtLoad (not wake-triggered).
    RunAtLoad fires at boot and login, not on wake from sleep.
    """
    plist_path = Path(__file__).resolve().parent.parent.parent / \
                 "config/launchd/com.marvin.hub-catchup.plist"

    with open(plist_path, 'rb') as f:
        plist = plistlib.load(f)

    # RunAtLoad = true means it fires at boot and login only
    assert plist.get('RunAtLoad') is True, \
        "Must use RunAtLoad for boot-only triggering"


def test_boot_trigger_calls_ticket_pipeline_scan():
    """
    Verify that Part B's launchd job calls a script/function to scan for work.
    """
    plist_path = Path(__file__).resolve().parent.parent.parent / \
                 "config/launchd/com.marvin.hub-catchup.plist"

    with open(plist_path, 'rb') as f:
        plist = plistlib.load(f)

    # ProgramArguments should reference a script or python
    prog_args = plist.get('ProgramArguments', [])
    assert len(prog_args) > 0, "ProgramArguments must be defined"

    # Should reference python or a scan script
    prog_str = " ".join(str(arg) for arg in prog_args).lower()
    assert any(x in prog_str for x in ['python', 'scan', 'hub', 'catchup']), \
        f"ProgramArguments should reference a scan script, got: {prog_args}"


def test_wake_does_not_trigger_part_b():
    """
    Document: Hub wakes from sleep (not rebooted).
    - RunAtLoad does NOT fire (boot-only)
    - Queued work starts on the next periodic scan or dispatch attempt
    """
    plist_path = Path(__file__).resolve().parent.parent.parent / \
                 "config/launchd/com.marvin.hub-catchup.plist"

    with open(plist_path, 'rb') as f:
        plist = plistlib.load(f)

    # Verify RunAtLoad-only configuration
    assert plist.get('RunAtLoad') is True
    # Should not have KeepAlive=true (which would keep it running)
    keep_alive = plist.get('KeepAlive')
    if isinstance(keep_alive, bool):
        assert not keep_alive, "Should not keep this job running"
