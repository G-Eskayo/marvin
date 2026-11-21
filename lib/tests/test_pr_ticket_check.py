"""Tests for lib/pr_ticket_check.py, a PR names its ticket (marvin#1004). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_pr_ticket_check.py -v

The parser runs the same cases file as the dashboard's (dashboard/test/fixtures/pr_ticket_refs_cases.json), so the
gate and the boards can't disagree about what names a ticket. The end-to-end tests run the real bin/gh with a fake
`gh` behind it: nothing reaches GitHub.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
import pr_ticket_check as pt  # noqa: E402

CASES = json.loads((ROOT / "dashboard" / "test" / "fixtures" / "pr_ticket_refs_cases.json").read_text())["cases"]
RELATION_CASES = json.loads((ROOT / "dashboard" / "test" / "fixtures" / "relation_refs_cases.json").read_text())["cases"]


# ── the parser: one rule, two languages ──────────────────────────────────────

@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_shared_cases(case):
    got = [[f"{r}#{n}", rel] for r, n, rel in pt.ticket_refs(case["body"], case["prRepo"])]
    assert got == case["refs"]


def test_none_body_is_empty():
    assert pt.ticket_refs(None, "o/r") == []


def test_unicode_digits_are_not_ticket_numbers():
    assert pt.ticket_refs("Closes #١٢", "o/r") == []  # Arabic-Indic digits: JS \d wouldn't match them


@pytest.mark.parametrize("case", RELATION_CASES, ids=[c["name"] for c in RELATION_CASES])
def test_relation_refs_shared_cases(case):
    got = [[f"{r}#{n}", rel] for r, n, rel in pt.relation_refs(case["body"], case["prRepo"])]
    assert got == case["refs"]


# ── which calls are checked ─────────────────────────────────────────────────

@pytest.mark.parametrize("argv,repo,target", [
    (["pr", "create", "--title", "t", "--body", "B"], None, None),
    (["pr", "create", "-R", "o/r", "-b", "B"], "o/r", None),
    (["pr", "create", "--repo=o/r", "--body=B"], "o/r", None),
    (["pr", "edit", "12", "--body", "B"], None, "12"),
    (["pr", "edit", "--title", "x", "12", "-F", "f.md"], None, "12"),
    (["pr", "edit", "https://github.com/o/x/pull/12", "--body", "B"], "o/x", "https://github.com/o/x/pull/12"),
    (["pr", "edit", "https://github.com/o/x/pull/12", "-R", "o/r", "--body", "B"], "o/r", "https://github.com/o/x/pull/12"),
])
def test_finds_the_repo_and_target(argv, repo, target):
    c = pt.pr_call(argv)
    assert (c["repo"], c["target"]) == (repo, target)


@pytest.mark.parametrize("argv", [
    ["pr", "comment", "3", "--body", "B"],      # a comment is not the PR's description
    ["issue", "create", "--body", "B"],
    ["pr", "edit", "3", "--add-label", "x"],     # no new body
    ["pr", "create", "--body-file", "-"],        # stdin belongs to gh
    ["pr", "merge", "3"], ["pr", "list"], ["pr"], [],
])
def test_other_calls_are_not_checked(argv):
    assert pt.pr_call(argv) is None


# ── which repos ─────────────────────────────────────────────────────────────

@pytest.fixture
def registry(tmp_path):
    f = tmp_path / "registry.json"
    f.write_text(json.dumps({"boards": [{"repo": "G-Eskayo/marvin"}, {"repo": "G-Eskayo/clarity-captions"}]}))
    return f


def test_onboarded_reads_the_board_registry_ignoring_case(registry):
    assert pt.onboarded("g-eskayo/MARVIN", registry)
    assert not pt.onboarded("someone/else", registry)
    assert not pt.onboarded(None, registry)


@pytest.mark.parametrize("content", [None, "{bad", "[]", '{"boards": "x"}', '{"boards": [1, null]}'])
def test_no_or_broken_registry_means_not_onboarded(tmp_path, content):
    f = tmp_path / "r.json"
    if content is not None:
        f.write_text(content)
    assert not pt.onboarded("G-Eskayo/marvin", f)


@pytest.mark.parametrize("url,repo", [
    ("git@github.com:G-Eskayo/marvin.git", "G-Eskayo/marvin"),
    ("https://github.com/G-Eskayo/marvin-instance.git", "G-Eskayo/marvin-instance"),
    ("https://github.com/o/r", "o/r"),
    ("https://gitlab.com/o/r.git", None),
])
def test_repo_here_reads_origin(tmp_path, url, repo):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", url], check=True)
    assert pt.repo_here(str(tmp_path)) == repo


def test_repo_here_outside_a_checkout_is_none(tmp_path):
    assert pt.repo_here(str(tmp_path)) is None


# ── gate: what bin/gh calls ─────────────────────────────────────────────────

def run_gate(argv, registry, env=None, here=lambda: "G-Eskayo/marvin", read_file=None, ask=None):
    said, logged = [], []
    rc = pt.gate(argv, said.append, logged.append, env=env or {}, registry=registry, here=here, read_file=read_file, ask=ask)
    return rc, said, logged


def test_refuses_a_body_naming_no_ticket_and_says_exactly_how_to_fix(registry):
    rc, said, logged = run_gate(["pr", "create", "--title", "t", "--body", "Mock-up for #235"], registry)
    assert rc == 1
    assert said[0].startswith("PR_NAMES_NO_TICKET")
    assert '"Closes #N"' in said[0] and '"Part of #N"' in said[0] and "owner/repo#N" in said[0]
    assert pt.OVERRIDE in said[1]
    assert logged == [{"cmd": "pr create", "repo": "G-Eskayo/marvin", "rc": 1, "no_ticket": logged[0]["no_ticket"]}]


@pytest.mark.parametrize("body", [
    "Closes #12", "Part of #235", "Part of G-Eskayo/marvin#949.", "Fixes https://github.com/G-Eskayo/marvin/issues/1",
])
def test_passes_either_form_silently(registry, body):
    assert run_gate(["pr", "create", "--body", body], registry) == (None, [], [])


def test_pr_edit_with_a_body_file_is_checked(registry, tmp_path):
    f = tmp_path / "b.md"
    f.write_text("## Summary\nNo ticket here.\n```\nCloses #5\n```\n")
    assert run_gate(["pr", "edit", "7", "--body-file", str(f)], registry)[0] == 1
    f.write_text("Part of #5\n")
    assert run_gate(["pr", "edit", "7", "--body-file", str(f)], registry)[0] is None


def test_an_unreadable_body_file_is_left_to_gh(registry, tmp_path):
    assert run_gate(["pr", "create", "-F", str(tmp_path / "missing.md")], registry) == (None, [], [])


def test_a_repo_without_a_board_is_exempt(registry):
    assert run_gate(["pr", "create", "--repo", "someone/else", "--body", "x"], registry) == (None, [], [])
    assert run_gate(["pr", "create", "--body", "x"], registry, here=lambda: None) == (None, [], [])


def test_the_explicit_repo_wins_over_the_checkout(registry):
    # in a non-board checkout, but the PR goes to a board repo
    assert run_gate(["pr", "create", "-R", "G-Eskayo/clarity-captions", "--body", "x"], registry, here=lambda: "o/other")[0] == 1


def test_override_lets_one_call_through_and_logs_why(registry):
    rc, said, logged = run_gate(["pr", "edit", "3", "--body", "x"], registry, env={pt.OVERRIDE: "release PR, no ticket"})
    assert rc is None and said == []
    assert logged == [{"cmd": "pr edit", "repo": "G-Eskayo/marvin", "no_ticket_override": "release PR, no ticket"}]


def test_a_blank_override_is_no_override(registry):
    assert run_gate(["pr", "edit", "3", "--body", "x"], registry, env={pt.OVERRIDE: "  "})[0] == 1


def test_the_pipelines_own_pr_body_passes_unchanged(registry):
    """lib/mr_raiser.py's body, as it builds it: 'Closes owner/repo#N' first."""
    import mr_raiser
    import inspect
    src = inspect.getsource(mr_raiser._default_open_pr)
    assert 'f"Closes {ticket_ref}' in src  # if this changes, the case below must change with it
    body = "Closes G-Eskayo/marvin#1004\n\nAutonomously implemented and verified by the MR pipeline.\n\n## Device\n..."
    assert run_gate(["pr", "create", "--repo", "G-Eskayo/marvin", "--title", "t", "--body", body], registry) == (None, [], [])


def test_the_onboarding_pr_body_passes(registry):
    import project_onboard
    assert pt.refusal(project_onboard._closes(7)) is None


# ── end to end: the real bin/gh, a fake gh behind it ────────────────────────

@pytest.fixture
def fake_gh(tmp_path, registry):
    home = tmp_path / "home"
    (home / ".claude" / "boards").mkdir(parents=True)
    (home / ".claude" / "boards" / "registry.json").write_text(registry.read_text())
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "called"
    (bindir / "gh").write_text(f"#!/bin/sh\necho \"$@\" >> {called}\necho '[]'\n")
    (bindir / "gh").chmod(0o755)
    # MARVIN_PULL_ONLY=0: about a full node, as every Mac is; an unregistered Linux machine (CI, #1117) is pull-only.
    env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}:/usr/bin:/bin", "MARVIN_UI_EVIDENCE_OK": "test",
           "MARVIN_DECISIONS_OK": "test", "MARVIN_PULL_ONLY": "0"}
    env.pop("MARVIN_GH_GATE_INSIDE", None)
    env.pop("MARVIN_NO_TICKET", None)
    return env, called


def _bin_gh(args, env):
    return subprocess.run([sys.executable, str(ROOT / "bin" / "gh"), *args], capture_output=True, text=True, env=env, timeout=60)


def test_bin_gh_refuses_before_reaching_github(fake_gh):
    env, called = fake_gh
    p = _bin_gh(["pr", "create", "--repo", "G-Eskayo/marvin", "--title", "t", "--body", "for #5"], env)
    assert p.returncode == 1, p.stderr
    assert "PR_NAMES_NO_TICKET" in p.stderr
    assert not called.exists()


def test_bin_gh_lets_a_named_ticket_through(fake_gh):
    env, called = fake_gh
    p = _bin_gh(["pr", "create", "--repo", "G-Eskayo/marvin", "--title", "t", "--body", "Part of #5"], env)
    assert p.returncode == 0, p.stderr
    assert "pr create" in called.read_text()


# ── MARVIN's own ticketless PR writers say why, so the rule doesn't break them ──

def _captured_env(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw.get("env") or {})
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def test_the_auto_fix_batch_names_why_it_has_no_ticket(monkeypatch):
    sys.path.insert(0, str(ROOT / "skills" / "improve" / "scripts"))
    import auto_fix
    seen = _captured_env(monkeypatch)
    auto_fix._gh(["pr", "create", "--body", "x"])
    assert seen.get(pt.OVERRIDE, "").strip()


def test_the_shadow_mutation_score_edit_names_why(monkeypatch):
    import auto_merge_shadow
    seen = _captured_env(monkeypatch)
    auto_merge_shadow._gh(["pr", "edit", "u", "--body", "x"])
    assert seen.get(pt.OVERRIDE, "").strip()


# ── red ticket warnings (marvin#1147) ──────────────────────────────────────

def test_is_red_ticket_with_main_red_label():
    assert pt.is_red_ticket({"labels": [{"name": "main-red"}]})
    assert pt.is_red_ticket({"labels": ["main-red"]})


def test_is_red_ticket_with_bug_p0_and_title():
    assert pt.is_red_ticket({"labels": [{"name": "bug"}, {"name": "priority:p0"}], "title": "Main is red at 9f4ac8d"})
    assert pt.is_red_ticket({"labels": ["bug", "priority:p0"], "title": "Main red: webhook issue"})


def test_is_red_ticket_needs_both_labels():
    assert not pt.is_red_ticket({"labels": [{"name": "bug"}], "title": "Main is red"})
    assert not pt.is_red_ticket({"labels": [{"name": "priority:p0"}], "title": "Main is red"})


def test_is_red_ticket_case_insensitive_on_labels():
    assert pt.is_red_ticket({"labels": ["BUG", "PRIORITY:P0"], "title": "Main is red"})


def test_is_red_ticket_defensively_handles_missing_data():
    assert not pt.is_red_ticket(None)
    assert not pt.is_red_ticket({})
    assert not pt.is_red_ticket({"labels": None})
    assert not pt.is_red_ticket({"labels": "not-a-list"})


def test_red_ticket_warning_part_of_red_ticket(registry):
    def fake_ask(args):
        if "issue" in args and "1234" in args:
            return {"labels": [{"name": "main-red"}], "title": "Main is red"}
        return {}
    rc, said, logged = run_gate(
        ["pr", "create", "--body", "Part of #1234"],
        registry,
        ask=fake_ask
    )
    assert rc is None
    assert any("red ticket" in s for s in said)
    assert any("red_ticket_warning" in str(e) for e in logged)


def test_red_ticket_warning_caps_lookups(registry):
    lookups = []
    def fake_ask(args):
        if "issue" in args:
            lookups.append(args)
            # Only return red for tickets beyond the cap (they shouldn't be looked up)
            return {"labels": [], "title": "Some ticket", "state": "OPEN"}
        return {}
    # Create 20 separate "Part of" statements to trigger the cap
    body_parts = [f"Part of #{i}" for i in range(20)]
    rc, said, logged = run_gate(
        ["pr", "create", "--body", "\n".join(body_parts)],
        registry,
        ask=fake_ask
    )
    # Exactly MAX_PART_OF_LOOKUPS lookups, no more
    assert len(lookups) == pt.MAX_PART_OF_LOOKUPS
    # No warning since we returned non-red tickets
    assert not any("red ticket" in s for s in said)


def test_red_ticket_warning_closes_red_gives_no_warning(registry):
    def fake_ask(args):
        if "issue" in args and "1234" in args:
            return {"labels": [{"name": "main-red"}], "title": "Main is red", "state": "OPEN"}
        return {}
    rc, said, logged = run_gate(
        ["pr", "create", "--body", "Closes #1234"],
        registry,
        ask=fake_ask
    )
    assert rc is None
    assert not any("red ticket" in s for s in said)
    assert not any("red_ticket_warning" in str(e) for e in logged)


def test_red_ticket_warning_cross_repo_target(registry):
    def fake_ask(args):
        if "issue" in args and "1234" in args:
            # Check if the --repo argument is correct
            if "--repo" in args:
                repo_idx = args.index("--repo") + 1
                if repo_idx < len(args) and args[repo_idx] == "other/repo":
                    return {"labels": [{"name": "main-red"}], "title": "Main is red", "state": "OPEN"}
        return {}
    rc, said, logged = run_gate(
        ["pr", "create", "--body", "Part of other/repo#1234"],
        registry,
        ask=fake_ask
    )
    assert rc is None
    assert any("red ticket" in s for s in said)
    assert any("red_ticket_warning" in str(e) for e in logged)


def test_red_ticket_warning_closes_one_red_part_of_another(registry):
    def fake_ask(args):
        if "issue" in args:
            if "1234" in args:
                return {"labels": [{"name": "main-red"}], "title": "Main is red", "state": "OPEN"}
            elif "5678" in args:
                return {"labels": [{"name": "bug"}, {"name": "priority:p0"}], "title": "Main is red in webhook", "state": "OPEN"}
        return {}
    rc, said, logged = run_gate(
        ["pr", "create", "--body", "Closes #1234\nPart of #5678"],
        registry,
        ask=fake_ask
    )
    assert rc is None
    # Should warn about the part-of red ticket
    assert any("red ticket" in s for s in said)
    assert any("red_ticket_warning" in str(e) for e in logged)


def test_red_ticket_warning_part_of_non_red_ticket(registry):
    def fake_ask(args):
        if "issue" in args and "1234" in args:
            return {"labels": [{"name": "enhancement"}], "title": "Add feature X", "state": "OPEN"}
        return {}
    rc, said, logged = run_gate(
        ["pr", "create", "--body", "Part of #1234"],
        registry,
        ask=fake_ask
    )
    assert rc is None
    assert not any("red ticket" in s for s in said)
    assert not any("red_ticket_warning" in str(e) for e in logged)


def test_red_ticket_warning_part_of_closed_red_ticket(registry):
    def fake_ask(args):
        if "issue" in args and "1234" in args:
            return {"labels": [{"name": "main-red"}], "title": "Main is red", "state": "CLOSED"}
        return {}
    rc, said, logged = run_gate(
        ["pr", "create", "--body", "Part of #1234"],
        registry,
        ask=fake_ask
    )
    assert rc is None
    assert not any("red ticket" in s for s in said)
    assert not any("red_ticket_warning" in str(e) for e in logged)




def test_red_ticket_warning_fails_open(registry):
    def fake_ask(args):
        raise RuntimeError("network error")
    rc, said, logged = run_gate(
        ["pr", "create", "--body", "Part of #1234"],
        registry,
        ask=fake_ask
    )
    # Still lets the PR through (no refusal, no warning said)
    assert rc is None
    assert not any("red ticket" in s for s in said)
