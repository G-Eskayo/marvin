#!/usr/bin/env python3
"""The map's Infrastructure section lists every script a live hook runs. It was empty after #291 moved the hooks
from settings.local.json to settings.json and wrapped them in the gate, because it read only the old file.
Run: python -m pytest brain-map/tests/test_infrastructure_hooks.py -v"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generate as g

GATE = "/v/python /h/.agents/lib/marvin_hooks.py gate"


def _settings(tmp_path, monkeypatch, user, local=None):
    paths = []
    for name, data in (("settings.json", user), ("settings.local.json", local)):
        p = tmp_path / name
        if data is not None:
            p.write_text(json.dumps(data))
        paths.append(p)
    monkeypatch.setattr(g, "HOOK_SETTINGS_PATHS", tuple(paths))


def test_gated_user_level_hooks_become_infrastructure_nodes(tmp_path, monkeypatch):
    script = tmp_path / "guard.py"
    script.write_text('"""Stops a merge nobody approved. More detail."""\n')
    _settings(tmp_path, monkeypatch, {"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": f"{GATE} all -- /v/python {script}"}]}]}})
    nodes = {n["id"]: n for n in g.build_hook_children({"hook_overrides": {}})}
    assert set(nodes) == {"marvin_hooks.py", "guard.py"}
    assert nodes["guard.py"]["cat"] == "infra"
    assert nodes["guard.py"]["desc"] == "Hook (PreToolUse: Bash) — Stops a merge nobody approved."


def test_a_script_wired_on_several_events_is_one_node_naming_each(tmp_path, monkeypatch):
    hook = lambda arg: {"matcher": "Edit", "hooks": [{"type": "command", "command": f"/v/python /x/work.py hook {arg}"}]}
    _settings(tmp_path, monkeypatch, {"hooks": {"PreToolUse": [hook("pre")], "PostToolUse": [hook("post")]}})
    [node] = g.build_hook_children({"hook_overrides": {}})
    assert node["desc"].startswith("Hook (PreToolUse: Edit; PostToolUse: Edit)")


def test_hand_written_overrides_still_win(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch, {}, {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/v/python /x/a.py"}]}]}})
    override = {"id": "a.py", "cat": "infra", "desc": "curated", "children": []}
    [node] = g.build_hook_children({"hook_overrides": {"a.py": override}})
    assert node["desc"] == "curated"


def test_no_settings_means_an_empty_section_not_a_crash(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch, None)
    assert g.build_hook_children({"hook_overrides": {}}) == []
