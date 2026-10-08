"""Tests for code_sync.py's pull(). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_code_sync_pull.py -v

Uses real temp git repos (a bare "origin" plus two working clones simulating
machines A and B) rather than mocking `git` — pull()'s whole job is
orchestrating real git state, so a mocked subprocess wouldn't catch the class
of bug this file guards against.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _git_ok(repo: Path, *args: str) -> tuple[bool, str]:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return result.returncode == 0, (result.stdout + result.stderr)


def _make_origin_and_clones(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare origin and two clones (A and B) with initial commit."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    (seed / "sync-log.md").write_text("# Sync Log\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", str(origin), "main")

    clone_a = tmp_path / "clone_a"
    subprocess.run(["git", "clone", str(origin), str(clone_a)], check=True, capture_output=True)
    _git(clone_a, "config", "user.email", "test@example.com")
    _git(clone_a, "config", "user.name", "Test A")

    clone_b = tmp_path / "clone_b"
    subprocess.run(["git", "clone", str(origin), str(clone_b)], check=True, capture_output=True)
    _git(clone_b, "config", "user.email", "test@example.com")
    _git(clone_b, "config", "user.name", "Test B")

    return clone_a, clone_b


def test_metrics_collision_merge_both_timestamps(tmp_path, monkeypatch):
    """Reproduces the 18:22 incident: machine B writes metrics tracked, machine A
    has them untracked with a different timestamp. pull() on A should merge them."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "machine_label", lambda: "test-machine-a")

    clone_a, clone_b = _make_origin_and_clones(tmp_path)

    (clone_b / "bench" / "metrics").mkdir(parents=True, exist_ok=True)
    ts_b1 = "2026-10-08T18:00:00.000000+00:00"
    metrics_b1 = {"timestamp": ts_b1, "metrics": {"test_metric": {"value": 100, "higher_is_better": True}}}
    (clone_b / "bench" / "metrics" / "ticket-268.json").write_text(json.dumps([metrics_b1], indent=2))
    (clone_b / "bench" / "metrics" / "ticket-268.md").write_text(f"## {ts_b1} — ticket-268\n- **test_metric**: 100\n\n")
    _git(clone_b, "add", "-A")
    _git(clone_b, "commit", "-m", "machine B records metrics")
    _git(clone_b, "push", "origin", "main")

    (clone_a / "bench" / "metrics").mkdir(parents=True, exist_ok=True)
    ts_a1 = "2026-10-08T18:05:00.000000+00:00"
    metrics_a1 = {"timestamp": ts_a1, "metrics": {"test_metric": {"value": 110, "higher_is_better": True}}}
    (clone_a / "bench" / "metrics" / "ticket-268.json").write_text(json.dumps([metrics_a1], indent=2))
    (clone_a / "bench" / "metrics" / "ticket-268.md").write_text(f"## {ts_a1} — ticket-268\n- **test_metric**: 110\n\n")

    cs.pull(clone_a)

    stash_list = subprocess.run(["git", "stash", "list"], cwd=clone_a, capture_output=True, text=True).stdout
    assert not stash_list.strip(), f"stash should be empty, but got: {stash_list}"

    merged_json = json.loads((clone_a / "bench" / "metrics" / "ticket-268.json").read_text())
    assert len(merged_json) == 2, f"expected 2 merged timestamps, got {len(merged_json)}"
    timestamps = {e["timestamp"] for e in merged_json}
    assert timestamps == {ts_a1, ts_b1}, f"expected both timestamps {ts_a1}, {ts_b1}, got {timestamps}"

    merged_md = (clone_a / "bench" / "metrics" / "ticket-268.md").read_text()
    assert ts_b1 in merged_md and ts_a1 in merged_md, "both timestamps should be in merged markdown"

    log_output = subprocess.run(["git", "log", "--oneline", "-5"], cwd=clone_a, capture_output=True, text=True).stdout
    assert "keep both machines' runs" in log_output, f"expected merge commit, got log:\n{log_output}"


def test_metrics_collision_identical_content_no_extra_commit(tmp_path, monkeypatch):
    """When both machines write byte-identical metrics, pull() should not create
    an extra 'keep both machines' commit."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "unused-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "machine_label", lambda: "test-machine-a")

    clone_a, clone_b = _make_origin_and_clones(tmp_path)

    (clone_b / "bench" / "metrics").mkdir(parents=True, exist_ok=True)
    ts = "2026-10-08T18:00:00.000000+00:00"
    metrics = {"timestamp": ts, "metrics": {"test": {"value": 50, "higher_is_better": True}}}
    (clone_b / "bench" / "metrics" / "ticket-268.json").write_text(json.dumps([metrics], indent=2))
    (clone_b / "bench" / "metrics" / "ticket-268.md").write_text(f"## {ts} — ticket-268\n- **test**: 50\n\n")
    _git(clone_b, "add", "-A")
    _git(clone_b, "commit", "-m", "machine B records metrics")
    _git(clone_b, "push", "origin", "main")

    (clone_a / "bench" / "metrics").mkdir(parents=True, exist_ok=True)
    (clone_a / "bench" / "metrics" / "ticket-268.json").write_text(json.dumps([metrics], indent=2))
    (clone_a / "bench" / "metrics" / "ticket-268.md").write_text(f"## {ts} — ticket-268\n- **test**: 50\n\n")

    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone_a, capture_output=True, text=True).stdout.strip()

    cs.pull(clone_a)

    stash_list = subprocess.run(["git", "stash", "list"], cwd=clone_a, capture_output=True, text=True).stdout
    assert not stash_list.strip(), f"stash should be empty"

    log = subprocess.run(["git", "log", "--oneline", "-3"], cwd=clone_a, capture_output=True, text=True).stdout
    keep_both_commits = [line for line in log.split("\n") if "keep both machines" in line]
    assert not keep_both_commits, f"should not create extra commit for identical content, but got:\n{log}"


def test_metrics_collision_unrelated_path_preserves_stash(tmp_path, monkeypatch):
    """Regression guard: if a non-metrics untracked file collides, fall back to
    today's behavior (stash preserved, logged as conflict)."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "machine_label", lambda: "test-machine-a")

    clone_a, clone_b = _make_origin_and_clones(tmp_path)

    _git(clone_b, "config", "user.name", "Test B")
    (clone_b / "unrelated.txt").write_text("machine B content\n")
    _git(clone_b, "add", "-A")
    _git(clone_b, "commit", "-m", "machine B adds unrelated file")
    _git(clone_b, "push", "origin", "main")

    (clone_a / "unrelated.txt").write_text("machine A content\n")

    cs.pull(clone_a)

    stash_list = subprocess.run(["git", "stash", "list"], cwd=clone_a, capture_output=True, text=True).stdout
    assert stash_list.strip(), "stash should be preserved for non-metrics collision"

    log = subprocess.run(["git", "log", "--oneline", "-3"], cwd=clone_a, capture_output=True, text=True).stdout
    assert "keep both machines" not in log, "should not auto-merge non-metrics files"


def test_metrics_collision_mixed_files_preserves_stash(tmp_path, monkeypatch):
    """If both metrics and non-metrics files are in the collision, preserve the
    stash intact rather than partially resolving."""
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(cs, "machine_label", lambda: "test-machine-a")

    clone_a, clone_b = _make_origin_and_clones(tmp_path)

    (clone_b / "bench" / "metrics").mkdir(parents=True, exist_ok=True)
    ts = "2026-10-08T18:00:00.000000+00:00"
    metrics = {"timestamp": ts, "metrics": {"test": {"value": 75, "higher_is_better": True}}}
    (clone_b / "bench" / "metrics" / "ticket-268.json").write_text(json.dumps([metrics], indent=2))
    (clone_b / "bench" / "metrics" / "ticket-268.md").write_text(f"## {ts} — ticket-268\n- **test**: 75\n\n")

    (clone_b / "other.txt").write_text("machine B other\n")
    _git(clone_b, "add", "-A")
    _git(clone_b, "commit", "-m", "machine B adds metrics and other file")
    _git(clone_b, "push", "origin", "main")

    (clone_a / "bench" / "metrics").mkdir(parents=True, exist_ok=True)
    (clone_a / "bench" / "metrics" / "ticket-268.json").write_text(json.dumps([metrics], indent=2))
    (clone_a / "bench" / "metrics" / "ticket-268.md").write_text(f"## {ts} — ticket-268\n- **test**: 75\n\n")
    (clone_a / "other.txt").write_text("machine A other\n")

    cs.pull(clone_a)

    stash_list = subprocess.run(["git", "stash", "list"], cwd=clone_a, capture_output=True, text=True).stdout
    assert stash_list.strip(), "mixed collision should preserve stash intact"

    log = subprocess.run(["git", "log", "--oneline", "-3"], cwd=clone_a, capture_output=True, text=True).stdout
    assert "keep both machines" not in log, "should not partially resolve mixed collisions"
