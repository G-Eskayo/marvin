"""Suite-wide isolation for skill tests: every model run is recorded to the launch log, and a test must never
write the real one (marvin#303 found skill tests adding fake runs to ~/.claude/logs/launches.jsonl)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))


@pytest.fixture(autouse=True)
def _isolate_launch_log(tmp_path_factory, monkeypatch):
    import marvin_launcher
    monkeypatch.setattr(marvin_launcher, "LAUNCH_LOG", tmp_path_factory.mktemp("launches") / "launches.jsonl")


@pytest.fixture(autouse=True)
def _no_real_github(tmp_path_factory, monkeypatch):
    # Tests must never reach real GitHub: a suite run was editing a real ticket's labels (marvin#20) and spending the
    # account's API budget (found 2026-10-08). A `gh` that refuses everything comes first on PATH; tests that need gh
    # behaviour mock it.
    import os
    bin_dir = tmp_path_factory.mktemp("no-gh")
    fake = bin_dir / "gh"
    fake.write_text("#!/bin/sh\necho 'gh is disabled in tests' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
