"""Repo-wide test isolation: no test reaches real GitHub.

A suite run was editing a real ticket's labels (marvin#20) and the merge gate's retests on the Mini made about 1,000
real gh calls an hour while PRs were being approved, on the one allowance both Macs and the dashboard share
(found 2026-10-08). A `gh` that refuses everything comes first on PATH for every test; tests that need gh behaviour
mock it.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _no_real_github(tmp_path_factory, monkeypatch):
    bin_dir = tmp_path_factory.mktemp("no-gh")
    fake = bin_dir / "gh"
    fake.write_text("#!/bin/sh\necho 'gh is disabled in tests' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
