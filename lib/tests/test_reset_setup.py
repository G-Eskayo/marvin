"""Tests for the owner's one-line setup scripts (marvin#847): bin/marvin-reset-setup (the planned restart) and
bin/marvin-peer-unlock-setup (the remote FileVault unlock on a watcher).
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_reset_setup.py -v

They only ever run here as this (non-root) user: in --dry-run, which must install nothing and touch no keychain, or
without --dry-run, which must refuse before doing anything. The owner runs them for real, once, with sudo.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

BIN = Path(__file__).resolve().parents[2] / "bin"
RESET_SETUP = BIN / "marvin-reset-setup"
UNLOCK_SETUP = BIN / "marvin-peer-unlock-setup"
TOOLS = ("install", "visudo", "security", "chown", "chmod", "mkdir", "cp", "tee", "fdesetup", "shutdown", "reboot")


def _fakes(tmp_path):
    """Fake every tool that could change the machine; any call is recorded."""
    calls = tmp_path / "calls"
    for n in TOOLS:
        (tmp_path / n).write_text(f'#!/bin/sh\necho "{n} $*" >> "{calls}"\n')
        (tmp_path / n).chmod(0o755)
    return calls, {"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path), "SUDO_USER": "owner"}


def _sudoers_block(out: str) -> str:
    lines = out.split("--- sudoers ---\n", 1)[1].split("--- end ---", 1)[0]
    return lines


def test_reset_setup_dry_run_changes_nothing_and_says_every_step(tmp_path):
    calls, env = _fakes(tmp_path)
    r = subprocess.run([str(RESET_SETUP), "--dry-run"], capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    out = r.stdout.lower()
    assert "dry run" in out
    for step in ("/usr/local/libexec/marvin-authrestart", "/etc/sudoers.d/marvin-authrestart", "system keychain"):
        assert step in out, step
    assert not calls.exists()


def test_reset_setup_sudoers_rule_allows_only_the_script_and_parses(tmp_path):
    _, env = _fakes(tmp_path)
    r = subprocess.run([str(RESET_SETUP), "--dry-run"], capture_output=True, text=True, timeout=30, env=env)
    rule = _sudoers_block(r.stdout)
    assert rule.strip() == ("owner ALL=(root) NOPASSWD: /usr/local/libexec/marvin-authrestart \"\", "
                            "/usr/local/libexec/marvin-authrestart --dry-run")
    f = tmp_path / "rule"
    f.write_text(rule)
    v = subprocess.run(["/usr/sbin/visudo", "-cf", str(f)], capture_output=True, text=True, timeout=30)
    assert v.returncode == 0, v.stdout + v.stderr


def test_reset_setup_never_takes_the_password_on_the_command_line(tmp_path):
    """The keychain step lets `security` prompt the owner itself (-w last): the password never passes through
    this script's argv, a variable or a file."""
    text = RESET_SETUP.read_text()
    assert "add-generic-password" in text
    line = next(ln for ln in text.splitlines() if "add-generic-password" in ln and not ln.lstrip().startswith("#"))
    assert line.rstrip().endswith(" -w")                       # security prompts only when -w is the last argument
    assert "read -s" not in text and "read -rs" not in text
    # ...and then takes no keychain argument, so the script checks the item really is in the System keychain
    assert 'find-generic-password -s "$SERVICE" -a "$user" "$KEYCHAIN"' in text.split("add-generic-password", 1)[1]


def test_reset_setup_without_dry_run_refuses_unless_root(tmp_path):
    calls, env = _fakes(tmp_path)
    r = subprocess.run([str(RESET_SETUP)], capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 77
    assert "sudo" in r.stderr
    assert not calls.exists()


def test_reset_setup_rejects_unknown_arguments():
    r = subprocess.run([str(RESET_SETUP), "--user", "x"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 64


def test_unlock_setup_dry_run_changes_nothing(tmp_path):
    calls, env = _fakes(tmp_path)
    r = subprocess.run([str(UNLOCK_SETUP), "mac-mini-1", "owner@192.0.2.41", "--dry-run"], capture_output=True,
                       text=True, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "dry run" in out.lower()
    assert "/usr/local/libexec/marvin-peer-unlock" in out and "TARGET=owner@192.0.2.41" in out
    assert not calls.exists()


def test_unlock_setup_sudoers_rule_parses(tmp_path):
    _, env = _fakes(tmp_path)
    r = subprocess.run([str(UNLOCK_SETUP), "mac-mini-1", "owner@192.0.2.41", "--dry-run"], capture_output=True,
                       text=True, timeout=30, env=env)
    rule = _sudoers_block(r.stdout)
    assert rule.strip() == "owner ALL=(root) NOPASSWD: /usr/local/libexec/marvin-peer-unlock"
    f = tmp_path / "rule"
    f.write_text(rule)
    v = subprocess.run(["/usr/sbin/visudo", "-cf", str(f)], capture_output=True, text=True, timeout=30)
    assert v.returncode == 0, v.stdout + v.stderr


def test_unlock_setup_rejects_targets_and_peers_that_could_steer_ssh(tmp_path):
    _, env = _fakes(tmp_path)
    for peer, target in (("../x", "owner@192.0.2.41"), ("mac-mini-1", "-oProxyCommand=x"),
                         ("mac-mini-1", "owner@host;reboot"), ("mac-mini-1", "nouser"), ("", "")):
        r = subprocess.run([str(UNLOCK_SETUP), peer, target, "--dry-run"], capture_output=True, text=True,
                           timeout=30, env=env)
        assert r.returncode == 64, (peer, target)


def test_unlock_setup_without_dry_run_refuses_unless_root(tmp_path):
    calls, env = _fakes(tmp_path)
    r = subprocess.run([str(UNLOCK_SETUP), "mac-mini-1", "owner@192.0.2.41"], capture_output=True, text=True,
                       timeout=30, env=env)
    assert r.returncode == 77 and not calls.exists()
