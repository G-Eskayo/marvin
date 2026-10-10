"""Test isolation for brain-map/scripts: fake gh and jobs_directory."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))


@pytest.fixture(autouse=True)
def _fake_gh_on_path(tmp_path_factory, monkeypatch):
    """Block real gh calls in tests; tests inject a fake gh by explicit monkeypatch."""
    bin_dir = tmp_path_factory.mktemp("no-gh")
    fake = bin_dir / "gh"
    fake.write_text("#!/bin/sh\necho 'gh is blocked in tests (brain-map/scripts/conftest.py): inject a fake' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.fixture(autouse=True)
def _isolate_jobs_directory(tmp_path_factory, monkeypatch):
    """Isolate job_events.JOBS_DIR so tests never write the real ~/.claude/logs/jobs."""
    import job_events
    monkeypatch.setattr(job_events, "JOBS_DIR", tmp_path_factory.mktemp("jobs"))
