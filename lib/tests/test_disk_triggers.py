"""Tests for disk_triggers.py (marvin#765: disk cleanup triggered by use, not once a day). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_disk_triggers.py -v

Real git repos in a temp HOME (conftest points cleanup_sweep.HOME there), so "has uncommitted work → keep" is checked
against git itself, not a fake.
"""
from __future__ import annotations
import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import cleanup_sweep as cs  # noqa: E402
import disk_triggers as dt  # noqa: E402

GiB = 2**30
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


# ── pre-flight: check free space before heavy work starts ───────────────────────────────────────────────────────

def _free_seq(*values):
    it = iter(values)
    return lambda: next(it)


def test_preflight_above_the_floor_runs_no_reclaim():
    reclaim = lambda: pytest.fail("reclaim must not run when there is room")  # noqa: E731
    r = dt.preflight("helper: #60", free=_free_seq(20 * GiB), reclaim=reclaim)
    assert r["ok"] is True and r["reclaimed"] is None


def test_preflight_below_the_floor_reclaims_once_then_starts_when_that_was_enough():
    calls = []
    r = dt.preflight("helper: #60", free=_free_seq(3 * GiB, 9 * GiB),
                     reclaim=lambda: calls.append(1) or {"freed_bytes": 6 * GiB, "detail": "freed 6144 MiB"})
    assert calls == [1]
    assert r["ok"] is True and r["free_before"] == 3 * GiB and r["free_after"] == 9 * GiB


def test_preflight_refuses_in_plain_words_when_still_too_low():
    r = dt.preflight("helper: #60 split wiring", free=_free_seq(2 * GiB, 3 * GiB),
                     reclaim=lambda: {"freed_bytes": GiB, "detail": "freed 1024 MiB"})
    assert r["ok"] is False
    msg = r["message"]
    assert "#60 split wiring" in msg and "3.0 GB free" in msg and "5.0 GB" in msg
    assert "freed 1024 MiB" in msg   # says what it already tried


def test_preflight_uses_the_merge_gates_floor():
    # Same floor as #690 (dashboard/webhook-server/merge.js MIN_GATE_FREE_BYTES = 5 GiB).
    js = (LIB.parent / "dashboard" / "webhook-server" / "merge.js").read_text()
    assert "MIN_GATE_FREE_BYTES = 5 * 1024 ** 3" in js
    assert dt.FLOOR_BYTES == 5 * GiB


def test_preflight_fails_open_when_free_space_cannot_be_read():
    r = dt.preflight("helper: x", free=lambda: None, reclaim=lambda: pytest.fail("no reading, no reclaim"))
    assert r["ok"] is True


def test_preflight_still_answers_when_the_reclaim_breaks():
    r = dt.preflight("helper: x", free=_free_seq(1 * GiB, 1 * GiB), reclaim=lambda: 1 / 0)
    assert r["ok"] is False and "ZeroDivisionError" in r["message"]


def test_preflight_records_what_its_reclaim_freed(tmp_path):
    dt.preflight("helper: x", free=_free_seq(1 * GiB, 8 * GiB), reclaim=lambda: {"freed_bytes": 7 * GiB, "detail": "d"})
    entries = [json.loads(l) for l in dt.LOG_PATH.read_text().splitlines()]
    assert entries[-1]["trigger"] == "preflight" and entries[-1]["freed_bytes"] == 7 * GiB
    assert entries[-1]["what"] == "helper: x" and entries[-1]["ok"] is True


def test_preflight_refusal_is_recorded_even_when_nothing_was_freed():
    dt.preflight("helper: y", free=_free_seq(1 * GiB, 1 * GiB), reclaim=lambda: {"freed_bytes": 0, "detail": "nothing"})
    last = json.loads(dt.LOG_PATH.read_text().splitlines()[-1])
    assert last["ok"] is False and last["what"] == "helper: y"


def test_cli_preflight_exit_code_says_go_or_stop(monkeypatch, capsys):
    monkeypatch.setattr(dt, "preflight", lambda what, **k: {"ok": False, "message": f"no room for {what}"})
    assert dt.main(["preflight", "--what", "lane 3"]) == 1
    assert "no room for lane 3" in capsys.readouterr().err
    monkeypatch.setattr(dt, "preflight", lambda what, **k: {"ok": True, "message": ""})
    assert dt.main(["preflight", "--what", "lane 3"]) == 0


# ── after a merge: remove the merged PR's worktrees, wherever they are ──────────────────────────────────────────

def _git(*a, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _repo(name="marvin"):
    """A clone at ~/Developer/<name> (temp HOME) with a GitHub-looking origin."""
    home = cs.HOME
    origin = home / f"{name}-origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    clone = home / "Developer" / name
    clone.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    (clone / ".gitignore").write_text(".build/\nDerivedData/\n")
    (clone / "f").write_text("1")
    _git("add", ".", cwd=clone)
    _git("commit", "-qm", "i", cwd=clone)
    _git("push", "-q", "origin", "main", cwd=clone)
    _git("remote", "set-url", "--push", "origin", str(origin), cwd=clone)
    _git("config", "remote.origin.url", f"https://github.com/G-Eskayo/{name}.git", cwd=clone)
    return clone


def _worktree(clone, branch, path):
    _git("worktree", "add", "-q", "-b", branch, str(path), cwd=clone)
    (path / "work.txt").write_text(branch)
    _git("add", ".", cwd=path)
    _git("commit", "-qm", "work", cwd=path)
    return _git("rev-parse", "HEAD", cwd=path)


def _clean(clone, merged, cwds=frozenset(), dd=None):
    return dt.clean_merged_worktrees(clones=[clone], merged=lambda repo: merged, cwds=set(cwds),
                                     derived_data=dd or (cs.HOME / "DerivedData"))


def test_a_merged_prs_worktree_in_developer_repo_n_is_removed_and_its_branch_kept():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-765"
    head = _worktree(clone, "feat/765-x", wt)
    (wt / ".build").mkdir()
    (wt / ".build" / "big.o").write_bytes(b"x" * 4096)   # ignored build output: what the removal frees
    r = _clean(clone, {"feat/765-x": [head]})
    assert not wt.exists()
    assert [Path(x["path"]).name for x in r["removed"]] == ["marvin-765"]
    assert _git("rev-parse", "feat/765-x", cwd=clone) == head   # every commit still reachable


def test_merged_but_uncommitted_work_is_kept():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-1"
    head = _worktree(clone, "feat/1", wt)
    (wt / "f").write_text("edited, not committed")
    r = _clean(clone, {"feat/1": [head]})
    assert wt.exists() and (wt / "f").read_text() == "edited, not committed"
    assert r["removed"] == [] and "uncommitted" in r["kept"][0]["reason"]


def test_merged_but_an_untracked_file_is_kept():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-2"
    head = _worktree(clone, "feat/2", wt)
    (wt / "notes.md").write_text("only copy")
    _clean(clone, {"feat/2": [head]})
    assert (wt / "notes.md").read_text() == "only copy"


def test_merged_but_a_process_is_inside_is_kept():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-3"
    head = _worktree(clone, "feat/3", wt)
    r = _clean(clone, {"feat/3": [head]}, cwds={str((wt / "sub").resolve())})
    assert wt.exists() and "process" in r["kept"][0]["reason"]


def test_commits_made_after_the_pr_merged_keep_the_worktree():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-4"
    head = _worktree(clone, "feat/4", wt)
    (wt / "more.txt").write_text("follow-up")
    _git("add", ".", cwd=wt)
    _git("commit", "-qm", "after merge", cwd=wt)
    r = _clean(clone, {"feat/4": [head]})
    assert wt.exists() and "not in the merged PR" in r["kept"][0]["reason"]


def test_a_worktree_whose_pr_is_not_merged_is_not_touched():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-5"
    _worktree(clone, "feat/5", wt)
    r = _clean(clone, {"feat/other": ["0" * 40]})
    assert wt.exists() and r["removed"] == [] and r["kept"] == []


def test_the_main_checkout_is_never_removed_even_on_a_merged_branch():
    clone = _repo()
    head = _git("rev-parse", "HEAD", cwd=clone)
    _clean(clone, {"main": [head]})
    assert (clone / "f").exists()


def test_a_github_failure_removes_nothing():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-6"
    _worktree(clone, "feat/6", wt)

    def boom(repo):
        raise RuntimeError("gh: rate limit")
    r = dt.clean_merged_worktrees(clones=[clone], merged=boom, cwds=set(), derived_data=cs.HOME / "DD")
    assert wt.exists() and "could not check GitHub" in r["kept"][0]["reason"]


def test_helper_worktrees_in_dot_claude_worktrees_are_found_too():
    clone = _repo()
    wt = clone / ".claude" / "worktrees" / "agent-abc"
    wt.parent.mkdir(parents=True)
    head = _worktree(clone, "worktree-agent-abc", wt)
    _clean(clone, {"worktree-agent-abc": [head]})
    assert not wt.exists()


def _derived(dd, name, workspace):
    d = dd / name
    d.mkdir(parents=True)
    (d / "Build").mkdir()
    (d / "Build" / "x.o").write_bytes(b"x" * 1000)
    with open(d / "info.plist", "wb") as f:
        plistlib.dump({"WorkspacePath": str(workspace)}, f)
    old = (NOW - timedelta(hours=2)).timestamp()
    os.utime(d, (old, old))
    return d


def test_the_removed_worktrees_xcode_build_products_go_too_and_nobody_elses():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-7"
    head = _worktree(clone, "feat/7", wt)
    dd = cs.HOME / "DerivedData"
    mine = _derived(dd, "Seal-abc", wt / "Seal.xcodeproj")
    live = _derived(dd, "Seal-def", cs.HOME / "Developer" / "clarity" / "Seal.xcodeproj")
    r = _clean(clone, {"feat/7": [head]}, dd=dd)
    assert not mine.exists() and live.exists()
    assert r["freed_bytes"] > 0


def test_build_products_of_a_kept_worktree_stay():
    clone = _repo()
    wt = cs.HOME / "Developer" / "marvin-8"
    head = _worktree(clone, "feat/8", wt)
    (wt / "dirty.txt").write_text("x")
    dd = cs.HOME / "DerivedData"
    mine = _derived(dd, "Seal-abc", wt / "Seal.xcodeproj")
    _clean(clone, {"feat/8": [head]}, dd=dd)
    assert mine.exists()


def test_clones_are_found_on_disk_so_a_new_repo_needs_no_code_change():
    a = _repo("marvin")
    b = _repo("clarity-captions")
    (cs.HOME / "Developer" / "not-a-repo").mkdir()
    found = dt.discover_clones()
    assert a in found and b in found
    # a worktree's `.git` is a file, not a clone of its own
    _worktree(a, "feat/9", cs.HOME / "Developer" / "marvin-9")
    assert cs.HOME / "Developer" / "marvin-9" not in dt.discover_clones()


def test_after_merge_runs_the_step_on_every_mac_and_records_what_it_freed():
    seen = []

    def everywhere(step):
        seen.append(step)
        return [{"mac": "mac-mini-1", "ok": True, "changed": True, "detail": "removed 2 worktree(s), freed 1024 MiB"},
                {"mac": "macbook-pro-1", "ok": False, "changed": False, "detail": "couldn't run on that Mac"}]
    out = dt.after_merge(everywhere=everywhere)
    assert seen == [dt.STEP_MERGED_WORKTREES] and len(out) == 2


def test_the_merged_worktree_step_is_registered_for_first_aid():
    import purpose_metrics as pm
    assert dt.STEP_MERGED_WORKTREES in pm.FIRST_AID
    assert pm._SAFE_NAME.fullmatch(dt.STEP_MERGED_WORKTREES)


def test_the_first_aid_step_logs_its_frees_to_the_trigger_log(monkeypatch):
    monkeypatch.setattr(dt, "clean_merged_worktrees",
                        lambda **k: {"removed": [{"path": "/x"}], "kept": [], "freed_bytes": 3 * GiB})
    r = dt.merged_worktrees_step()
    assert r["changed"] is True and "1 worktree" in r["detail"]
    last = json.loads(dt.LOG_PATH.read_text().splitlines()[-1])
    assert last["trigger"] == "after-merge" and last["freed_bytes"] == 3 * GiB


# ── the reclaim pre-flight runs: only things that are already disposable ──────────────────────────────────────

def test_reclaim_runs_the_rebuildable_trims_merged_worktrees_and_the_download_cap(monkeypatch):
    import download_cache
    monkeypatch.setattr(cs, "clear_rebuildable", lambda: {"freed_bytes": 1 * GiB, "detail": "a"})
    monkeypatch.setattr(dt, "clean_merged_worktrees", lambda **k: {"removed": [], "kept": [], "freed_bytes": 2 * GiB})
    monkeypatch.setattr(download_cache, "enforce_cap", lambda **k: {"removed": [], "freed_bytes": 3 * GiB})
    r = dt.reclaim()
    assert r["freed_bytes"] == 6 * GiB


def test_reclaim_keeps_going_when_one_part_breaks(monkeypatch):
    import download_cache
    monkeypatch.setattr(cs, "clear_rebuildable", lambda: 1 / 0)
    monkeypatch.setattr(dt, "clean_merged_worktrees", lambda **k: {"removed": [], "kept": [], "freed_bytes": GiB})
    monkeypatch.setattr(download_cache, "enforce_cap", lambda **k: {"removed": [], "freed_bytes": 0})
    r = dt.reclaim()
    assert r["freed_bytes"] == GiB and "ZeroDivisionError" in r["detail"]


# ── aerial videos: WatchPaths trim, off until the owner chooses (item 1, Decision on the PR) ─────────────────────

def _aerials(n):
    d = cs.HOME / cs.AERIAL_SUBPATH
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"v{i}.mov").write_bytes(b"x" * 2**20)
        os.utime(d / f"v{i}.mov", (1000 + i, 1000 + i))
    return d


def test_aerial_watch_does_nothing_while_the_flag_is_off():
    d = _aerials(3)
    r = dt.aerial_watch(config={"aerial_watch_trim": False})
    assert r["ran"] is False and len(list(d.iterdir())) == 3


def test_aerial_watch_flag_ships_off():
    cfg = json.loads((LIB.parent / "config" / "disk_triggers.json").read_text())
    assert cfg["aerial_watch_trim"] is False


def test_aerial_watch_keeps_the_newest_when_on_and_records_it():
    d = _aerials(3)
    r = dt.aerial_watch(config={"aerial_watch_trim": True})
    assert r["ran"] is True and [p.name for p in d.iterdir()] == ["v2.mov"]
    last = json.loads(dt.LOG_PATH.read_text().splitlines()[-1])
    assert last["trigger"] == "aerial-watch" and last["freed_bytes"] == 2 * 2**20


def test_a_missing_or_broken_config_means_off(tmp_path, monkeypatch):
    d = _aerials(2)
    bad = tmp_path / "disk_triggers.json"
    bad.write_text("{not json")
    monkeypatch.setattr(dt, "CONFIG_PATH", bad)
    assert dt.aerial_watch()["ran"] is False
    monkeypatch.setattr(dt, "CONFIG_PATH", tmp_path / "missing.json")
    assert dt.aerial_watch()["ran"] is False
    assert len(list(d.iterdir())) == 2


def test_the_watchpaths_job_watches_the_aerial_folder_and_runs_the_flagged_trim():
    plist = plistlib.loads((LIB.parent / "config" / "launchd" / "com.marvin.aerial-watch.plist").read_bytes())
    assert plist["Label"] == "com.marvin.aerial-watch"
    assert any(p.endswith("com.apple.wallpaper/aerials/videos") for p in plist["WatchPaths"])
    assert plist["ProgramArguments"][-1] == "aerial-watch"
    assert plist.get("ThrottleInterval", 0) >= 30   # a burst of writes runs it once, not per file
    import job_catalog
    assert job_catalog.JOBS["aerial-watch"]["machine"] == "none"   # not placed until the owner answers


# ── the trigger log the Health card reads ───────────────────────────────────────────────────────────────────────

def test_record_and_summarize_since_a_time():
    dt.record("preflight", 2 * GiB, "x", now=NOW - timedelta(hours=3))
    dt.record("after-merge", 1 * GiB, "y", now=NOW - timedelta(minutes=30))
    dt.record("download-cache", GiB // 2, "z", now=NOW - timedelta(minutes=10))
    s = dt.summarize(dt.LOG_PATH.read_text().splitlines(), since=NOW - timedelta(hours=1))
    assert s["freed_bytes"] == GiB + GiB // 2
    assert s["by_trigger"] == {"after-merge": GiB, "download-cache": GiB // 2}
    assert s["refused"] == []


def test_summarize_lists_refusals_and_skips_garbled_lines():
    lines = ["garbage", json.dumps({"ts": NOW.isoformat(), "trigger": "preflight", "freed_bytes": 0, "ok": False,
                                    "what": "helper: #60"})]
    s = dt.summarize(lines, since=NOW - timedelta(hours=1))
    assert s["refused"] == ["helper: #60"]


# ── marvin#866: after a merge with no keychain (ssh / launchd), gh still reaches GitHub through the token file ─────

from test_gh_env import EXPIRED, GOOD, fake_gh  # noqa: E402


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    import gh_env
    p = tmp_path / "claude" / ".gh-token"
    p.parent.mkdir()
    monkeypatch.setattr(gh_env, "TOKEN_FILE", p)
    monkeypatch.delenv("GH_TOKEN", raising=False)   # conftest's second _no_real_github shadows the one that clears it
    return p


def _merged_wt(name="marvin-866", branch="fix/866"):
    clone = _repo()
    wt = cs.HOME / "Developer" / name
    head = _worktree(clone, branch, wt)
    return clone, wt, head


def _gh_merged(tmp_path, monkeypatch, branch, head):
    fake_gh(tmp_path, monkeypatch, stdout=json.dumps([{"headRefName": branch, "headRefOid": head}]))


def test_no_keychain_but_a_token_file_still_removes_the_merged_worktree(tmp_path, monkeypatch, token_file):
    clone, wt, head = _merged_wt()
    _gh_merged(tmp_path, monkeypatch, "fix/866", head)
    token_file.write_text(GOOD + "\n")
    r = dt.clean_merged_worktrees(clones=[clone], cwds=set(), derived_data=cs.HOME / "DD")   # the real gh path
    assert not wt.exists()
    assert [Path(x["path"]).name for x in r["removed"]] == ["marvin-866"]


def test_no_keychain_and_no_token_file_keeps_everything_and_says_so_plainly(tmp_path, monkeypatch, token_file):
    clone, wt, head = _merged_wt()
    _gh_merged(tmp_path, monkeypatch, "fix/866", head)
    monkeypatch.setattr(dt, "discover_clones", lambda: [clone])
    monkeypatch.setattr(cs, "_cwds_in_use", lambda: set())
    r = dt.merged_worktrees_step()
    assert wt.exists()
    assert "no GitHub token" in r["detail"] and ".gh-token" in r["detail"]
    last = json.loads(dt.LOG_PATH.read_text().splitlines()[-1])
    assert "no GitHub token" in last["detail"]


@pytest.mark.parametrize("content", ["", "  \n"])
def test_an_empty_token_file_keeps_everything_and_says_there_is_no_token(tmp_path, monkeypatch, token_file, content):
    clone, wt, head = _merged_wt()
    _gh_merged(tmp_path, monkeypatch, "fix/866", head)
    token_file.write_text(content)
    r = dt.clean_merged_worktrees(clones=[clone], cwds=set(), derived_data=cs.HOME / "DD")
    assert wt.exists() and r["removed"] == []
    assert "no GitHub token" in r["kept"][0]["reason"]


def test_an_expired_token_keeps_everything_says_why_and_never_logs_the_token(tmp_path, monkeypatch, token_file):
    clone, wt, head = _merged_wt()
    _gh_merged(tmp_path, monkeypatch, "fix/866", head)
    token_file.write_text(EXPIRED)
    monkeypatch.setattr(dt, "discover_clones", lambda: [clone])
    monkeypatch.setattr(cs, "_cwds_in_use", lambda: set())
    r = dt.merged_worktrees_step()
    assert wt.exists()
    assert "refused" in r["detail"] and "expired" in r["detail"]
    assert EXPIRED not in r["detail"] and EXPIRED not in dt.LOG_PATH.read_text()


def test_the_github_reason_is_said_once_not_once_per_worktree(tmp_path, monkeypatch, token_file):
    clone = _repo()
    for n in range(4):
        _worktree(clone, f"feat/{n}", cs.HOME / "Developer" / f"marvin-{n}")
    fake_gh(tmp_path, monkeypatch)
    monkeypatch.setattr(dt, "discover_clones", lambda: [clone])
    monkeypatch.setattr(cs, "_cwds_in_use", lambda: set())
    r = dt.merged_worktrees_step()
    assert r["detail"].count("no GitHub token") == 1 and "kept 4" in r["detail"]


def test_github_reachable_still_never_removes_uncommitted_work(tmp_path, monkeypatch, token_file):
    clone, wt, head = _merged_wt()
    (wt / "f").write_text("edited, not committed")
    _gh_merged(tmp_path, monkeypatch, "fix/866", head)
    token_file.write_text(GOOD)
    r = dt.clean_merged_worktrees(clones=[clone], cwds=set(), derived_data=cs.HOME / "DD")
    assert (wt / "f").read_text() == "edited, not committed" and "uncommitted" in r["kept"][0]["reason"]


def test_github_reachable_still_never_removes_a_worktree_a_process_is_in(tmp_path, monkeypatch, token_file):
    clone, wt, head = _merged_wt()
    _gh_merged(tmp_path, monkeypatch, "fix/866", head)
    token_file.write_text(GOOD)
    r = dt.clean_merged_worktrees(clones=[clone], cwds={str(wt.resolve())}, derived_data=cs.HOME / "DD")
    assert wt.exists() and "process" in r["kept"][0]["reason"]


def test_reclaim_also_trims_pytest_temp_dirs(monkeypatch):
    import download_cache
    monkeypatch.setattr(cs, "clear_rebuildable", lambda: {"freed_bytes": 0})
    monkeypatch.setattr(dt, "clean_merged_worktrees", lambda **k: {"removed": [], "kept": [], "freed_bytes": 0})
    monkeypatch.setattr(download_cache, "enforce_cap", lambda **k: {"removed": [], "freed_bytes": 0})
    monkeypatch.setattr(cs, "trim_pytest_temps", lambda **k: {"removed": ["pytest-1"], "kept": [], "freed_bytes": 4 * GiB})
    r = dt.reclaim()
    assert r["freed_bytes"] == 4 * GiB and "pytest temp" in r["detail"]
