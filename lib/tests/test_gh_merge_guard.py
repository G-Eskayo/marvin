"""Tests for gh_merge_guard.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_gh_merge_guard.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import gh_merge_guard as g  # noqa: E402


def test_allows_pr_number_then_dash_r():
    result = g.check("gh pr merge 86 -R G-Eskayo/marvin --merge")
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_allows_dash_r_before_pr_number():
    result = g.check("gh pr merge -R G-Eskayo/marvin 86 --merge")
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_allows_long_form_repo_flag():
    result = g.check("gh pr merge 86 --repo G-Eskayo/marvin --merge")
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_allows_equals_form_repo_flag():
    result = g.check("gh pr merge 86 --repo=G-Eskayo/marvin --merge")
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_rejects_a_different_repo():
    assert g.check("gh pr merge 86 -R someone-else/other-repo --merge") is None


def test_rejects_missing_repo_flag_entirely():
    assert g.check("gh pr merge 86 --merge") is None


def test_rejects_non_merge_gh_commands():
    assert g.check("gh pr close 86 -R G-Eskayo/marvin") is None
    assert g.check("gh pr view 86 -R G-Eskayo/marvin") is None
    assert g.check("gh issue edit 20 -R G-Eskayo/marvin --add-label foo") is None


def test_rejects_unrelated_commands():
    assert g.check("git push origin main") is None
    assert g.check("rm -rf /") is None


class _FakeStdin:
    def __init__(self, stdin_bytes: bytes):
        import io
        self.buffer = io.BytesIO(stdin_bytes)


def test_main_never_raises_on_garbage_stdin(monkeypatch, capsys):
    monkeypatch.setattr(g.sys, "stdin", _FakeStdin(b"not json"))
    g.main()  # should not raise
    assert capsys.readouterr().out == ""


def test_main_writes_allow_decision_for_a_matching_command(monkeypatch, capsys):
    import json as json_module
    payload = json_module.dumps({"tool_input": {"command": "gh pr merge 1 -R G-Eskayo/marvin --merge"}}).encode()
    monkeypatch.setattr(g.sys, "stdin", _FakeStdin(payload))
    g.main()
    out = json_module.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_main_writes_nothing_for_a_non_matching_command(monkeypatch, capsys):
    import json as json_module
    payload = json_module.dumps({"tool_input": {"command": "ls -la"}}).encode()
    monkeypatch.setattr(g.sys, "stdin", _FakeStdin(payload))
    g.main()
    assert capsys.readouterr().out == ""
