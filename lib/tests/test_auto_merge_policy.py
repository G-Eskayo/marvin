"""Tests for auto_merge_policy.py (ADR 0064, #338): what a PR touches decides whether it may auto-merge.
Written to break it (ADR 0063): mixed areas, renames, deletions, path tricks, look-alike characters, lockfiles,
folder sprawl, empty PRs, unknown repos, and a missing or corrupt rules file.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_auto_merge_policy.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto_merge_policy as amp  # noqa: E402

MARVIN = "G-Eskayo/marvin"
RULES = amp.load_rules()                       # the shipped rules file
TOP = {"lib", "skills", "docs", "dashboard", "config", "brain-map", "bench", "bin"}


def f(path, add=10, rem=0, status="modified", previous=None):
    return {"path": path, "additions": add, "deletions": rem, "status": status, "previous_path": previous}


def decide(files, repo=MARVIN, **kw):
    kw.setdefault("existing_top_level", TOP)
    kw.setdefault("new_top_level_this_week", 0)
    kw.setdefault("ramp_open", True)
    kw.setdefault("render_check_passed", False)
    return amp.decide(repo, files, RULES, **kw)


# ── the plain cases ─────────────────────────────────────────────────────────

def test_an_owned_change_may_auto_merge():
    d = decide([f("lib/project_tagger.py"), f("lib/tests/test_project_tagger.py")])
    assert d["verdict"] == "auto", d["reasons"]


def test_one_core_file_makes_the_whole_pr_wait_and_says_which():
    d = decide([f("lib/project_tagger.py"), f("dashboard/webhook-server/merge.js")])
    assert d["verdict"] == "ask" and any("merge.js" in r for r in d["reasons"])


def test_every_core_area_named_in_adr_0064_is_core():
    for path in ("dashboard/webhook-server/merge.js", "config/auto_merge.json", "lib/auto_merge_policy.py",
                 "lib/marvin_hooks.py", "lib/gh_merge_guard.py", "bin/gh", "lib/code_sync.py",
                 "lib/disk_trim.py", "lib/cleanup_sweep.py", ".claude/settings.json"):
        assert decide([f(path)])["verdict"] == "ask", path


def test_the_rules_file_itself_is_core():
    assert amp.area("config/auto_merge.json", RULES, TOP) == "core"


# ── renames and deletions ───────────────────────────────────────────────────

def test_a_rename_out_of_a_core_path_is_core():
    d = decide([f("lib/harmless.py", status="renamed", previous="lib/gh_merge_guard.py")])
    assert d["verdict"] == "ask"


def test_deleting_a_core_file_waits():
    assert decide([f("lib/code_sync.py", add=0, rem=200, status="removed")])["verdict"] == "ask"


def test_deleting_an_owned_file_may_auto_merge():
    assert decide([f("lib/old_helper.py", add=0, rem=40, status="removed")])["verdict"] == "auto"


# ── path tricks ─────────────────────────────────────────────────────────────

def test_dot_dot_absolute_backslash_and_empty_paths_wait():
    for path in ("lib/../config/auto_merge.json", "/etc/passwd", "lib\\..\\bin\\gh", "", "lib//x.py"):
        assert decide([f(path)])["verdict"] == "ask", repr(path)


def test_case_differences_cannot_dodge_core():
    # macOS file systems ignore case: Config/Auto_Merge.json IS the rules file there
    assert decide([f("Config/Auto_Merge.json")])["verdict"] == "ask"
    assert decide([f("LIB/CODE_SYNC.PY")])["verdict"] == "ask"


def test_non_ascii_paths_wait_so_look_alikes_cannot_dodge_core():
    assert decide([f("lib/code_sуnc.py")])["verdict"] == "ask"      # Cyrillic у


# ── dependencies, size, repos ───────────────────────────────────────────────

def test_any_dependency_manifest_or_lockfile_waits():
    for path in ("dashboard/package.json", "dashboard/package-lock.json", "requirements.txt", "pyproject.toml",
                 "some/Package.swift", "some/Package.resolved", "requirements-dev.txt"):
        d = decide([f("lib/x.py"), f(path)])
        assert d["verdict"] == "ask" and any("dependenc" in r for r in d["reasons"]), path


def test_more_than_1500_changed_lines_waits():
    assert decide([f("lib/x.py", add=1400), f("lib/tests/test_x.py", add=101)])["verdict"] == "ask"
    assert decide([f("lib/x.py", add=1400), f("lib/tests/test_x.py", add=100)])["verdict"] == "auto"


def test_finance_os_always_asks_even_when_everything_else_would_allow_it():
    # a profile, an open trust ramp, an owned file: still asks, and says it's because it's finance-os
    d = decide([f("src/x.ts")], repo="G-Eskayo/finance-os", existing_top_level={"src"},
               profile={"auto_merge": {"core": []}}, ramp_open=True)
    assert d["verdict"] == "ask" and any("always waits" in r for r in d["reasons"])


def test_an_empty_pr_waits():
    assert decide([])["verdict"] == "ask"


def test_another_project_needs_its_trust_ramp_and_its_own_core_paths():
    prof = {"auto_merge": {"core": ["deploy/**"]}}
    closed = decide([f("src/a.ts")], repo="G-Eskayo/portfolio-website-updater", profile=prof,
                    existing_top_level={"src", "deploy"}, ramp_open=False)
    assert closed["verdict"] == "ask" and any("trust" in r for r in closed["reasons"])
    opened = decide([f("src/a.ts")], repo="G-Eskayo/portfolio-website-updater", profile=prof,
                    existing_top_level={"src", "deploy"}, ramp_open=True)
    assert opened["verdict"] == "auto"
    core = decide([f("deploy/x.php")], repo="G-Eskayo/portfolio-website-updater", profile=prof,
                  existing_top_level={"src", "deploy"}, ramp_open=True)
    assert core["verdict"] == "ask"


def test_a_project_with_no_profile_waits():
    assert decide([f("src/a.ts")], repo="G-Eskayo/unknown", existing_top_level={"src"})["verdict"] == "ask"


# ── UI and new folders ──────────────────────────────────────────────────────

def test_a_ui_change_waits_until_the_render_check_passed():
    assert decide([f("dashboard/src/components/X.jsx")])["verdict"] == "ask"
    assert decide([f("dashboard/src/components/X.jsx")], render_check_passed=True)["verdict"] == "auto"


def test_a_new_folder_inherits_its_parent():
    assert decide([f("lib/newpkg/mod.py", status="added")])["verdict"] == "auto"
    assert decide([f(".claude/hooks/new.py", status="added")])["verdict"] == "ask"


def test_new_top_level_folders_are_owned_up_to_three_a_week():
    assert decide([f("research/notes.md", status="added")], new_top_level_this_week=2)["verdict"] == "auto"
    d = decide([f("research/notes.md", status="added")], new_top_level_this_week=3)
    assert d["verdict"] == "ask" and any("top-level" in r for r in d["reasons"])


def test_two_new_top_level_folders_in_one_pr_count_twice():
    d = decide([f("aaa/x.md", status="added"), f("bbb/y.md", status="added")], new_top_level_this_week=2)
    assert d["verdict"] == "ask"


# ── the rules file itself ───────────────────────────────────────────────────

def test_a_missing_or_corrupt_rules_file_means_ask_for_everything(tmp_path):
    assert amp.load_rules(tmp_path / "none.json") == amp.ASK_ALL
    bad = tmp_path / "r.json"
    bad.write_text("{not json")
    assert amp.load_rules(bad) == amp.ASK_ALL
    bad.write_text(json.dumps({"core": "not a list"}))
    assert amp.load_rules(bad) == amp.ASK_ALL
    d = amp.decide(MARVIN, [f("lib/project_tagger.py")], amp.ASK_ALL, existing_top_level=TOP,
                   new_top_level_this_week=0, ramp_open=True)
    assert d["verdict"] == "ask"


def test_every_reason_is_readable_and_the_verdict_is_only_auto_or_ask():
    d = decide([f("lib/x.py"), f("bin/gh"), f("dashboard/package.json")])
    assert d["verdict"] in ("auto", "ask") and all(isinstance(r, str) and r for r in d["reasons"])


def test_code_that_handles_credentials_is_core():
    for path in ("dashboard/webhook-server/gh_auth.js", "dashboard/electron/main/path.js", "lib/mobile_auth.py",
                 "lib/gh_token_store.py", "config/secrets.json"):
        assert decide([f(path)])["verdict"] == "ask", path
