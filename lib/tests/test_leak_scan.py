"""marvin#1101: the secret and transcript scan runs the same way in CI and in MARVIN's merge gate, so no merge waits
on GitHub for it. Real gitleaks, the real guard, a scratch repo with a planted fake secret."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "secret-scan.sh"
FAKE_AWS = "AKIA" + "QYLPMN5HHHFPZAM2"   # split so this file never trips a scanner itself


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "r"
    for rel in (".github/secret-scan.sh", ".gitleaks.toml", "bin/pre-push-guard", "config/push-guard/patterns.txt",
                "config/push-guard/paths.txt"):
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, d / rel)
    git(tmp_path, "init", "-q", "-b", "main", str(d))
    git(d, "config", "user.email", "t@example.invalid")
    git(d, "config", "user.name", "t")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "base")
    return d


def scan(d, base=None, path=None):
    env = {**os.environ, "HOME": str(d.parent)}
    env.pop("MARVIN_BASE", None)
    if base:
        env["MARVIN_BASE"] = base
    if path is not None:
        env["PATH"] = path
    return subprocess.run(["bash", str(d / ".github" / "secret-scan.sh")], capture_output=True, text=True, env=env,
                          timeout=120)


@pytest.mark.requires_tool("gitleaks")
def test_a_clean_change_passes(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "notes.md").write_text("nothing secret here\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "clean")
    r = scan(repo, base)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "clean" in r.stdout


@pytest.mark.requires_tool("gitleaks")
def test_a_planted_secret_fails_it_and_is_redacted(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "config.py").write_text(f'aws_access_key_id = "{FAKE_AWS}"\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "oops")
    r = scan(repo, base)
    assert r.returncode == 1
    assert FAKE_AWS not in r.stdout + r.stderr          # --redact: a finding never prints the secret itself


@pytest.mark.requires_tool("gitleaks")
def test_a_secret_already_in_the_base_does_not_block_a_later_change(repo):
    (repo / "old.py").write_text(f'k = "{FAKE_AWS}"\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "already public")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "notes.md").write_text("later\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "later")
    assert scan(repo, base).returncode == 0


@pytest.mark.requires_tool("gitleaks")
def test_a_transcript_file_fails_it_through_the_guard(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "logs").mkdir()
    (repo / "logs" / "session.jsonl").write_text('{"role": "user"}\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "transcript")
    assert scan(repo, base).returncode == 1


@pytest.mark.requires_tool("gitleaks")
@pytest.mark.parametrize("base", [None, "0" * 40, "not-a-commit"])
def test_no_base_or_a_missing_one_still_scans_the_change(repo, base):
    (repo / "config.py").write_text(f'aws_access_key_id = "{FAKE_AWS}"\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "oops")
    assert scan(repo, base).returncode == 1


def test_without_gitleaks_it_refuses_instead_of_passing(repo):
    r = scan(repo, path="/usr/bin:/bin")
    assert r.returncode == 3 and "isn't installed" in r.stderr


def test_the_gate_and_ci_both_run_it_through_run_check():
    checks = {c["id"]: c for c in json.loads((REPO / ".github" / "required-checks.json").read_text())["checks"]}
    scan_check = checks["secret-scan"]
    assert scan_check.get("where", "both") == "both" and "gitleaks" in scan_check["requires"]
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    assert ".github/run-check.sh secret-scan" in ci
    assert "ripgrep" in ci and "gitleaks_8.30.1_linux_x64" in ci      # CI's Python job installs what tests declare
