"""mac-mini-2012 runs MARVIN's own scheduled jobs (marvin#911) under ADR 0069: it never pushes, never writes GitHub or
the synced ~/.claude, holds no secrets, and must never remove what a live process uses. These tests try to make the
cleanup sweep and the health check break those rules on a pull-only node."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import cleanup_sweep as cs
import gh_env
import host_os
import machine_profile as mp

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

REGISTRY = {
    "mac-mini-1": {"accepts": ["general", "macos"], "os": "macos"},
    "mac-mini-2012": {"accepts": ["security", "quarantine", "test", "bench"], "os": "linux"},
    "old-mac": {},   # predates `accepts` and `os`: a Mac, a full node
}


# ── which machine is pull-only ─────────────────────────────────────────

@pytest.mark.parametrize("me, os_name, expected", [
    ("mac-mini-1", "macos", False),
    ("mac-mini-2012", "linux", True),
    ("old-mac", "macos", False),
    ("unregistered-linux", "linux", True),    # an unknown non-Mac is treated as the untrusted kind
    ("unregistered-mac", "macos", False),     # an unregistered Mac keeps today's behaviour
])
def test_pull_only_follows_adr_0069_general_work_is_for_full_nodes_only(monkeypatch, me, os_name, expected):
    monkeypatch.setattr(mp, "_load_registry", lambda: REGISTRY)
    monkeypatch.setattr(mp, "registry_id", lambda: me)
    monkeypatch.setattr(mp.host_os, "os_name", lambda: os_name)
    assert mp.pull_only() is expected


def test_a_linux_box_registered_as_a_mac_like_node_is_still_not_trusted_by_os_alone(monkeypatch):
    # The registry decides for a registered machine: a Linux node that accepts general work is a full node.
    monkeypatch.setattr(mp, "_load_registry", lambda: {"linux-builder": {"accepts": ["general"], "os": "linux"}})
    monkeypatch.setattr(mp, "registry_id", lambda: "linux-builder")
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "linux")
    assert mp.pull_only() is False


def test_a_broken_accepts_field_counts_as_pull_only(monkeypatch):
    monkeypatch.setattr(mp, "_load_registry", lambda: {"me": {"accepts": "general"}})   # a string, not a list
    monkeypatch.setattr(mp, "registry_id", lambda: "me")
    assert mp.pull_only() is True


# ── lsof lives in /usr/bin on Linux ────────────────────────────────────

def test_lsof_is_found_where_kali_installs_it(monkeypatch):
    monkeypatch.setattr(host_os.os, "access", lambda p, mode: str(p) == "/usr/bin/lsof")
    monkeypatch.setattr(host_os.shutil, "which", lambda name: None)
    assert host_os.lsof_bin() == "/usr/bin/lsof"


def test_lsof_on_a_mac_is_usr_sbin_even_with_a_bare_path(monkeypatch):
    monkeypatch.setattr(host_os.os, "access", lambda p, mode: str(p) in ("/usr/sbin/lsof", "/usr/bin/lsof"))
    assert host_os.lsof_bin() == "/usr/sbin/lsof"


def test_no_lsof_anywhere_is_none(monkeypatch):
    monkeypatch.setattr(host_os.os, "access", lambda p, mode: False)
    monkeypatch.setattr(host_os.shutil, "which", lambda name: None)
    assert host_os.lsof_bin() is None


def test_the_sweep_sees_a_process_inside_a_worktree_on_linux(monkeypatch, tmp_path):
    """Before #911 the sweep ran /usr/sbin/lsof, which Kali doesn't have: every worktree read as unused."""
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd[0])
        class R:
            stdout = f"p123\nn{tmp_path}/wt/sub\n"
        return R()
    monkeypatch.setattr(cs.host_os, "lsof_bin", lambda: "/usr/bin/lsof")
    monkeypatch.setattr(cs.subprocess, "run", fake_run)
    cwds = cs._cwds_in_use()
    assert seen == ["/usr/bin/lsof"]
    assert cs._in_use(tmp_path / "wt", cwds) is True


def test_without_lsof_the_pytest_trim_removes_nothing(monkeypatch):
    monkeypatch.setattr(cs.host_os, "lsof_bin", lambda: None)
    assert cs._open_paths() is None   # the caller then keeps every folder


# ── the sweep on a pull-only node ──────────────────────────────────────

@pytest.fixture
def log_path(tmp_path, monkeypatch):
    p = tmp_path / "mr-pipeline-sweep.md"
    monkeypatch.setattr(cs, "OUTPUT_PATH", p)
    return p


def _old_dirty_wt(tmp_path):
    return {"path": tmp_path / "wt", "branch": "ticket/5-x", "clone": tmp_path, "repo": "G-Eskayo/marvin",
            "ahead": 2, "dirty": True, "age_hours": 500, "in_use": False}


def test_pull_only_sweep_never_releases_claims_pushes_backups_or_promotes(log_path, tmp_path, monkeypatch):
    promoted = []
    monkeypatch.setattr(cs, "_default_outcome_check", lambda: promoted.append(1))
    cs.run_daily_sweep(
        list_claimed_open_issues=lambda: pytest.fail("asked GitHub for claims on a pull-only node"),
        list_worktrees=lambda: [_old_dirty_wt(tmp_path)],
        pr_state=lambda repo, branch: None,
        is_claimed=lambda repo, n: False,
        release=lambda n, m: pytest.fail("released a claim from a pull-only node"),
        remove_worktree=lambda w: pytest.fail("removed a worktree whose work was never backed up"),
        backup=lambda w: pytest.fail("pushed a backup branch from a pull-only node"),
        now=NOW, pull_only=True,
    )
    assert promoted == []
    log = log_path.read_text()
    assert "pull-only" in log.lower() and "ADR 0069" in log
    assert "not backed up" in log and str(tmp_path / "wt") in log


def test_pull_only_still_removes_a_merged_prs_clean_worktree(log_path, tmp_path):
    # Purely local, lossless (git refuses if anything is uncommitted): allowed on the box.
    wt = {**_old_dirty_wt(tmp_path), "dirty": False, "ahead": 0}
    removed = []
    out = cs.run_daily_sweep(list_worktrees=lambda: [wt], pr_state=lambda r, b: "MERGED", is_claimed=lambda r, n: False,
                             remove_worktree=lambda w: removed.append(w) or True, now=NOW, pull_only=True)
    assert removed and out["worktrees_removed"] == 1


def test_pull_only_never_removes_a_worktree_a_process_is_inside(log_path, tmp_path):
    wt = {**_old_dirty_wt(tmp_path), "dirty": False, "ahead": 0, "in_use": True}
    cs.run_daily_sweep(list_worktrees=lambda: [wt], pr_state=lambda r, b: "MERGED", is_claimed=lambda r, n: False,
                       remove_worktree=lambda w: pytest.fail("removed a worktree a process is inside"),
                       now=NOW, pull_only=True)


def test_no_github_token_skips_claims_with_a_clear_line_instead_of_crashing(log_path, monkeypatch):
    def no_token():
        raise gh_env.GhError("no GitHub token for this shell (the keychain is locked ...)")
    out = cs.run_daily_sweep(list_claimed_open_issues=no_token, list_worktrees=lambda: [], now=NOW, pull_only=False,
                             release=lambda n, m: pytest.fail("released with no list"))
    assert out["stale_claims_released"] == 0
    log = log_path.read_text()
    assert "Stale claims not checked" in log and "no GitHub token" in log
    assert "Nothing to clean up" not in log   # a skipped step is not "all clean"


def test_with_no_token_a_worktree_is_kept_never_removed(log_path, tmp_path, monkeypatch):
    def no_token(*a):
        raise gh_env.GhError("no GitHub token for this shell")
    wt = {**_old_dirty_wt(tmp_path), "dirty": False, "ahead": 0}
    cs.run_daily_sweep(list_worktrees=lambda: [wt], pr_state=no_token, is_claimed=no_token,
                       remove_worktree=lambda w: pytest.fail("removed a worktree GitHub was never asked about"),
                       now=NOW, pull_only=True)
    assert "could not check GitHub" in log_path.read_text()


def test_the_pull_only_answer_comes_from_the_registry_and_fails_closed(monkeypatch):
    monkeypatch.setattr(cs.machine_profile, "pull_only", lambda: (_ for _ in ()).throw(OSError("unreadable")))
    assert cs._is_pull_only() is True
    monkeypatch.setattr(cs.machine_profile, "pull_only", lambda: False)
    assert cs._is_pull_only() is False


def test_main_on_a_pull_only_node_leaves_the_synced_suggestions_file_alone(log_path, tmp_path, monkeypatch):
    """output_contracts.run_promotion rewrites ~/.claude/suggestions.md, a synced file the box must never write."""
    import output_contracts
    monkeypatch.setattr(output_contracts, "run_promotion", lambda *a, **k: pytest.fail("rewrote suggestions.md"))
    monkeypatch.setattr(cs, "_default_outcome_check", cs.__dict__["_default_outcome_check"])
    monkeypatch.setattr(cs, "_is_pull_only", lambda: True)
    monkeypatch.setattr(cs, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(cs, "_default_list_worktrees", lambda: [])
    cs.main()
    assert "pull-only" in log_path.read_text().lower()


# ── the health check's own result on the box ───────────────────────────

def test_on_a_pull_only_node_the_health_sweep_writes_beside_the_minis_view(monkeypatch, tmp_path):
    """On mac-mini-2012 health-status.json is the Mini's whole-network view, copied there every 2 min for the
    dashboard (marvin-observer-feed). The box's own sweep must not race it."""
    import health_checks as hc
    monkeypatch.setattr(hc, "STATUS_PATH", tmp_path / "health-status.json")
    monkeypatch.setattr(hc.machine_profile, "pull_only", lambda: True)
    (tmp_path / "health-status.json").write_text('{"from": "mini"}')
    hc.write_status({"overall": "green", "checks": []})
    assert json.loads((tmp_path / "health-status.json").read_text()) == {"from": "mini"}
    assert json.loads((tmp_path / "health-status.local.json").read_text())["overall"] == "green"


def test_on_a_mac_the_health_sweep_writes_where_it_always_did(monkeypatch, tmp_path):
    import health_checks as hc
    monkeypatch.setattr(hc, "STATUS_PATH", tmp_path / "health-status.json")
    monkeypatch.setattr(hc.machine_profile, "pull_only", lambda: False)
    hc.write_status({"overall": "green", "checks": []})
    assert json.loads((tmp_path / "health-status.json").read_text())["overall"] == "green"
    assert not (tmp_path / "health-status.local.json").exists()


def test_if_the_node_kind_cannot_be_read_the_health_sweep_still_writes(monkeypatch, tmp_path):
    import health_checks as hc
    monkeypatch.setattr(hc, "STATUS_PATH", tmp_path / "health-status.json")
    monkeypatch.setattr(hc.machine_profile, "pull_only", lambda: (_ for _ in ()).throw(ValueError("bad registry")))
    hc.write_status({"overall": "red", "checks": []})
    written = list(tmp_path.glob("health-status*.json"))
    assert len(written) == 1
