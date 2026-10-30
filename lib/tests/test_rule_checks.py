"""marvin#826 step 2: the repo's rules run before each commit, not first at merge. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_rule_checks.py -v

The rules (secrets, the instance split in test_instance*.py, the Decisions format) used to fail only in the merge
gate, after the work was done (#767 and #770 each hard-coded the owner and went red there). lib/rule_checks.py runs
them as a pre-commit hook and as CI's "Rules" check. Real temp git repos and real `git commit`; nothing is mocked
except, where named, the rule-test runner.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import decisions_check as dc  # noqa: E402
import rule_checks as rc  # noqa: E402

needs_node = pytest.mark.skipif(not dc.find_node(), reason="node is not installed")
KEY = "sk-ant-" + "a1B2" * 10  # split so this file never matches its own pattern


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / "config" / "push-guard").mkdir(parents=True)
    (r / "config" / "push-guard" / "patterns.txt").write_text("# shared\nsk-ant-[A-Za-z0-9_-]{30,}\n")
    (r / "config" / "push-guard" / "paths.txt").write_text("(^|/)logs/.*\\.jsonl$\n")
    (r / "README.md").write_text("hi\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


def _stage(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    _git(repo, "add", rel)


# ── secrets ─────────────────────────────────────────────────────────────────

def test_a_staged_key_is_found_with_its_file_and_line(repo, tmp_path):
    _stage(repo, "lib/x.py", f'ok = 1\nTOKEN = "{KEY}"\n')
    hits = rc.secret_hits(repo, private=tmp_path / "none.txt")
    assert hits == ["lib/x.py:2 matches a secret pattern (config/push-guard/patterns.txt)"]


def test_a_short_test_fake_and_an_unstaged_key_are_not_flagged(repo, tmp_path):
    _stage(repo, "lib/x.py", 'FAKE = "sk-ant-abc123"\n')
    (repo / "lib" / "y.py").write_text(f'T = "{KEY}"\n')  # not staged: not in this commit
    assert rc.secret_hits(repo, private=tmp_path / "none.txt") == []


def test_a_key_already_committed_is_not_flagged_again_only_new_lines_are(repo, tmp_path):
    _stage(repo, "lib/x.py", f'T = "{KEY}"\n')
    _git(repo, "commit", "-q", "--no-verify", "-m", "old")
    _stage(repo, "lib/x.py", f'T = "{KEY}"\nnew = 2\n')
    assert rc.secret_hits(repo, private=tmp_path / "none.txt") == []


def test_the_owners_private_patterns_are_used_and_never_printed(repo, tmp_path):
    private = tmp_path / "private.txt"
    private.write_text("# mine\n555-0199\n")
    _stage(repo, "notes.txt", "call 555-0199\n")
    hits = rc.secret_hits(repo, private=private)
    assert hits == ["notes.txt:1 matches one of your private patterns"]
    assert "555" not in hits[0]


def test_a_forbidden_path_is_refused_even_when_its_content_is_clean(repo, tmp_path):
    _stage(repo, "logs/run.jsonl", "{}\n")
    assert rc.secret_hits(repo, private=tmp_path / "none.txt") == ["logs/run.jsonl: this path may never be committed (config/push-guard/paths.txt)"]


def test_a_repo_without_shared_patterns_still_refuses_transcripts(tmp_path):
    r = tmp_path / "bare"
    r.mkdir()
    _git(r, "init", "-q")
    _stage(r, "chat.transcript", "x\n")
    assert rc.secret_hits(r, private=tmp_path / "none.txt") == ["chat.transcript: this path may never be committed (config/push-guard/paths.txt)"]


# ── the Decisions format ────────────────────────────────────────────────────

BROKEN = "## Decisions\n<!-- marvin:decisions -->\n### : no id here?\n- [ ] only one option\n"
GOOD = "## Decisions\n<!-- marvin:decisions -->\n### pick: Which?\n- [ ] A\n- [ ] B\n"


@needs_node
def test_a_staged_doc_whose_decisions_block_does_not_parse_is_refused(repo):
    _stage(repo, "docs/plan.md", BROKEN)
    probs = rc.decisions_problems(repo, ["docs/plan.md"])
    assert len(probs) == 1 and probs[0].startswith("docs/plan.md: DECISIONS_UNPARSED")


@needs_node
def test_a_doc_that_only_records_a_decision_is_not_an_ask(repo):
    # An ADR's "## Decision" section records what was decided; only a real block must parse.
    _stage(repo, "docs/adr/0001.md", "# ADR\n\n## Decision\n\nWe use X.\n")
    _stage(repo, "docs/good.md", GOOD)
    _stage(repo, "lib/x.py", BROKEN)  # not markdown: not a doc
    assert rc.decisions_problems(repo, ["docs/adr/0001.md", "docs/good.md", "lib/x.py"]) == []


def test_a_deleted_doc_is_not_read(repo):
    assert rc.decisions_problems(repo, ["docs/gone.md"]) == []


# ── the hook as a whole ─────────────────────────────────────────────────────

def test_pre_commit_runs_the_rule_tests_and_refuses_when_they_fail(repo, tmp_path):
    _stage(repo, "lib/x.py", "x = 1\n")
    ran = []
    ok, report = rc.pre_commit(repo, env={}, private=tmp_path / "none.txt",
                               run_tests=lambda r: ran.append(r) or (False, "FAILED test_instance.py::ratchet"))
    assert ran == [repo] and not ok and "ratchet" in report


def test_pre_commit_with_nothing_staged_does_nothing(repo, tmp_path):
    ok, report = rc.pre_commit(repo, env={}, private=tmp_path / "none.txt", run_tests=lambda r: pytest.fail("ran"))
    assert ok


def test_an_auto_sync_commit_skips_the_slow_rules_but_never_the_secret_scan(repo, tmp_path):
    _stage(repo, "lib/x.py", f'T = "{KEY}"\n')
    env = {"MARVIN_COMMIT_KIND": "auto-sync"}
    ok, report = rc.pre_commit(repo, env=env, private=tmp_path / "none.txt", run_tests=lambda r: pytest.fail("ran"))
    assert not ok and "secret" in report


def test_the_rule_tests_are_the_content_rules_and_exist():
    for node in rc.RULE_TESTS:
        path, _, name = node.partition("::")
        assert f"def {name.split('[')[0]}(" in (ROOT / path).read_text(), node
    assert {n.split("::")[0] for n in rc.RULE_TESTS} == {"lib/tests/test_instance.py", "lib/tests/test_instance_move.py"}


def test_a_repo_without_the_rule_tests_passes_that_part(tmp_path):
    assert rc.run_rule_tests(tmp_path) == (True, "no rule tests in this repo")


def test_the_real_rule_tests_pass_here_and_quickly():
    import time
    t = time.monotonic()
    ok, out = rc.run_rule_tests(ROOT)
    assert ok, out
    assert time.monotonic() - t < 60, "a pre-commit hook has to stay fast"


# ── installed: a real `git commit` ──────────────────────────────────────────

def test_install_puts_the_hook_in_and_never_over_someone_elses(repo):
    assert rc.install_hook(repo) == "installed"
    assert rc.install_hook(repo) == "already installed"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    assert rc.install_hook(repo).startswith("skipped")


def test_a_real_commit_with_a_staged_key_is_refused(repo, tmp_path):
    rc.install_hook(repo)
    _stage(repo, "lib/x.py", f'T = "{KEY}"\n')
    env = {**os.environ, "HOME": str(tmp_path / "home"), "MARVIN_RULES_SKIP_TESTS": "1"}
    r = _git(repo, "commit", "-m", "add key", env=env)
    assert r.returncode != 0 and "lib/x.py:1" in r.stderr
    assert _git(repo, "log", "--oneline").stdout.count("\n") == 1  # still only the first commit
    _stage(repo, "lib/x.py", "T = None\n")
    assert _git(repo, "commit", "-q", "-m", "clean", env=env).returncode == 0


# ── CI's "Rules" check ──────────────────────────────────────────────────────

@needs_node
def test_ci_checks_the_docs_the_branch_changed_since_its_base(repo, tmp_path):
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _stage(repo, "docs/plan.md", BROKEN)
    _git(repo, "commit", "-q", "--no-verify", "-m", "bad doc")
    rc_code, out = rc.ci(repo, base, run_tests=lambda r: (True, ""))
    assert rc_code == 1 and "docs/plan.md: DECISIONS_UNPARSED" in out
    assert rc.ci(repo, "HEAD", run_tests=lambda r: (True, ""))[0] == 0  # nothing changed since HEAD


def test_ci_without_a_base_checks_every_tracked_doc(repo):
    calls = []
    rc.ci(repo, None, run_tests=lambda r: (True, ""), check_docs=lambda r, paths: calls.append(paths) or [])
    assert calls == [["README.md"]]


def test_the_rules_check_is_on_the_required_list():
    import required_checks
    rules = next(c for c in required_checks.load(ROOT) if c["id"] == "rules")
    assert rules["command"] == ["python", "lib/rule_checks.py", "ci"] and rules["where"] == "both"
