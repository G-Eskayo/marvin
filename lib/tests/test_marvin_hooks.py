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


def _write(path, settings):
    path.write_text(json.dumps(settings, indent=2))


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


def test_session_awareness_records_everywhere_and_asks_only_people():
    """#326: every session's request and edits go on the live list (a pipeline agent on this Mac too); only an
    interactive session is asked before editing a file another live session edited."""
    sw = {(h.event, h.command[-1]): h for h in mh.HOOKS if "session_work.py" in " ".join(h.command)}
    assert sw[("UserPromptSubmit", "prompt")].kinds == {"all"}
    assert sw[("PostToolUse", "post")].kinds == {"all"} and "Edit" in sw[("PostToolUse", "post")].matcher
    assert sw[("PreToolUse", "pre")].kinds == {"interactive"} and "Write" in sw[("PreToolUse", "pre")].matcher


# ── wired_scripts: what the live hooks actually run (the map's Infrastructure section and auto_fix's never-touch
# list both read it; both were still reading settings.local.json after #291 emptied it, so both saw no hooks) ──

def _hook(command, matcher=None):
    entry = {"hooks": [{"type": "command", "command": command}]}
    return {**entry, "matcher": matcher} if matcher else entry


def _wired(tmp_path, user=None, local=None):
    paths = []
    for name, settings in (("settings.json", user), ("settings.local.json", local)):
        p = tmp_path / name
        if settings is not None:
            p.write_text(settings if isinstance(settings, str) else json.dumps(settings))
        paths.append(p)
    return {Path(r["path"]).name: r for r in mh.wired_scripts(paths)}


def test_wired_scripts_reads_user_level_hooks_through_the_gate(tmp_path):
    cmd = f"{mh.PY} {mh.GATE_SCRIPT} gate all -- {mh.PY} /a/lib/gh_merge_guard.py"
    got = _wired(tmp_path, user={"hooks": {"PreToolUse": [_hook(cmd, "Bash")]}})
    assert got["gh_merge_guard.py"] == {"path": "/a/lib/gh_merge_guard.py", "triggers": ["PreToolUse: Bash"]}
    assert "marvin_hooks.py" in got  # the gate runs on every hook, so it's wired infrastructure too


def test_wired_scripts_still_reads_home_folder_hooks(tmp_path):
    got = _wired(tmp_path, local={"hooks": {"Stop": [_hook("/usr/bin/python3 /a/old_hook.py")]}})
    assert got["old_hook.py"]["triggers"] == ["Stop"]


def test_wired_scripts_finds_every_script_in_a_shell_chain_with_quotes(tmp_path):
    chain = f"{mh.PY} {mh.GATE_SCRIPT} gate interactive -- /bin/sh -c '/p /a/code_sync.py pull /x && /p /a/code_sync.py pull /y && /p /a/report.py'"
    got = _wired(tmp_path, user={"hooks": {"SessionStart": [_hook(chain)]}})
    assert set(got) == {"marvin_hooks.py", "code_sync.py", "report.py"}  # no stray quote, code_sync once
    assert got["report.py"]["path"] == "/a/report.py"


def test_wired_scripts_merges_triggers_of_a_script_wired_several_times(tmp_path):
    user = {"hooks": {"PreToolUse": [_hook("/p /a/work.py hook pre", "Edit")],
                      "PostToolUse": [_hook("/p /a/work.py hook post", "Edit")]}}
    got = _wired(tmp_path, user=user, local={"hooks": {"PostToolUse": [_hook("/p /a/work.py hook post", "Edit")]}})
    assert got["work.py"]["triggers"] == ["PreToolUse: Edit", "PostToolUse: Edit"]


def test_wired_scripts_includes_shell_scripts_but_not_interpreters_or_arguments(tmp_path):
    got = _wired(tmp_path, user={"hooks": {"Stop": [_hook("/bin/bash /a/notify.sh pre /a/data.json")]}})
    assert set(got) == {"notify.sh"}


def test_wired_scripts_survives_missing_broken_and_odd_settings(tmp_path):
    assert _wired(tmp_path) == {}  # neither file exists
    assert _wired(tmp_path, user="{not json", local="[]") == {}
    odd = {"hooks": {"A": "nope", "B": [None, "x", {"hooks": None}, {"hooks": [{"type": "prompt", "prompt": "/a/x.py"},
                                                                             {"type": "command"}, {"type": "command", "command": "/p '/a/unclosed.py"}]}]}}
    assert set(_wired(tmp_path, user=odd)) == {"unclosed.py"}  # an unbalanced quote still yields its script
    assert _wired(tmp_path, user={"hooks": []}) == {}


def test_wired_scripts_reads_the_real_installed_hooks():
    names = {Path(r["path"]).name for r in mh.wired_scripts([mh.HOME / "nonexistent.json"] + [mh.USER_SETTINGS])}
    if not mh.USER_SETTINGS.exists():
        pytest.skip("no user settings on this machine")
    for h in mh.HOOKS:  # everything install() writes is found again by wired_scripts
        for token in " ".join(h.command).replace("'", " ").split():
            if token.endswith(".py"):
                assert Path(token).name in names, token


def test_auto_fix_never_touches_a_script_a_user_level_hook_runs(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "improve" / "scripts"))
    import auto_fix
    script = auto_fix.AGENTS_DIR / "lib" / "gh_merge_guard.py"
    user = tmp_path / "settings.json"
    user.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": f"{mh.PY} {mh.GATE_SCRIPT} gate all -- {mh.PY} {script}"}]}]}}))
    monkeypatch.setattr(auto_fix, "HOOK_SETTINGS_PATHS", (user, tmp_path / "settings.local.json"))
    monkeypatch.setattr(auto_fix, "LAUNCH_AGENTS_DIR", tmp_path / "none")
    assert auto_fix._core_files() == {script.resolve(), mh.GATE_SCRIPT.resolve()}
