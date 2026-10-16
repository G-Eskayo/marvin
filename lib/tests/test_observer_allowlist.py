"""The observer key (ADR 0069): mac-mini-2012's dashboard may read a fixed list of things from the Macs and nothing
else. The Mac's sshd runs config/mac-mini-2012/marvin-observer.sh as a forced command; these run the real script in a
real shell with a temp HOME and try to get anything past it."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "config" / "mac-mini-2012" / "marvin-observer.sh"


def run(command, home):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "SSH_ORIGINAL_COMMAND": command}
    return subprocess.run(["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, cwd=home, timeout=20)


@pytest.fixture
def home(tmp_path):
    logs = tmp_path / ".claude" / "logs"
    logs.mkdir(parents=True)
    (logs / "tool-usage.json").write_text('{"tools": 1}')
    (logs / "health-status.json").write_text('{"overall": "green"}')
    (tmp_path / ".claude" / "dispatch-state.json").write_text('{"busy": false}')
    return tmp_path


@pytest.mark.parametrize("command,expect", [
    ("echo ok", "ok"),
    ("cat ~/.claude/logs/tool-usage.json", '{"tools": 1}'),
    ("cat ~/.claude/logs/health-status.json", '{"overall": "green"}'),
    ('cat "$HOME/.claude/dispatch-state.json"', '{"busy": false}'),
])
def test_the_listed_reads_work(home, command, expect):
    r = run(command, home)
    assert r.returncode == 0 and expect in r.stdout


@pytest.mark.parametrize("command", [
    "bash -s",                                                     # would run whatever arrives on stdin
    "sh",
    "",
    "echo ok; touch PWNED",
    "echo ok && touch PWNED",
    "echo ok | touch PWNED",
    "echo ok\ntouch PWNED",
    "echo ok `touch PWNED`",
    "echo ok $(touch PWNED)",
    "cat ~/.claude/logs/tool-usage.json > ~/PWNED",
    "cat ~/.claude/logs/../../.ssh/id_ed25519",
    "cat ~/.ssh/id_ed25519",
    "cat ~/.claude/.marvin-bot-token",
    "cat ~/.claude/logs/tool-usage.json ~/.ssh/id_ed25519",
    "git -C .agents push origin main",
    "git -C .agents rev-parse HEAD; touch PWNED",
    'cd "$HOME/.agents" && "$HOME/.agents/venv/bin/python" -m lib.dispatch_concurrency slots-in-use --machine x; touch PWNED',
    'cd "$HOME/.agents" && "$HOME/.agents/venv/bin/python" -m lib.dispatch_concurrency slots-in-use --machine $(touch PWNED)',
    "~/.agents/venv/bin/python ~/.agents/lib/purpose_metrics.py measure ../x --local",
    "ECHO OK",
    " echo ok",
    "echo ok ",
])
def test_everything_else_is_refused_and_nothing_runs(home, command):
    r = run(command, home)
    assert r.returncode != 0 and "refused" in r.stderr
    assert not (home / "PWNED").exists()


def test_the_script_never_trusts_ssh_original_command_being_unset(home):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    r = subprocess.run(["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, cwd=home)
    assert r.returncode != 0


# --- contract: what each real caller sends is on the list (else the box's dashboard silently loses that panel) ---

def _captured(monkeypatch, module, call):
    """Run `call` with subprocess.run captured; return the remote command string it sent over ssh."""
    sent = []

    def fake(cmd, *a, **k):
        if cmd and cmd[0] == "ssh":
            sent.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 1, "", "stop")
    monkeypatch.setattr(module.subprocess, "run", fake)
    try:
        call()
    except Exception:
        pass
    assert sent, f"{module.__name__} sent nothing over ssh"
    return sent[0]


def _callers(monkeypatch):
    import device_status, running_tickets, task_dispatch, health_checks, dispatch_concurrency, scanner_role
    out = [
        _captured(monkeypatch, device_status, lambda: device_status.probe_remote("h")),
        _captured(monkeypatch, running_tickets, lambda: running_tickets._remote_ps("h")),
        _captured(monkeypatch, task_dispatch, lambda: task_dispatch._read_remote_dispatch_state("h")),
        _captured(monkeypatch, health_checks, lambda: health_checks._run_errors_remote("h")),
    ]
    sent = []
    dispatch_concurrency.slots_in_use_remote("h", "mac-mini-1", run=lambda cmd, **k: sent.append(cmd[-1]) or
                                             subprocess.CompletedProcess(cmd, 1, "", ""))
    out += sent
    out.append(scanner_role.REMOTE_HEARTBEAT_COMMAND)
    out += [f"git -C {rel} rev-parse HEAD" for rel in (".agents", ".claude")]   # cron_health's convergence check
    return out


def test_every_dashboard_caller_sends_a_command_the_observer_key_allows(monkeypatch, home):
    for command in _callers(monkeypatch):
        r = run(command, home)
        assert "refused" not in r.stderr, f"observer key refuses {command!r}"
