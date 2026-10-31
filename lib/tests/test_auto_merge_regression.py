"""Rung 3's own merge for regressions of known incidents (ADR 0064 amendment), shadow mode. Tests try to break it: a
PR with no failing-first test, a test that passes before the fix, one that can't even run before it, core files that
must still wait, the per-day cap, and a probe that still trips after merge. Real git in temp repos; no GitHub."""
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import auto_merge_policy as amp
import auto_merge_regression as amr

RULES = amp.load_rules()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "clone"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "lib").mkdir()
    (r / "lib" / "tests").mkdir()
    (r / "lib" / "sync.py").write_text("def stuck(n):\n    return n > 5   # the regression: should be n > 0\n")
    (r / "lib" / "tests" / "test_sync.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\nimport sync\n\n"
        "def test_big():\n    assert sync.stuck(9)\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _branch(repo, name, files: dict):
    _git(repo, "checkout", "-q", "-b", name, "main")
    for path, text in files.items():
        (repo / path).write_text(textwrap.dedent(text))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", name)
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    return _git(repo, "rev-parse", "main"), head


NEW_TEST = """\
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import sync

def test_big():
    assert sync.stuck(9)

def test_one_stuck_episode_counts():
    assert sync.stuck(1)
"""
FIX = "def stuck(n):\n    return n > 0\n"


def test_a_fix_with_a_failing_first_test_passes_the_check(repo):
    base, head = _branch(repo, "fix", {"lib/sync.py": FIX, "lib/tests/test_sync.py": NEW_TEST})
    r = amr.regression_test_check(repo, base, head)
    assert r["ok"] and r["failed_before"] and r["passed_after"] and r["tests"] == ["lib/tests/test_sync.py"]
    assert _git(repo, "worktree", "list").count("\n") == 0           # scratch trees cleaned up


def test_a_pr_without_a_test_is_not_eligible(repo):
    base, head = _branch(repo, "notest", {"lib/sync.py": FIX})
    r = amr.regression_test_check(repo, base, head)
    assert not r["ok"] and "no test" in r["why"]


def test_a_test_that_already_passes_before_the_fix_does_not_count(repo):
    weak = NEW_TEST.replace("sync.stuck(1)", "sync.stuck(9)")
    base, head = _branch(repo, "weak", {"lib/sync.py": FIX, "lib/tests/test_sync.py": weak})
    r = amr.regression_test_check(repo, base, head)
    assert not r["ok"] and not r["failed_before"] and "pass on the code before the fix too" in r["why"]


def test_a_test_that_cannot_even_import_before_the_fix_is_not_a_failing_test(repo):
    broken = NEW_TEST.replace("import sync", "import sync\nfrom sync import new_helper")
    base, head = _branch(repo, "import", {"lib/sync.py": FIX + "\ndef new_helper():\n    pass\n",
                                          "lib/tests/test_sync.py": broken})
    r = amr.regression_test_check(repo, base, head)
    assert not r["ok"] and "couldn't run before the fix" in r["why"]


def test_a_test_without_the_fix_does_not_pass_after(repo):
    base, head = _branch(repo, "testonly", {"lib/tests/test_sync.py": NEW_TEST})
    r = amr.regression_test_check(repo, base, head)
    assert not r["ok"] and r["failed_before"] and not r["passed_after"]


def test_a_hung_test_is_not_ok(repo):
    base, head = _branch(repo, "fix2", {"lib/sync.py": FIX, "lib/tests/test_sync.py": NEW_TEST})
    r = amr.regression_test_check(repo, base, head, pytest=lambda tree, tests: -1)
    assert not r["ok"]


# ── the verdict ────────────────────────────────────────────────────────────────────────────────────────────────

GOOD_TEST = {"ok": True, "failed_before": True, "passed_after": True, "why": "fails before the fix and passes after"}


def _pr(files=("lib/code_sync.py", "lib/tests/test_code_sync.py"), score=92):
    return {"repo": RULES.get("home_repo", "o/r"), "number": 812, "url": "u/812", "incident": 707,
            "body": f"Closes #707\n\n**Score:** {score}%" if score is not None else "Closes #707",
            "files": [{"path": f, "additions": 10, "deletions": 2} for f in files]}


def _facts(**over):
    return {"ticket_labels": {"bug", "watch", "regression"}, "regression_test": GOOD_TEST, "main_green": True,
            "checks_green": True, "ramp_open": True, "existing_top_level": {"lib"}, **over}


def test_a_tested_regression_fix_may_touch_core_sync_code():
    assert amp.decide(_pr()["repo"], _pr()["files"], RULES, existing_top_level={"lib"}, new_top_level_this_week=0,
                      ramp_open=True)["verdict"] == "ask"            # ADR 0064 alone: sync is core
    v = amr.verdict(_pr(), _facts(), RULES)
    assert v["verdict"] == "auto", v


@pytest.mark.parametrize("path", ["config/auto_merge.json", "lib/auto_merge_policy.py", "lib/auto_merge_regression.py",
                                  "lib/trust_ramp.py", "dashboard/webhook-server/merge.js", "lib/mutation_check.py",
                                  "config/github_token.txt"])
def test_a_fix_can_never_loosen_the_rules_that_let_it_merge(path):
    v = amr.verdict(_pr(files=("lib/code_sync.py", path)), _facts(), RULES)
    assert v["verdict"] == "ask" and any("core" in r for r in v["reasons"])


@pytest.mark.parametrize("over,why", [
    ({"ticket_labels": {"bug", "regression"}}, "watched incident"),
    ({"ticket_labels": {"bug", "watch"}}, "watched incident"),
    ({"regression_test": None}, "hasn't been checked"),
    ({"regression_test": {"ok": False, "why": "the PR adds or changes no test file"}}, "no test file"),
    ({"main_green": False}, "main isn't green"),
    ({"main_green": None}, "main isn't green"),
    ({"checks_green": False}, "checks"),
    ({"ramp_open": False}, "trust ramp"),
    ({"merged_today": 1}, "already merged itself today"),
])
def test_every_guardrail_is_required(over, why):
    v = amr.verdict(_pr(), _facts(**over), RULES)
    assert v["verdict"] == "ask" and any(why in r for r in v["reasons"]), v


def test_the_mutation_check_is_required():
    assert amr.verdict(_pr(score=None), _facts(), RULES)["verdict"] == "ask"
    assert amr.verdict(_pr(score=60), _facts(), RULES)["verdict"] == "ask"


def test_everything_else_in_adr_0064_still_holds():
    assert amr.verdict(_pr(files=("lib/code_sync.py", "requirements.txt")), _facts(), RULES)["verdict"] == "ask"
    big = {**_pr(), "files": [{"path": "lib/code_sync.py", "additions": 2000, "deletions": 0}]}
    assert amr.verdict(big, _facts(), RULES)["verdict"] == "ask"
    assert amr.verdict(_pr(files=("../etc/passwd",)), _facts(), RULES)["verdict"] == "ask"


@pytest.mark.parametrize("section", [None, {"core_ok": False, "still_core": ["x"]}, {"core_ok": "yes", "still_core": ["x"]},
                                     {"core_ok": True}, {"core_ok": True, "still_core": []}, "garbage"])
def test_without_a_well_formed_amendment_every_core_file_still_waits(section):
    rules = {**RULES, "known_incident_regressions": section}
    assert amr.regression_rules(rules)["core"] == RULES["core"]
    assert amr.verdict(_pr(), _facts(), rules)["verdict"] == "ask"


def test_a_missing_rules_file_asks_for_everything(tmp_path):
    assert amr.verdict(_pr(), _facts(), amp.load_rules(tmp_path / "nope.json"))["verdict"] == "ask"


@pytest.mark.parametrize("pr,n", [({"headRefName": "pipeline/707"}, 707), ({"headRefName": "pipeline/o/r#707"}, 707),
                                  ({"headRefName": "feat/x", "body": "Closes #707\n"}, 707),
                                  ({"headRefName": "feat/x", "body": "Mentions #707"}, None),
                                  ({"headRefName": "pipeline/707; rm -rf ~"}, None), ({}, None)])
def test_the_incident_is_read_from_the_pipeline_branch_or_the_closes_line(pr, n):
    assert amr.incident_of(pr) == n


# ── shadow state: the cap, the post-merge re-measure, the report ───────────────────────────────────────────────

def test_shadow_records_once_and_caps_one_auto_merge_per_incident_per_day(tmp_path):
    path = tmp_path / "s.json"
    now = time.time()
    a, b = {**_pr(), "url": "u/1", "number": 1}, {**_pr(), "url": "u/2", "number": 2}
    seen = amr.observe([a, b], lambda p: _facts(), path, now=now)
    assert [s["verdict"] for s in seen] == ["auto", "ask"]
    assert any("already merged itself today" in r for r in seen[1]["reasons"])
    seen = amr.observe([a], lambda p: _facts(main_green=False), path, now=now + 60)
    assert seen[0]["verdict"] == "auto"                 # the first 'auto' is kept: that's when it would have merged
    nxt = amr.observe([b], lambda p: _facts(), path, now=now + 86400 * 1.5)
    assert nxt[0]["verdict"] == "auto"                  # a new day


def test_after_merge_a_probe_that_still_trips_would_revert(tmp_path):
    path = tmp_path / "s.json"
    now = time.time()
    amr.observe([_pr()], lambda p: _facts(), path, now=now)
    st = json.loads(path.read_text())
    st["prs"]["u/812"].update(outcome="merged", probe="code-sync-stuck", merged_at=now)
    path.write_text(json.dumps(st))
    assert amr.post_merge(path, lambda *a: pytest.fail("too early"), lambda u: None, now=now + 60) == []
    calls = []

    def measure(name, days):
        calls.append(days)
        return 1.0, {}
    done = amr.post_merge(path, measure, lambda u: None, now=now + amr.POST_MERGE_WAIT_S + 1)
    assert done[0]["would_revert"] is True and calls[0] == pytest.approx((amr.POST_MERGE_WAIT_S + 1) / 86400)
    assert amr.post_merge(path, lambda *a: pytest.fail("recorded once"), lambda u: None, now=now + 10 ** 5) == []
    r = amr.report(path)
    assert r["would_merge"] == 1 and r["would_revert"] == 1 and "reverted 1" in r["line"]


def test_after_merge_a_held_fix_is_kept_and_a_throwing_probe_is_retried(tmp_path):
    path = tmp_path / "s.json"
    now = time.time()
    amr.observe([_pr()], lambda p: _facts(), path, now=now)
    st = json.loads(path.read_text())
    st["prs"]["u/812"].update(outcome="merged", probe="code-sync-stuck", merged_at=now)
    path.write_text(json.dumps(st))
    later = now + amr.POST_MERGE_WAIT_S + 1

    def boom(*a):
        raise OSError("ssh down")
    assert amr.post_merge(path, boom, lambda u: None, now=later) == []
    done = amr.post_merge(path, lambda *a: (0.0, {}), lambda u: None, now=later + 3600)
    assert done[0]["would_revert"] is False


def test_shadow_never_merges_or_reverts(tmp_path, monkeypatch):
    """Nothing here calls gh merge, git revert or the trust ramp: shadow only records."""
    src = Path(amr.__file__).read_text()
    assert '"merge"' not in src and "revert" not in src.split("def run(")[1].replace("would_revert", "")
    assert "trust_ramp.record" not in src


def test_a_corrupt_state_is_never_overwritten(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{corrupt")
    with pytest.raises(ValueError):
        amr.observe([_pr()], lambda p: _facts(), path)
    assert path.read_text() == "{corrupt" and "unreadable" in amr.report(path)["line"]


def test_no_report_line_until_there_is_a_rung3_pr(tmp_path):
    assert amr.report(tmp_path / "none.json")["line"] is None


# ── a rung-3 fix written by mac-mini-2012's bot still needs the bot's own ramp (ADR 0069 rule 5, #952) ────────────

def test_a_bot_written_regression_fix_waits_until_the_bots_ramp_is_open():
    bot = {**_pr(), "author": "MARVIN-bot-gil"}
    assert amr.verdict(bot, _facts(), RULES)["verdict"] == "ask"
    assert amr.verdict(bot, _facts(author_ramp_open=False), RULES)["verdict"] == "ask"
    assert amr.verdict(bot, _facts(author_ramp_open=True), RULES)["verdict"] == "auto"
    assert amr.verdict({**_pr(), "author": "G-Eskayo"}, _facts(), RULES)["verdict"] == "auto"


def test_a_regression_fix_whose_author_is_unknown_waits():
    assert amr.verdict({**_pr(), "author": ""}, _facts(author_ramp_open=True), RULES)["verdict"] == "ask"
