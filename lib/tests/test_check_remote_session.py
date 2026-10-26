"""check_remote_session.py, the SessionStart step that pulls a handoff from the other Mac's live session.

2026-10-25: after ADR 0069 swapped literal paths for "$HOME/...", the local pull ran `subprocess.run(["$HOME/..."])`.
No shell expands that, so the script crashed whenever the other Mac had a newer session, and the && chain in the
SessionStart hook dropped the session report with it.
"""
import importlib.util
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "handoff" / "scripts" / "check_remote_session.py"


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("check_remote_session_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(mod, "remote_devices", lambda: {"laptop": {"tailscale_hostname": "laptop"}})
    monkeypatch.setattr(mod, "_check_remote", lambda d, h: {"device_id": d, "mtime": 10, "transcript_path": "/t.jsonl"})
    monkeypatch.setattr(mod, "dispatch", lambda *a, **k: type("R", (), {"ok": True})())
    return mod


def test_the_local_pull_runs_real_paths_not_shell_variables(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(mod.subprocess, "run", lambda argv, **k: calls.append(argv))
    mod.main()
    assert calls, "a newer remote session must trigger the local pull"
    for argv in calls:
        assert not any("$" in part for part in argv), f"unexpanded shell variable in {argv}"
        assert os.path.isabs(argv[0]) and argv[0].startswith(str(tmp_path))


def test_the_remote_command_still_uses_home_so_it_works_on_the_other_mac(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(mod, "dispatch", lambda cmd, **k: sent.append(cmd) or type("R", (), {"ok": True})())
    monkeypatch.setattr(mod.subprocess, "run", lambda argv, **k: None)
    mod.main()
    assert sent and "$HOME/" in sent[0] and str(tmp_path) not in sent[0]


def test_a_failing_pull_does_not_crash_the_session_start(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)

    def boom(argv, **k):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(mod.subprocess, "run", boom)
    mod.main()  # must not raise
