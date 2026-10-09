"""MARVIN's hooks at user level, each declaring the launch kinds it runs for (marvin#291, ADR 0059)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import marvin_hooks as mh
import marvin_launcher as ml

GATE = Path(mh.__file__)


def _gate(kinds, cmd, kind=None, stdin="{}"):
    env = {"PATH": "/usr/bin:/bin"}
    if kind is not None:
        env[ml.KIND_ENV] = kind
    return subprocess.run([sys.executable, str(GATE), "gate", kinds, "--", *cmd], input=stdin,
                          capture_output=True, text=True, env=env)


def test_a_session_with_no_marker_is_interactive_and_runs_interactive_hooks():
    assert _gate("interactive", ["/bin/echo", "ran"]).stdout == "ran\n"


def test_a_headless_kind_skips_interactive_only_hooks():
    r = _gate("interactive", ["/bin/echo", "ran"], kind="ticket-executor")
    assert (r.returncode, r.stdout) == (0, "")


def test_all_kind_hooks_run_for_every_kind_and_unknown_ones():
    for kind in [*ml.KINDS, "bench"]:
        assert _gate("all", ["/bin/echo", "ran"], kind=kind).stdout == "ran\n"


def test_the_hook_gets_the_event_on_stdin_and_its_exit_code_is_kept():
    r = _gate("all", ["/bin/sh", "-c", "cat; exit 2"], stdin='{"tool_name": "Bash"}')
    assert r.stdout == '{"tool_name": "Bash"}' and r.returncode == 2  # exit 2 is how a PreToolUse guard blocks


def test_every_hook_declares_known_kinds():
    for hook in mh.HOOKS:
        assert hook.kinds == {"all"} or hook.kinds <= set(ml.KINDS), hook


def test_safety_and_telemetry_hooks_run_everywhere_and_session_upkeep_only_interactive():
    by_script = {Path(h.command[-1] if h.command[0] != "/bin/sh" else "session-start").name: h for h in mh.HOOKS}
    assert by_script["gh_merge_guard.py"].kinds == {"all"}
    assert by_script["skill_activity.py"].kinds == {"all"}
    for upkeep in ("background_review.py", "trigger_code_sync.py", "auto_route_hook.py", "session-start"):
        assert by_script[upkeep].kinds == {"interactive"}, upkeep


def _write(path, data):
    path.write_text(json.dumps(data, indent=2))


def test_install_moves_hooks_to_user_settings_and_sets_one_memory(tmp_path):
    user, local = tmp_path / "settings.json", tmp_path / "settings.local.json"
    _write(user, {"model": "opus", "permissions": {"allow": ["Read"]}})
    _write(local, {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PostToolUse": []}})
    mh.install(user, local, memory_dir=tmp_path / "memory")
    u, l = json.loads(user.read_text()), json.loads(local.read_text())
    assert u["model"] == "opus" and u["permissions"] == {"allow": ["Read"]}  # nothing else touched
    assert u["autoMemoryDirectory"] == str(tmp_path / "memory")
    assert set(u["hooks"]) == {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit"}
    assert all("marvin_hooks.py gate" in h["command"] for groups in u["hooks"].values()
               for g in groups for h in g["hooks"])
    assert "hooks" not in l and l["permissions"] == {"allow": ["Bash(ls)"]}
    assert (tmp_path / "settings.local.json.pre-marvin-hooks").exists()  # backup, never lose anything


def test_install_is_idempotent(tmp_path):
    user, local = tmp_path / "settings.json", tmp_path / "settings.local.json"
    _write(user, {})
    _write(local, {})
    mh.install(user, local, memory_dir=tmp_path / "m")
    first = user.read_text()
    mh.install(user, local, memory_dir=tmp_path / "m")
    assert user.read_text() == first


def test_stray_memories_are_found(tmp_path):
    projects = tmp_path / "projects"
    main = projects / "-Users-x" / "memory"
    main.mkdir(parents=True)
    (main / "a.md").write_text("x")
    stray = projects / "-Users-x--agents" / "memory"
    stray.mkdir(parents=True)
    (stray / "b.md").write_text("y")
    (projects / "-empty" / "memory").mkdir(parents=True)
    assert mh.stray_memories(projects, main) == [stray / "b.md"]


def test_the_gate_reads_the_same_marker_the_launcher_sets():
    assert mh.KIND_ENV == ml.KIND_ENV
