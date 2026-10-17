"""Runs the Linux live wallpaper's own tests (brain-map/desktop-live-linux/host.test.js) inside MARVIN's suite."""
import shutil
import subprocess
from pathlib import Path

import pytest

TEST = Path(__file__).resolve().parents[2] / "brain-map" / "desktop-live-linux" / "host.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_linux_wallpaper_host_logic_passes_its_tests():
    r = subprocess.run(["node", "--test", str(TEST)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
