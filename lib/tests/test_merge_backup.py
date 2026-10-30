"""Tests for merge_backup.py (marvin#940 part 4: another Mac merges when the Mini can't, only when it's fit to). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_merge_backup.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import merge_backup as mb  # noqa: E402

MARVIN = mb.marvin_repo()
SEAL = MARVIN.split("/")[0] + "/clarity-captions"


def facts(**kw):
    base = dict(machine="macbook-pro-1", platform="darwin", os="macOS 27.0", on_power=True, at_home=True,
                pressure="normal", merge_running=False, test_run=None)
    return mb.Facts(**{**base, **kw})


def test_a_macbook_on_power_at_home_and_idle_is_ready():
    v = mb.verdict(facts(), SEAL)
    assert v == {"ready": True, "why": [], "machine": "macbook-pro-1", "os": "macOS 27.0"}


@pytest.mark.parametrize("kw,why", [
    (dict(on_power=False), "it is on battery"),
    (dict(on_power=None), "it is on battery"),               # unknown power counts as battery: never guess yes
    (dict(at_home=False), "it is not at home"),
    (dict(at_home=None), "it is not at home"),
    (dict(pressure="warn"), "its memory is under pressure"),
    (dict(pressure="critical"), "its memory is under pressure"),
    (dict(merge_running=True), "it is merging something already"),
    (dict(test_run="pytest lib/tests"), "it is running pytest lib/tests"),
])
def test_each_reason_it_is_not_fit_is_named(kw, why):
    v = mb.verdict(facts(**kw), MARVIN)
    assert v["ready"] is False and why in " ".join(v["why"])


def test_an_unreadable_pressure_level_does_not_block():
    assert mb.verdict(facts(pressure=None), MARVIN)["ready"] is True


def test_a_linux_box_takes_marvin_prs_only():
    """marvin#945 slots in here: Seal Speak needs Xcode."""
    linux = facts(machine="linux-box-1", platform="linux", os="Linux 6.8")
    assert mb.verdict(linux, MARVIN)["ready"] is True
    v = mb.verdict(linux, SEAL)
    assert v["ready"] is False and "needs a Mac with Xcode" in " ".join(v["why"])


def test_power_from_pmset_and_linux_power_supply(tmp_path):
    assert mb.on_power_darwin("Now drawing from 'AC Power'\n") is True
    assert mb.on_power_darwin("Now drawing from 'Battery Power'\n") is False
    (tmp_path / "AC").mkdir()
    (tmp_path / "AC" / "type").write_text("Mains\n")
    (tmp_path / "AC" / "online").write_text("1\n")
    assert mb.on_power_linux(tmp_path) is True
    (tmp_path / "AC" / "online").write_text("0\n")
    assert mb.on_power_linux(tmp_path) is False
    assert mb.on_power_linux(tmp_path / "none") is True   # no power supply at all: a desktop on mains


def test_the_home_anchor_itself_is_at_home(monkeypatch):
    monkeypatch.setattr(mb, "_home_anchor", lambda: "mac-mini-1")
    assert mb.at_home("mac-mini-1") is True


def test_the_command_prints_one_json_line_and_never_fails():
    out = subprocess.run([sys.executable, str(LIB / "merge_backup.py"), "ready", "--repo", MARVIN],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
    v = json.loads(out.stdout.strip().splitlines()[-1])
    assert set(v) == {"ready", "why", "machine", "os"} and isinstance(v["ready"], bool)
