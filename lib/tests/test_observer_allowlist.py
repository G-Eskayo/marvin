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


# --- marvin#954: the box's GitHub view comes from the Mini's feed file, by name, and nothing near it ---

def test_the_github_feed_is_readable_by_its_exact_name(home):
    (home / ".claude" / "logs" / "github-feed.json").write_text('{"version": 1, "repos": {}}')
    r = run("cat ~/.claude/logs/github-feed.json", home)
    assert r.returncode == 0 and '"repos"' in r.stdout


@pytest.mark.parametrize("command", [
    "cat ~/.claude/logs/github-feed.json ~/.claude/.gh-token",
    "cat ~/.claude/logs/github-feed.json; cat ~/.claude/.gh-token",
    "cat ~/.claude/logs/../.gh-token",
    "cat ~/.claude/.gh-token",
    "cat ~/.claude/.oauth-token",
    "cat ~/.claude/.anthropic-api-key",
    "cat ~/.claude/logs/github-feed.json.tmp",
    "cat ~/.claude/logs/*.json",
])
def test_nothing_beside_the_feed_is_readable(home, command):
    (home / ".claude" / ".gh-token").write_text("SECRET-CANARY")
    r = run(command, home)
    assert r.returncode != 0 and "refused" in r.stderr and "SECRET-CANARY" not in r.stdout


def test_the_box_copy_script_asks_only_for_listed_reads(home):
    """marvin-observer-feed.sh's requests, as sent, are on the list (else the box silently loses a view)."""
    import re
    feed = (SCRIPT.parent / "marvin-observer-feed.sh").read_text()
    names = re.findall(r"^copy ([\w.-]+\.json)", feed, re.M)
    assert set(names) == {"health-status.json", "github-feed.json"}
    for n in names:
        (home / ".claude" / "logs" / n).write_text("{}")
        assert "refused" not in run(f"cat ~/.claude/logs/{n}", home).stderr


def test_the_box_copy_keeps_the_last_good_file_when_the_mini_sends_junk(tmp_path):
    """Run the real copy script against a fake ssh: junk or a failed ssh never replaces a good copy."""
    logs = tmp_path / ".claude" / "logs"
    logs.mkdir(parents=True)
    (logs / "github-feed.json").write_text('{"good": true}')
    (logs / "health-status.json").write_text('{"good": true}')
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "ssh").write_text('#!/bin/sh\ncase "$*" in *github-feed*) echo \'{"repos": [trunc\' ;; *) echo \'{"new": 1}\' ;; esac\n')
    (fake / "ssh").chmod(0o755)
    venv = tmp_path / ".agents" / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(os.path.realpath(__import__("sys").executable))
    env = {"HOME": str(tmp_path), "PATH": f"{fake}:/usr/bin:/bin", "MARVIN_OBSERVER_HOST": "primary-mac"}
    r = subprocess.run(["/bin/bash", str(SCRIPT.parent / "marvin-observer-feed.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "could not copy github-feed.json" in r.stderr
    assert (logs / "github-feed.json").read_text() == '{"good": true}'
    assert (logs / "health-status.json").read_text().strip() == '{"new": 1}'
    assert oct((logs / "health-status.json").stat().st_mode & 0o777) == "0o600"
    assert sorted(p.name for p in logs.iterdir()) == ["github-feed.json", "health-status.json"]


def test_the_box_copy_with_no_primary_in_the_registry_copies_nothing_and_says_so(tmp_path):
    """No machine is named in the script (identity rule): with no registry to ask, it stops loudly, never guesses."""
    logs = tmp_path / ".claude" / "logs"
    logs.mkdir(parents=True)
    (logs / "health-status.json").write_text('{"good": true}')
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "ssh").write_text('#!/bin/sh\necho called >> "$HOME/ssh-calls"\necho \'{"new": 1}\'\n')
    (fake / "ssh").chmod(0o755)
    venv = tmp_path / ".agents" / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(os.path.realpath(__import__("sys").executable))
    env = {"HOME": str(tmp_path), "PATH": f"{fake}:/usr/bin:/bin"}
    r = subprocess.run(["/bin/bash", str(SCRIPT.parent / "marvin-observer-feed.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "no primary Mac in the machine registry" in r.stderr
    assert not (tmp_path / "ssh-calls").exists()
    assert (logs / "health-status.json").read_text() == '{"good": true}'


def test_the_box_copy_finds_the_primary_through_the_registry_lookup_it_runs(tmp_path):
    """The exact lookup the script runs answers with the primary's Tailscale hostname from the synced registry."""
    import json, re, sys
    import scanner_role
    (tmp_path / ".claude").mkdir()
    primary = scanner_role.PRIMARY_PREFIX + "1"
    (tmp_path / ".claude" / "marvin-network.json").write_text(json.dumps({"devices": {
        primary: {"tailscale_hostname": "the-primary", "hardware_uuid": "P", "accepts": ["general"]},
        "linux-box": {"tailscale_hostname": "the-box", "hardware_uuid": "B", "os": "linux", "accepts": ["test"]}}}))
    feed = (SCRIPT.parent / "marvin-observer-feed.sh").read_text()
    code = re.search(r"-c '([^']*scanner_role[^']*)'", feed).group(1)
    r = subprocess.run([sys.executable, "-c", code], cwd=SCRIPT.parents[2], capture_output=True, text=True, timeout=30,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert r.stdout.strip() == "the-primary", r.stderr
