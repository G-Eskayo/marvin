"""Tests for graphify_freshness.py (marvin#691): keeping the graphify code graph current and saying when it isn't.
Real git repos in tmp_path and a fake `graphify` executable; nothing touches the real graphify-out.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_graphify_freshness.py -v
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import graphify_freshness as gf  # noqa: E402

NOW = datetime(2026, 10, 26, 20, tzinfo=timezone.utc)


def git(repo, *args) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def make_repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "lib").mkdir()
    (repo / "lib" / "a.py").write_text("def a():\n    return 1\n")
    (repo / "README.md").write_text("# r\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo


def write_graph(repo, sha, manifest=("lib/a.py", "README.md")) -> Path:
    out = repo / "graphify-out"
    out.mkdir(exist_ok=True)
    # built_at_commit sits at the very end of a big file, the way graphify writes it
    body = {"directed": False, "nodes": [{"id": f"n{i}", "label": "x" * 50} for i in range(3000)], "links": [],
            "hyperedges": [], "built_at_commit": sha}
    (out / "graph.json").write_text(json.dumps(body, indent=2))
    (out / "manifest.json").write_text(json.dumps({p: {"mtime": 0} for p in manifest}))
    return out


def commit(repo, path, text, msg="change"):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD")


# ── reading the graph cheaply ─────────────────────────────────────────────

def test_built_commit_is_read_from_the_tail_without_parsing_the_whole_file(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    sha = git(repo, "rev-parse", "HEAD")
    out = write_graph(repo, sha)
    monkeypatch.setattr(json, "loads", lambda *a, **k: pytest.fail("parsed the whole graph"))
    monkeypatch.setattr(json, "load", lambda *a, **k: pytest.fail("parsed the whole graph"))
    assert gf.read_built_commit(out / "graph.json") == sha


def test_built_commit_missing_or_garbage_is_none(tmp_path):
    assert gf.read_built_commit(tmp_path / "nope.json") is None
    f = tmp_path / "g.json"
    f.write_text('{"nodes": [], "built_at_commit": "not-a-sha; rm -rf /"}')
    assert gf.read_built_commit(f) is None


# ── what changed since the graph was last known current ──────────────────

def test_changes_count_only_files_the_graph_tracks(tmp_path):
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    write_graph(repo, base)
    commit(repo, "lib/a.py", "def a():\n    return 2\n")
    commit(repo, "lib/new_module.py", "x = 1\n")           # new file, tracked extension -> counts
    commit(repo, "assets/photo.heic", "binary")             # extension graphify never saw -> ignored
    commit(repo, "graphify-out/GRAPH_REPORT.md", "report")  # the graph's own output -> ignored
    changed = gf.tracked_changes(repo, base)
    assert sorted(changed) == ["lib/a.py", "lib/new_module.py"]


def test_changes_work_when_the_build_commit_is_not_an_ancestor(tmp_path):
    # 2026-10-26: built_at_commit 535c264 was off to the side of HEAD after a rebase; diff trees, not history
    repo = make_repo(tmp_path)
    git(repo, "checkout", "-qb", "side")
    side = commit(repo, "lib/a.py", "def a():\n    return 'side'\n")
    git(repo, "checkout", "-q", "main")
    commit(repo, "README.md", "# main moved\n")
    write_graph(repo, side)
    assert set(gf.tracked_changes(repo, side)) == {"lib/a.py", "README.md"}


def test_unknown_build_commit_is_none_not_zero(tmp_path):
    repo = make_repo(tmp_path)
    write_graph(repo, "0" * 40)
    assert gf.tracked_changes(repo, "0" * 40) is None


# ── severity ──────────────────────────────────────────────────────────────

def evaluate(**kw):
    base = dict(head="h" * 40, basis_sha="h" * 40, basis_at=NOW - timedelta(hours=1), changed=[], last_error=None,
                missing_hooks=[], graph_exists=True, now=NOW)
    base.update(kw)
    return gf.evaluate(**base)


def test_green_when_nothing_tracked_changed():
    sev, detail, value = evaluate()
    assert sev == "green" and value == 0


def test_yellow_when_behind_but_recent():
    sev, detail, value = evaluate(changed=["lib/a.py", "lib/b.py"], basis_sha="a" * 40)
    assert sev == "yellow" and value == 2
    assert "2 files changed" in detail and "aaaaaaa" in detail


def test_red_when_behind_for_more_than_a_day():
    sev, detail, _ = evaluate(changed=["lib/a.py"], basis_at=NOW - timedelta(hours=25))
    assert sev == "red" and "1 file changed" in detail


def test_red_when_last_refresh_failed_even_if_otherwise_current():
    sev, detail, _ = evaluate(last_error="graphify: command not found")
    assert sev == "red" and "command not found" in detail


def test_red_when_hooks_are_missing():
    sev, detail, _ = evaluate(missing_hooks=["post-merge"])
    assert sev == "red" and "post-merge" in detail


def test_red_when_build_commit_is_unknown():
    sev, detail, _ = evaluate(changed=None)
    assert sev == "red" and "doesn't have" in detail


def test_yellow_when_never_built():
    sev, detail, _ = evaluate(graph_exists=False)
    assert sev == "yellow" and "not built" in detail


# ── refresh: the one writer every hook and the button call ───────────────

def fake_graphify(tmp_path, body: str) -> Path:
    exe = tmp_path / "bin" / "graphify"
    exe.parent.mkdir(exist_ok=True)
    exe.write_text("#!/bin/sh\n" + body + "\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def test_refresh_stamps_head_even_when_graphify_leaves_outputs_untouched(tmp_path):
    # graphify skips rewriting graph.json when topology didn't change, so built_at_commit lags; the stamp is the truth
    repo = make_repo(tmp_path)
    old = git(repo, "rev-parse", "HEAD")
    write_graph(repo, old)
    head = commit(repo, "lib/a.py", "def a():\n    return 3\n")
    exe = fake_graphify(tmp_path, 'echo "No code-graph topology changes detected; outputs left untouched."')
    r = gf.refresh(repo, graphify=str(exe), now=NOW)
    assert r["ok"] is True
    stamp = gf.read_stamp(repo / "graphify-out")
    assert stamp["last_ok_head"] == head and stamp["last_error"] is None
    res = gf.check(repo, now=NOW + timedelta(minutes=1), hooks_ok=True)
    assert res["severity"] == "green", res["detail"]


def test_failed_refresh_keeps_last_good_and_reports_red(tmp_path):
    repo = make_repo(tmp_path)
    good = git(repo, "rev-parse", "HEAD")
    write_graph(repo, good)
    gf.refresh(repo, graphify=str(fake_graphify(tmp_path, "true")), now=NOW)
    commit(repo, "lib/a.py", "def a():\n    return 4\n")
    r = gf.refresh(repo, graphify=str(fake_graphify(tmp_path, "echo boom >&2; exit 3")), now=NOW)
    assert r["ok"] is False
    stamp = gf.read_stamp(repo / "graphify-out")
    assert stamp["last_ok_head"] == good and "boom" in stamp["last_error"]
    res = gf.check(repo, now=NOW, hooks_ok=True)
    assert res["severity"] == "red" and "boom" in res["detail"]
    # a later success clears the error
    gf.refresh(repo, graphify=str(fake_graphify(tmp_path, "true")), now=NOW)
    assert gf.check(repo, now=NOW, hooks_ok=True)["severity"] == "green"


def test_refresh_does_nothing_in_a_linked_worktree_or_without_a_graph(tmp_path):
    repo = make_repo(tmp_path)
    exe = fake_graphify(tmp_path, f"touch {tmp_path}/ran")
    assert gf.refresh(repo, graphify=str(exe), now=NOW)["skipped"]  # no graphify-out yet
    write_graph(repo, git(repo, "rev-parse", "HEAD"))
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "wt")
    (wt / "graphify-out").mkdir()
    assert gf.refresh(wt, graphify=str(exe), now=NOW)["skipped"]
    assert not (tmp_path / "ran").exists()


def test_refresh_survives_a_missing_graphify_binary(tmp_path):
    repo = make_repo(tmp_path)
    write_graph(repo, git(repo, "rev-parse", "HEAD"))
    r = gf.refresh(repo, graphify=str(tmp_path / "no-such-graphify"), now=NOW)
    assert r["ok"] is False and gf.read_stamp(repo / "graphify-out")["last_error"]


# ── snapshot pruning ──────────────────────────────────────────────────────

def test_prune_keeps_newest_dated_snapshots_and_nothing_else_is_touched(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    days = [f"2026-10-{d:02d}" for d in range(1, 13)]
    for d in days:
        (out / d).mkdir()
        (out / d / "graph.json").write_text("{}")
    keepers = ["cache", "2026-10-xx", "notes-2026-10-01", "graph.json"]
    (out / "cache").mkdir()
    (out / "2026-10-xx").mkdir()
    (out / "notes-2026-10-01").mkdir()
    (out / "graph.json").write_text("{}")
    (tmp_path / "2026-01-01").mkdir()  # outside graphify-out: never touched
    removed = gf.prune_snapshots(out, keep=7)
    assert sorted(removed) == days[:5]
    left = sorted(p.name for p in out.iterdir())
    assert left == sorted(days[5:] + keepers)
    assert (tmp_path / "2026-01-01").exists()
    # run twice: nothing more to do, nothing breaks
    assert gf.prune_snapshots(out, keep=7) == []


def test_prune_never_follows_a_symlinked_snapshot(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.txt").write_text("x")
    for d in range(1, 10):
        (out / f"2026-10-{d:02d}").mkdir()
    (out / "2026-09-01").symlink_to(precious)
    gf.prune_snapshots(out, keep=7)
    assert (precious / "keep.txt").exists()


# ── hooks ─────────────────────────────────────────────────────────────────

GRAPHIFY_BLOCK = "# graphify-hook-start\necho graphify-rebuild\n# graphify-hook-end\n"


def test_install_hooks_covers_every_way_commits_land_and_keeps_other_hook_content(tmp_path):
    repo = make_repo(tmp_path)
    hooks = Path(git(repo, "rev-parse", "--git-path", "hooks"))
    if not hooks.is_absolute():
        hooks = repo / hooks
    hooks.mkdir(exist_ok=True)
    pc = hooks / "post-commit"
    pc.write_text("#!/bin/sh\necho before\n" + GRAPHIFY_BLOCK + "echo brain-map\n")
    gf.install_hooks(repo)
    for name in gf.HOOKS:
        text = (hooks / name).read_text()
        assert text.startswith("#!/bin/sh") and gf.MARKER_START in text and gf.MARKER_END in text
        assert os.access(hooks / name, os.X_OK)
    text = pc.read_text()
    assert "echo before" in text and "echo brain-map" in text
    assert "graphify-hook-start" not in text  # one writer: graphify's own post-commit rebuild is replaced
    assert gf.missing_hooks(repo) == []
    # idempotent
    before = {n: (hooks / n).read_text() for n in gf.HOOKS}
    gf.install_hooks(repo)
    assert {n: (hooks / n).read_text() for n in gf.HOOKS} == before


@pytest.mark.parametrize("detach", [True, False])
def test_installed_hooks_are_valid_shell(tmp_path, detach):
    repo = make_repo(tmp_path)
    gf.install_hooks(repo, detach=detach)
    hooks = gf._hooks_dir(repo)
    for name in gf.HOOKS:
        r = subprocess.run(["sh", "-n", str(hooks / name)], capture_output=True, text=True)
        assert r.returncode == 0, f"{name}: {r.stderr}"


def test_missing_hooks_names_what_is_absent(tmp_path):
    repo = make_repo(tmp_path)
    assert set(gf.missing_hooks(repo)) == set(gf.HOOKS)


def test_a_real_merge_triggers_the_refresh(tmp_path):
    # end to end through git itself: a merge (how code_sync lands commits) must refresh the graph
    repo = make_repo(tmp_path)
    write_graph(repo, git(repo, "rev-parse", "HEAD"))
    git(repo, "checkout", "-qb", "feature")
    commit(repo, "lib/a.py", "def a():\n    return 'merged'\n")
    git(repo, "checkout", "-q", "main")
    commit(repo, "README.md", "# diverge\n")
    marker = tmp_path / "refreshed"
    exe = fake_graphify(tmp_path, f'echo "$@" > {marker}')
    gf.install_hooks(repo, graphify=str(exe), detach=False)
    subprocess.run(["git", "merge", "-q", "--no-edit", "feature"], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t"})
    assert marker.exists(), "post-merge did not refresh the graph"
    assert gf.read_stamp(repo / "graphify-out")["last_ok_head"] == git(repo, "rev-parse", "HEAD")


def test_check_result_shape_for_the_health_tab(tmp_path):
    repo = make_repo(tmp_path)
    write_graph(repo, git(repo, "rev-parse", "HEAD"))
    r = gf.check(repo, now=NOW, hooks_ok=True)
    assert r["id"] == "graphify:fresh" and r["label"] == "Code graph is current"
    assert r["severity"] in ("green", "yellow", "red") and isinstance(r["detail"], str)
