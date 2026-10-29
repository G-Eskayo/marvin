"""Tests for helper_tab.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_helper_tab.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import helper_tab as ht  # noqa: E402


def pane(window, tab, pane_id, tab_title="", title="zsh"):
    return {"window_id": window, "tab_id": tab, "pane_id": pane_id, "tab_title": tab_title, "title": title}


# ── tab_title ────────────────────────────────────────────────────────────────

def test_title_names_group_and_work():
    assert ht.tab_title("Seal Speak", "#60 split wiring", "running") == "● Seal Speak · #60 split wiring"


def test_title_marks_done_and_failed():
    assert ht.tab_title("Seal Speak", "#60", "done").startswith("✓ ")
    assert ht.tab_title("Seal Speak", "#60", "failed").startswith("✗ ")


def test_title_rejects_unknown_state():
    with pytest.raises(ValueError):
        ht.tab_title("Seal Speak", "#60", "paused")


def test_title_strips_separator_from_group_so_parsing_stays_unambiguous():
    # A group containing the separator would make the group/work split ambiguous for the tab colouring.
    assert ht.tab_title("Seal · Speak", "x", "running") == "● Seal Speak · x"


@pytest.mark.parametrize("group,title", [("", "x"), ("  ", "x"), ("Seal", ""), ("Seal", "   ")])
def test_title_requires_group_and_work(group, title):
    with pytest.raises(ValueError):
        ht.tab_title(group, title, "running")


def test_parse_round_trips():
    assert ht.parse_title(ht.tab_title("MARVIN", "#735 screenshot gate", "done")) == ("done", "MARVIN", "#735 screenshot gate")


@pytest.mark.parametrize("raw", ["", "zsh", "◑ Translation feature release readiness", "● no separator"])
def test_parse_ignores_tabs_that_are_not_helpers(raw):
    assert ht.parse_title(raw) is None


# ── pick_window ──────────────────────────────────────────────────────────────

def test_no_window_open_means_start_one():
    assert ht.pick_window([]) is None


def test_reuses_the_window_that_already_holds_helpers():
    panes = [pane(0, 0, 0, title="Claude session"),
             pane(3, 7, 9, tab_title=ht.tab_title("MARVIN", "digest", "running"))]
    assert ht.pick_window(panes) == 3


def test_finished_helpers_still_anchor_the_window():
    panes = [pane(0, 0, 0), pane(2, 4, 5, tab_title=ht.tab_title("Seal Speak", "#60", "failed"))]
    assert ht.pick_window(panes) == 2


def test_without_helpers_uses_the_open_window():
    assert ht.pick_window([pane(4, 1, 1), pane(4, 2, 2)]) == 4


def test_without_helpers_and_several_windows_picks_the_lowest_id_deterministically():
    assert ht.pick_window([pane(6, 1, 1), pane(2, 2, 2), pane(9, 3, 3)]) == 2


def test_helpers_in_two_windows_converge_on_the_one_with_most_helpers():
    h = lambda w, t, p: pane(w, t, p, tab_title=ht.tab_title("G", f"w{p}", "running"))
    assert ht.pick_window([h(1, 1, 1), h(5, 2, 2), h(5, 3, 3)]) == 5


# ── wrapper and run_helper: the real script, a fake wezterm that records its title ─────────────────────────

def _fake_env(tmp_path):
    fake = tmp_path / "wezterm"
    fake.write_text(f'#!/bin/sh\nprintf "%s" "$5" > {tmp_path}/title\n')
    fake.chmod(0o755)
    return {"WEZTERM_PANE": "7", "PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "HELPER_TAB_WEZTERM": str(fake),
            "HELPER_TAB_QUIET": "1", "HELPER_TAB_JOBS_DIR": str(tmp_path / "jobs")}


def _run_wrapper(tmp_path, command, group="G", title="w", on_exit=None):
    script = ht.wrapper_script(command, group, title, on_exit).replace("exec zsh -l", "")
    return subprocess.run(["zsh", "-c", script], capture_output=True, text=True, env=_fake_env(tmp_path))


def test_wrapper_keeps_the_tab_open_afterwards():
    assert ht.wrapper_script(["true"], "G", "w").rstrip().endswith("exec zsh -l")


def test_success_retitles_done_and_logs_a_passed_run(tmp_path):
    out = _run_wrapper(tmp_path, ["echo", "hello"], "Seal Speak", "#60 split")
    assert "hello" in out.stdout
    assert (tmp_path / "title").read_text() == ht.tab_title("Seal Speak", "#60 split", "done")
    doc = json.loads((tmp_path / "jobs" / f"{ht.job_name('Seal Speak', '#60 split')}.json").read_text())
    assert doc["runs"][-1]["status"] == "passed"


def test_failure_retitles_failed_logs_it_and_keeps_the_exit_code(tmp_path):
    out = _run_wrapper(tmp_path, ["sh", "-c", "exit 3"])
    assert (tmp_path / "title").read_text() == ht.tab_title("G", "w", "failed")
    assert "exit 3" in out.stdout
    doc = json.loads((tmp_path / "jobs" / f"{ht.job_name('G', 'w')}.json").read_text())
    assert doc["runs"][-1]["status"] == "failed"


def test_on_exit_fires_once_with_the_exit_code(tmp_path):
    _run_wrapper(tmp_path, ["sh", "-c", "exit 2"], on_exit=f'echo "$HELPER_RC" >> {tmp_path}/fired')
    assert (tmp_path / "fired").read_text() == "2\n"


def test_missing_command_fails_the_tab_instead_of_crashing_the_wrapper(tmp_path):
    out = _run_wrapper(tmp_path, ["/no/such/helper"])
    assert (tmp_path / "title").read_text() == ht.tab_title("G", "w", "failed")


def test_hostile_titles_and_arguments_are_never_expanded(tmp_path):
    canary = tmp_path / "pwned"
    hostile = f"it's $(touch {canary}) `touch {canary}`"
    out = _run_wrapper(tmp_path, ["printf", "%s", hostile], "G", hostile)
    assert out.stdout.startswith(hostile)
    assert (tmp_path / "title").read_text() == ht.tab_title("G", hostile, "done")
    assert not canary.exists()


# ── install_wezterm ─────────────────────────────────────────────────────────

def test_install_adds_the_require_before_return_and_is_idempotent(tmp_path):
    cfg = tmp_path / "wezterm.lua"
    cfg.write_text("local wezterm = require 'wezterm'\nlocal config = wezterm.config_builder()\nconfig.x = 1\nreturn config\n")
    assert ht.install_wezterm(cfg, tmp_path / "helper_tabs.lua") == "installed"
    text = cfg.read_text()
    assert text.index(ht.INSTALL_LINE) < text.index("return config") and "config.x = 1" in text
    assert ht.install_wezterm(cfg, tmp_path / "helper_tabs.lua") == "already installed"
    assert cfg.read_text() == text


def test_install_creates_a_config_when_there_is_none(tmp_path):
    cfg = tmp_path / "sub" / "wezterm.lua"
    assert ht.install_wezterm(cfg, tmp_path / "helper_tabs.lua") == "installed"
    assert ht.INSTALL_LINE in cfg.read_text()


def test_install_refuses_a_config_it_cannot_place_safely(tmp_path):
    cfg = tmp_path / "wezterm.lua"
    cfg.write_text("return { font_size = 14 }\n")
    with pytest.raises(ValueError):
        ht.install_wezterm(cfg, tmp_path / "helper_tabs.lua")
    assert cfg.read_text() == "return { font_size = 14 }\n"


# ── disk (marvin#765): check space before a helper starts, tidy its downloads when it ends ───────────────────

def test_launch_refuses_before_opening_a_tab_when_the_disk_is_too_full(monkeypatch, capsys):
    import disk_triggers
    seen = []
    monkeypatch.setattr(disk_triggers, "preflight",
                        lambda what, **k: seen.append(what) or {"ok": False, "message": f"Not starting {what}: 2.0 GB free"})
    monkeypatch.setattr(ht, "_list_panes", lambda: pytest.fail("no tab may open on a full disk"))
    monkeypatch.setenv("HELPER_TAB_QUIET", "1")
    monkeypatch.delenv("HELPER_TAB_SKIP_DISK_CHECK", raising=False)
    assert ht.launch("Seal Speak", "#60 split", ["true"], "/tmp") == ht.DISK_REFUSED_RC
    assert seen == ["helper Seal Speak: #60 split"]
    assert "Not starting helper Seal Speak: #60 split" in capsys.readouterr().err


def test_launch_goes_ahead_when_the_preflight_passes(monkeypatch):
    import disk_triggers
    monkeypatch.setattr(disk_triggers, "preflight", lambda what, **k: {"ok": True, "message": ""})
    monkeypatch.delenv("HELPER_TAB_SKIP_DISK_CHECK", raising=False)
    opened = []
    monkeypatch.setattr(ht, "_list_panes", lambda: opened.append(1) or [pane(1, 1, 1)])
    monkeypatch.setattr(ht.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="9\n"))
    assert ht.launch("G", "w", ["true"], "/tmp") == 0
    assert opened


def test_the_disk_check_can_be_skipped_on_purpose(monkeypatch):
    import disk_triggers
    monkeypatch.setattr(disk_triggers, "preflight", lambda *a, **k: pytest.fail("skipped on purpose"))
    monkeypatch.setenv("HELPER_TAB_SKIP_DISK_CHECK", "1")
    monkeypatch.setattr(ht, "_list_panes", lambda: [pane(1, 1, 1)])
    monkeypatch.setattr(ht.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="9\n"))
    assert ht.launch("G", "w", ["true"], "/tmp") == 0


def test_the_helper_is_told_where_the_download_cache_is(tmp_path):
    out = _run_wrapper(tmp_path, ["sh", "-c", 'printf "%s" "$MARVIN_DOWNLOAD_CACHE"'])
    assert out.stdout.startswith(str(tmp_path / ".cache" / "marvin-downloads"))


def test_the_helpers_exit_enforces_the_download_cap_without_changing_its_exit_code(monkeypatch, tmp_path):
    import download_cache
    calls = []
    monkeypatch.setattr(download_cache, "enforce_cap", lambda **k: calls.append(1) or {"removed": [], "freed_bytes": 0})
    monkeypatch.setenv("HELPER_TAB_QUIET", "1")
    monkeypatch.setenv("HELPER_TAB_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.delenv("WEZTERM_PANE", raising=False)
    assert ht.run_helper("G", "w", ["sh", "-c", "exit 4"]) == 4
    assert calls == [1]
    monkeypatch.setattr(download_cache, "enforce_cap", lambda **k: 1 / 0)
    assert ht.run_helper("G", "w", ["true"]) == 0   # a broken trim never changes the helper's result
