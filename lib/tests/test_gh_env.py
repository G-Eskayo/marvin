"""Tests for gh_env.py (marvin#866): the environment every non-interactive gh call uses. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_gh_env.py -v

A fake `gh` on PATH stands in for GitHub: it answers only when GH_TOKEN is the good token, and fails the way the real gh
does in an ssh or launchd shell (keychain locked) otherwise. No real token file, HOME or GitHub is touched.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import gh_env  # noqa: E402

GOOD = "test-good-token-not-a-real-one"
EXPIRED = "test-expired-token-not-a-real-one"


def fake_gh(tmp_path: Path, monkeypatch, stdout: str = "[]") -> Path:
    """A gh that answers only with GOOD; with any other token, 'Bad credentials'; with none, 'Requires authentication'.
    It also echoes the token it was given to stderr on failure, so a test can prove the caller never repeats it."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    out = tmp_path / "gh-stdout.json"
    out.write_text(stdout)
    gh = d / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'if [ "$GH_TOKEN" = "{GOOD}" ]; then cat "{out}"; exit 0; fi\n'
        'if [ -n "$GH_TOKEN" ]; then echo "HTTP 401: Bad credentials (token $GH_TOKEN)" >&2; exit 1; fi\n'
        'echo "HTTP 401: Requires authentication (https://api.github.com/graphql)" >&2; exit 1\n')
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ.get('PATH', '')}")
    return d


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    p = tmp_path / "claude" / ".gh-token"
    p.parent.mkdir()
    monkeypatch.setattr(gh_env, "TOKEN_FILE", p)
    monkeypatch.delenv("GH_TOKEN", raising=False)   # conftest's second _no_real_github shadows the one that clears it
    return p


def test_the_token_file_is_exported_as_gh_token(token_file):
    token_file.write_text(GOOD + "\n")
    assert gh_env.env(base={})["GH_TOKEN"] == GOOD


def test_an_explicit_gh_token_is_never_overridden(token_file):
    token_file.write_text(GOOD)
    assert gh_env.env(base={"GH_TOKEN": "explicit"})["GH_TOKEN"] == "explicit"


def test_no_file_leaves_the_environment_unchanged(token_file):
    assert "GH_TOKEN" not in gh_env.env(base={"PATH": "/bin"})
    assert gh_env.env(base={"PATH": "/bin"}) == {"PATH": "/bin"}


@pytest.mark.parametrize("content", ["", "   \n", "\n\n"])
def test_an_empty_token_file_is_no_token(token_file, content):
    token_file.write_text(content)
    assert "GH_TOKEN" not in gh_env.env(base={})


def test_an_unreadable_token_file_is_no_token(token_file):
    token_file.mkdir()   # a directory where the file should be: read fails, never raises
    assert "GH_TOKEN" not in gh_env.env(base={})


def test_the_default_token_file_is_under_claude_in_home():
    assert gh_env.DEFAULT_TOKEN_FILE == Path.home() / ".claude" / ".gh-token"


def test_run_reaches_github_with_the_token_when_the_keychain_is_locked(tmp_path, monkeypatch, token_file):
    fake_gh(tmp_path, monkeypatch, stdout='[{"ok": 1}]')
    token_file.write_text(GOOD)
    assert gh_env.run(["gh", "pr", "list"]).stdout == '[{"ok": 1}]'


def test_run_without_a_token_says_plainly_there_is_none(tmp_path, monkeypatch, token_file):
    fake_gh(tmp_path, monkeypatch)
    with pytest.raises(gh_env.GhError) as e:
        gh_env.run(["gh", "pr", "list"])
    msg = str(e.value)
    assert "no GitHub token" in msg and ".gh-token" in msg and "keychain" in msg


def test_run_with_an_expired_token_says_github_refused_it_and_never_repeats_it(tmp_path, monkeypatch, token_file):
    fake_gh(tmp_path, monkeypatch)
    token_file.write_text(EXPIRED)
    with pytest.raises(gh_env.GhError) as e:
        gh_env.run(["gh", "pr", "list"])
    msg = str(e.value)
    assert "refused" in msg and "expired" in msg
    assert EXPIRED not in msg   # gh echoed it; the reason must not


def test_run_without_check_returns_the_failure_for_the_caller_to_read(tmp_path, monkeypatch, token_file):
    fake_gh(tmp_path, monkeypatch)
    r = gh_env.run(["gh", "issue", "view", "1"], check=False)
    assert r.returncode == 1 and "Requires authentication" in r.stderr


def test_a_missing_gh_is_a_plain_error_not_a_crash(tmp_path, monkeypatch, token_file):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(gh_env.GhError) as e:
        gh_env.run(["gh", "pr", "list"])
    assert "gh" in str(e.value)
