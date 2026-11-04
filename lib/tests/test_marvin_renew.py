"""bin/marvin-renew (marvin#974): renewing a credential from Vitals. The person approves or pastes; the token must never
reach argv, the screen, a log, or a world-readable file. Runs the real script against fake gh/claude."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "marvin-renew"
TOKEN = "gho_CANARYrenewTOKEN0123456789"


def fake_bin(tmp_path, name, body):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    f = d / name
    # every fake records its own argv, so a token passed on a command line would show up there
    f.write_text(f'#!/bin/bash\necho "$0 $*" >> "{tmp_path}/argv.log"\n{body}\n')
    f.chmod(0o755)
    return d


def renew(tmp_path, account, stdin="", bins=()):
    d = None
    for name, body in bins:
        d = fake_bin(tmp_path, name, body)
    path = f"{d}:/usr/bin:/bin" if d else "/usr/bin:/bin"
    env = {"HOME": str(tmp_path), "MARVIN_RENEW_HOME": str(tmp_path), "PATH": path}
    return subprocess.run(["/bin/bash", str(SCRIPT), account], input=stdin, capture_output=True, text=True, env=env, timeout=30)


def saved(tmp_path, name):
    p = tmp_path / ".claude" / name
    return p.read_text(), stat.S_IMODE(p.stat().st_mode)


def argv_log(tmp_path):
    p = tmp_path / "argv.log"
    return p.read_text() if p.exists() else ""


def test_github_saves_what_gh_got_privately_and_never_shows_it(tmp_path):
    r = renew(tmp_path, "github", bins=[("gh", f'[ "$2" = token ] && printf "{TOKEN}\\n"; exit 0')])
    assert r.returncode == 0, r.stderr
    text, mode = saved(tmp_path, ".gh-token")
    assert text == TOKEN and mode == 0o600
    assert TOKEN not in r.stdout + r.stderr + argv_log(tmp_path)
    assert "auth login --hostname github.com --git-protocol https --web" in argv_log(tmp_path)


def test_github_login_cancelled_saves_nothing_and_keeps_the_old_token(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".gh-token").write_text("old")
    r = renew(tmp_path, "github", bins=[("gh", "exit 1")])
    assert r.returncode == 1 and "nothing was saved" in r.stderr
    assert saved(tmp_path, ".gh-token")[0] == "old"


def test_github_login_runs_without_the_shared_token_in_its_environment(tmp_path):
    body = f'env | grep -q "^GH_TOKEN=" && echo LEAKED >> "{tmp_path}/argv.log"; [ "$2" = token ] && echo {TOKEN}; exit 0'
    env_token = {"GH_TOKEN": "ghp_should_not_pass"}
    d = fake_bin(tmp_path, "gh", body)
    r = subprocess.run(["/bin/bash", str(SCRIPT), "github"], capture_output=True, text=True, timeout=30,
                       env={"HOME": str(tmp_path), "MARVIN_RENEW_HOME": str(tmp_path), "PATH": f"{d}:/usr/bin:/bin", **env_token})
    assert r.returncode == 0 and "LEAKED" not in argv_log(tmp_path)


@pytest.mark.parametrize("account,file", [("anthropic-api-key", ".anthropic-api-key"), ("marvin-bot-token", ".marvin-bot-token")])
def test_a_pasted_token_is_saved_600_and_never_echoed(tmp_path, account, file):
    r = renew(tmp_path, account, stdin=TOKEN + "\n")
    assert r.returncode == 0, r.stderr
    assert saved(tmp_path, file) == (TOKEN, 0o600)
    assert TOKEN not in r.stdout + r.stderr


def test_claude_setup_token_runs_claude_then_takes_the_paste(tmp_path):
    r = renew(tmp_path, "claude-setup-token", stdin=TOKEN + "\n", bins=[("claude", 'echo "Your token: (shown to the person only)"; exit 0')])
    assert r.returncode == 0, r.stderr
    assert saved(tmp_path, ".oauth-token") == (TOKEN, 0o600)
    assert "claude setup-token" in argv_log(tmp_path) and TOKEN not in argv_log(tmp_path)


@pytest.mark.parametrize("paste", ["", "\n", "two words\n", "  \n"])
def test_an_empty_or_garbled_paste_saves_nothing(tmp_path, paste):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".anthropic-api-key").write_text("old-key")
    r = renew(tmp_path, "anthropic-api-key", stdin=paste)
    assert r.returncode == 1 and "nothing was saved" in r.stderr
    assert saved(tmp_path, ".anthropic-api-key")[0] == "old-key"
    assert [p.name for p in (tmp_path / ".claude").iterdir()] == [".anthropic-api-key"]


def test_an_existing_world_readable_file_ends_up_600(tmp_path):
    (tmp_path / ".claude").mkdir()
    old = tmp_path / ".claude" / ".marvin-bot-token"
    old.write_text("old")
    os.chmod(old, 0o644)
    renew(tmp_path, "marvin-bot-token", stdin=TOKEN + "\n")
    assert saved(tmp_path, ".marvin-bot-token") == (TOKEN, 0o600)


@pytest.mark.parametrize("account", ["evil; touch PWNED", "../x", "tailscale", "GITHUB"])
def test_unknown_accounts_are_refused(tmp_path, account):
    r = renew(tmp_path, account)
    assert r.returncode != 0 and not (tmp_path / "PWNED").exists()
