"""ADR 0071: the pre-push guard, its install by setup.sh, and code_sync's own call to it. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_push_guard.py -v

2026-10-25: auto-sync pushed a session transcript to the public repo, and a phone number had been public since July.
Real temp repos, a temp HOME (never the real one), the real bin/pre-push-guard and the real setup.sh function.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "bin" / "pre-push-guard"
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

PHONE = "(555) 010-4477"  # stand-in for a real person's number; only the private file names it


def _run(cwd: Path, *args: str, env: dict | None = None, inp: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=env, input=inp)


def _git(cwd: Path, *args: str, env: dict | None = None) -> str:
    r = _run(cwd, "git", *args, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    (h / ".claude" / "private-push-patterns.txt").write_text("# test owner\n555[^0-9]{0,2}010[^0-9]{0,2}4477\n")
    return h


@pytest.fixture
def env(home):
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(HOME=str(home), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return e


@pytest.fixture
def repo(tmp_path, env):
    """A clone with the guard installed as its pre-push hook, the way setup.sh installs it (a symlink)."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote), env=env)
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(remote), str(clone), env=env)
    _git(clone, "checkout", "-q", "-b", "main", env=env)
    (clone / "bin").mkdir()
    (clone / "bin" / "pre-push-guard").symlink_to(GUARD)
    (clone / "config" / "push-guard").mkdir(parents=True)
    (clone / "config" / "push-guard" / "patterns.txt").write_text((ROOT / "config" / "push-guard" / "patterns.txt").read_text())
    (clone / "README.md").write_text("engine\n")
    _git(clone, "add", "-A", env=env)
    _git(clone, "commit", "-qm", "init", env=env)
    (clone / ".git" / "hooks" / "pre-push").symlink_to(GUARD)
    _git(clone, "push", "-q", "origin", "main", env=env)
    return clone


def _commit(repo: Path, env: dict, path: str, text: str, msg: str = "c") -> None:
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", msg, env=env)


def _push(repo: Path, env: dict, *ref: str) -> subprocess.CompletedProcess:
    return _run(repo, "git", "push", "origin", *(ref or ("main",)), env=env)


def _remote_has(repo: Path, env: dict, branch: str = "main") -> str:
    return _run(repo, "git", "ls-remote", "origin", f"refs/heads/{branch}", env=env).stdout.split("\t")[0]


# ── the guard ────────────────────────────────────────────────────────────────

def test_clean_push_goes_through(repo, env):
    _commit(repo, env, "skills/x/SKILL.md", "a skill\n")
    assert _push(repo, env).returncode == 0
    assert _remote_has(repo, env) == _git(repo, "rev-parse", "HEAD")


def test_a_private_pattern_blocks_the_push_and_origin_is_unchanged(repo, env):
    before = _remote_has(repo, env)
    _commit(repo, env, "skills/resume/SKILL.md", f"call {PHONE}\n")
    r = _push(repo, env)
    assert r.returncode != 0 and "BLOCKED" in r.stderr
    assert _remote_has(repo, env) == before
    assert PHONE not in r.stderr, "the guard must not echo the very string it protects"


def test_a_line_added_then_deleted_in_the_same_push_is_still_blocked(repo, env):
    """The middle commit is published with the push even though the tip no longer has the line."""
    _commit(repo, env, "notes.md", f"{PHONE}\n")
    _commit(repo, env, "notes.md", "clean now\n")
    assert _push(repo, env).returncode != 0


def test_a_transcript_file_under_logs_is_blocked_whatever_its_content(repo, env):
    _commit(repo, env, "logs/session.jsonl", "{}\n")
    r = _push(repo, env)
    assert r.returncode != 0 and "logs/session.jsonl" in r.stderr


def test_transcript_text_is_blocked_anywhere_in_the_tree(repo, env):
    # split so this file doesn't itself carry transcript text past the guard
    _commit(repo, env, "bench/run.json", '{"type":"user","message":{"role":"user",' + '"content":"hi"}}\n')
    assert _push(repo, env).returncode != 0


@pytest.mark.parametrize("secret", [
    "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "sk-ant-api03-" + "x" * 40,
    "-----BEGIN OPENSSH " + "PRIVATE KEY-----",  # split, or this file trips the guard it tests
])
def test_real_shaped_secrets_are_blocked_by_the_shared_patterns(repo, env, secret):
    _commit(repo, env, "lib/cfg.py", f"KEY = '{secret}'\n")
    assert _push(repo, env).returncode != 0


def test_renaming_a_public_file_into_logs_as_jsonl_is_blocked(repo, env):
    """With rename detection a move is status R, which an Added/Modified path filter never sees."""
    _commit(repo, env, "bench/run-output.txt", "line one\nline two\nline three\n")
    assert _push(repo, env).returncode == 0
    (repo / "logs").mkdir()
    _git(repo, "mv", "bench/run-output.txt", "logs/session.jsonl", env=env)
    _git(repo, "commit", "-qm", "move", env=env)
    r = _push(repo, env)
    assert r.returncode != 0 and "logs/session.jsonl" in r.stderr


def test_content_slipped_in_by_a_merge_resolution_is_blocked(repo, env):
    """An evil merge adds lines that are in neither parent; plain `git log -p` shows no diff for merges."""
    _git(repo, "checkout", "-q", "-b", "side", env=env)
    _commit(repo, env, "side.md", "side\n")
    _git(repo, "checkout", "-q", "main", env=env)
    _commit(repo, env, "main.md", "main\n")
    _git(repo, "merge", "-q", "--no-commit", "side", env=env)
    (repo / "main.md").write_text(f"main\n{PHONE}\n")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", "merge", env=env)
    assert _push(repo, env).returncode != 0


def test_history_already_on_the_remote_is_not_rescanned(repo, env):
    """A public test fixture that matches a pattern must not block every later push forever."""
    _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "--allow-empty", "-m", "x", env=env)
    (repo / "fixture.py").write_text(f"SAMPLE = '{PHONE}'\n")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", "fixture", env=env)
    assert _run(repo, "git", "push", "--no-verify", "origin", "main", env=env).returncode == 0
    _commit(repo, env, "next.md", "unrelated\n")
    assert _push(repo, env).returncode == 0


def test_a_new_branch_is_judged_only_by_its_own_new_commits(repo, env):
    _git(repo, "checkout", "-q", "-b", "ticket/1", env=env)
    _commit(repo, env, "t.md", "ok\n")
    assert _push(repo, env, "ticket/1").returncode == 0
    _git(repo, "checkout", "-q", "-b", "ticket/2", env=env)
    _commit(repo, env, "t2.md", f"{PHONE}\n")
    assert _push(repo, env, "ticket/2").returncode != 0


def test_a_new_branch_cut_from_a_main_with_a_public_fixture_can_be_pushed(repo, env):
    """Every ticket branch starts from main; main's already-public history must not count against it."""
    (repo / "fixture.py").write_text(f"SAMPLE = '{PHONE}'\n")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", "fixture", env=env)
    assert _run(repo, "git", "push", "--no-verify", "origin", "main", env=env).returncode == 0
    _git(repo, "checkout", "-q", "-b", "ticket/3", env=env)
    _commit(repo, env, "t3.md", "ticket work\n")
    assert _push(repo, env, "ticket/3").returncode == 0


def test_removing_a_matching_line_is_allowed(repo, env):
    _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "--allow-empty", "-m", "x", env=env)
    (repo / "old.md").write_text(f"{PHONE}\n")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", "old leak", env=env)
    _run(repo, "git", "push", "--no-verify", "origin", "main", env=env)
    _commit(repo, env, "old.md", "scrubbed\n")
    assert _push(repo, env).returncode == 0


def test_deleting_a_branch_is_allowed(repo, env):
    _git(repo, "checkout", "-q", "-b", "gone", env=env)
    _commit(repo, env, "g.md", "g\n")
    _push(repo, env, "gone")
    assert _push(repo, env, "--delete", "gone").returncode == 0


def test_a_missing_private_patterns_file_refuses_rather_than_pushing_blind(repo, env, home):
    (home / ".claude" / "private-push-patterns.txt").unlink()
    _commit(repo, env, "fine.md", "fine\n")
    r = _push(repo, env)
    assert r.returncode != 0 and "private-push-patterns.txt" in r.stderr


def test_an_empty_private_file_still_applies_the_shared_patterns(repo, env, home):
    """A brand-new user has no personal patterns yet; secrets and transcripts must still be caught."""
    (home / ".claude" / "private-push-patterns.txt").write_text("# nothing yet\n\n")
    _commit(repo, env, "fine.md", "fine\n")
    assert _push(repo, env).returncode == 0
    _commit(repo, env, "logs/x.jsonl", "{}\n")
    assert _push(repo, env).returncode != 0


# ── setup.sh installs it ─────────────────────────────────────────────────────

def _install(home: Path, env: dict, clone: Path) -> subprocess.CompletedProcess:
    script = f'source "{ROOT}/setup.sh"; MARVIN_DIR="{clone}"; install_push_guard'
    return _run(clone, "bash", "-c", script, env=env)


@pytest.fixture
def fresh(tmp_path, env):
    """A clone with no hook yet, as a new user has right after `git clone`."""
    clone = tmp_path / "fresh"
    _git(tmp_path, "init", "-q", "-b", "main", str(clone), env=env)
    (clone / "bin").mkdir()
    (clone / "bin" / "pre-push-guard").write_text(GUARD.read_text())
    (clone / "bin" / "pre-push-guard").chmod(0o755)
    return clone


def test_sourcing_setup_sh_runs_nothing(tmp_path, env):
    r = _run(tmp_path, "bash", "-c", f'source "{ROOT}/setup.sh"; echo sourced', env=env)
    assert r.returncode == 0 and r.stdout.strip().endswith("sourced")
    assert "Homebrew" not in r.stdout and "Platform" not in r.stdout


def test_setup_creates_a_private_patterns_file_only_the_owner_can_read(home, env, fresh):
    (home / ".claude" / "private-push-patterns.txt").unlink()
    assert _install(home, env, fresh).returncode == 0
    f = home / ".claude" / "private-push-patterns.txt"
    assert f.exists() and stat.S_IMODE(f.stat().st_mode) == 0o600


def test_setup_never_overwrites_existing_private_patterns(home, env, fresh):
    f = home / ".claude" / "private-push-patterns.txt"
    before = f.read_text()
    _install(home, env, fresh)
    assert f.read_text() == before


def test_setup_links_the_hook_so_guard_updates_reach_it(home, env, fresh):
    _install(home, env, fresh)
    hook = fresh / ".git" / "hooks" / "pre-push"
    assert hook.is_symlink() and hook.resolve() == (fresh / "bin" / "pre-push-guard").resolve()


def test_setup_twice_is_a_no_op(home, env, fresh):
    _install(home, env, fresh)
    r = _install(home, env, fresh)
    assert r.returncode == 0
    assert (fresh / ".git" / "hooks" / "pre-push").is_symlink()


def test_setup_leaves_someone_elses_pre_push_hook_alone_and_says_so(home, env, fresh):
    hook = fresh / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho mine\n")
    r = _install(home, env, fresh)
    assert hook.read_text() == "#!/bin/sh\necho mine\n"
    assert "pre-push" in r.stdout + r.stderr


def test_setup_installs_into_the_shared_hooks_dir_when_run_from_a_worktree(home, env, fresh, tmp_path):
    _git(fresh, "commit", "-q", "--allow-empty", "-m", "i", env=env)
    wt = tmp_path / "wt"
    _git(fresh, "worktree", "add", "-q", "-b", "w", str(wt), env=env)
    (wt / "bin").mkdir(exist_ok=True)
    (wt / "bin" / "pre-push-guard").write_text(GUARD.read_text())
    assert _install(home, env, wt).returncode == 0
    assert (fresh / ".git" / "hooks" / "pre-push").is_symlink()


# ── code_sync calls it too ───────────────────────────────────────────────────

def test_code_sync_refuses_to_push_what_the_guard_blocks_even_without_the_hook(repo, env, home, tmp_path, monkeypatch):
    import code_sync as cs
    from test_code_sync_push import _quiet
    log = tmp_path / "sync-log.md"
    _quiet(monkeypatch, log)
    for k, v in env.items():
        monkeypatch.setenv(k, v)  # temp HOME + a git identity, so the auto-commit can happen
    (repo / ".git" / "hooks" / "pre-push").unlink()  # hook missing: code_sync's own check is the backstop
    before = _remote_has(repo, env)
    (repo / "logs").mkdir()
    (repo / "logs" / "s.jsonl").write_text("{}\n")
    (repo / "note.md").write_text(f"{PHONE}\n")

    cs.push(repo)

    assert _remote_has(repo, env) == before
    assert "REFUSING to push" in log.read_text()


def test_code_sync_still_pushes_clean_work_through_the_guard(repo, env, home, tmp_path, monkeypatch):
    import code_sync as cs
    from test_code_sync_push import _quiet
    _quiet(monkeypatch, tmp_path / "sync-log.md")
    for k, v in env.items():
        monkeypatch.setenv(k, v)  # temp HOME + a git identity, so the auto-commit can happen
    (repo / "skills").mkdir()
    (repo / "skills" / "new.md").write_text("a new skill\n")

    cs.push(repo)

    assert _remote_has(repo, env) == _git(repo, "rev-parse", "HEAD")
