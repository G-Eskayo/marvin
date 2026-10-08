"""The MARVIN button's session launcher (marvin#228): a ready Interactive MARVIN session in WezTerm."""
import subprocess
from pathlib import Path

import pytest

import cleanup_sweep
import marvin_launcher as ml
import marvin_session as ms

AGENTS = Path(__file__).resolve().parents[2]


def test_slug_is_short_lowercase_and_shell_safe():
    assert ms.slug("Header button: open a MARVIN session in WezTerm!") == "header-button-open-a-marvin-session-in"
    assert ms.branch_for(228, "Header button") == "ticket/228-header-button"


def test_the_cleanup_sweep_reads_the_ticket_from_a_session_branch():
    assert cleanup_sweep._extract_issue_number("ticket/228-header-button") == 228
    assert cleanup_sweep._extract_issue_number("pipeline/g-eskayo/marvin#188") == 188


def _repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    git = lambda *a: subprocess.run(["git", "-C", str(clone), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True, text=True)
    (clone / "f").write_text("x")
    git("add", "f"); git("commit", "-qm", "init"); git("push", "-q", "origin", "main")
    return clone


def test_a_ticket_gets_its_own_worktree_on_its_ticket_branch_and_reuses_it(tmp_path, monkeypatch):
    clone = _repo(tmp_path)
    monkeypatch.setattr(ms, "WORKTREES_ROOT", tmp_path / "wt")
    first = ms.session_dir(clone, 228, "Header button")
    assert first == tmp_path / "wt" / "ticket-228-header-button"
    head = subprocess.run(["git", "-C", str(first), "branch", "--show-current"], capture_output=True, text=True)
    assert head.stdout.strip() == "ticket/228-header-button"
    (first / "work.txt").write_text("in progress")
    assert ms.session_dir(clone, 228, "Header button") == first
    assert (first / "work.txt").read_text() == "in progress"  # reused, never recreated


def test_no_ticket_starts_at_home_never_in_the_shared_checkout():
    assert ms.session_dir(AGENTS, None, None) == Path.home()


def test_the_shell_script_sets_its_own_environment_and_keeps_the_token_off_the_command_line(tmp_path):
    script = ms.shell_script(tmp_path)
    assert f"cd {tmp_path}" in script
    assert "export PATH=" in script and "/.agents/venv/bin" in script and "/.local/bin" in script
    assert f"export {ml.KIND_ENV}=interactive" in script
    assert 'GH_TOKEN="$(cat' in script  # read inside the shell, so `ps` never shows it
    assert script.rstrip().endswith("exec claude")


def test_spawns_into_the_running_wezterm_and_falls_back_to_starting_it(tmp_path):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[1:3] == ["cli", "spawn"] else 0, "", "no mux")

    started = []
    ms.open_in_wezterm(tmp_path, wezterm="/x/wezterm", run=run, start=lambda cmd: started.append(cmd))
    assert calls[0][:4] == ["/x/wezterm", "cli", "spawn", "--new-window"]
    assert started and started[0][:2] == ["/x/wezterm", "start"]


def test_a_missing_wezterm_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(ms, "WEZTERM_CANDIDATES", (Path("/nonexistent/wezterm"),))
    monkeypatch.setattr(ms.shutil, "which", lambda name: None)
    with pytest.raises(ms.SessionError, match="WezTerm"):
        ms.find_wezterm()


def test_the_phone_can_never_open_a_desktop_session():
    for path in (AGENTS / "dashboard/mobile-backend").rglob("*.js"):
        if "node_modules" in path.parts:
            continue
        src = path.read_text(errors="ignore")
        assert "marvin_session" not in src and "openSession" not in src, path
