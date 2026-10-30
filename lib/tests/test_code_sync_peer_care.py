"""marvin#847 (design #769 section 3, "heartbeat missing"): the end of each existing code-sync pull of the engine
starts one peer-care check of the peers this machine watches. No new clock. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_peer_care.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402


def test_pull_of_the_engine_starts_one_detached_check(tmp_path):
    spawned = []
    cs.peer_care_after_sync("pull", cs.DEFAULT_REPO, spawn=lambda cmd, **kw: spawned.append((cmd, kw)))
    assert len(spawned) == 1
    cmd, kw = spawned[0]
    assert cmd[-3:] == ["check-all", "--trigger", "code-sync"] and cmd[-4].endswith("peer_care.py")
    assert kw.get("start_new_session") is True           # never holds the sync up, never dies with it


def test_push_mirror_and_other_repos_start_nothing(tmp_path):
    spawned = []
    for action, repo in (("push", cs.DEFAULT_REPO), ("mirror", cs.DEFAULT_REPO), ("pull", tmp_path)):
        cs.peer_care_after_sync(action, repo, spawn=lambda cmd, **kw: spawned.append(cmd))
    assert spawned == []


def test_a_spawn_failure_never_breaks_the_sync():
    def boom(cmd, **kw):
        raise OSError("no python")
    cs.peer_care_after_sync("pull", cs.DEFAULT_REPO, spawn=boom)     # no exception
