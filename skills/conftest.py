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
