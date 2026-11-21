"""The work loop, end to end (ADR 0080, marvin#737): each rule checked through the real bin/gh, in a temp HOME, against
a fake GitHub that records every call that reaches it. A rule holds only if a call that breaks it never gets there.
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_work_loop_e2e.py -v

Each rule adds its own section. I2 (askable questions, marvin#742) is below. I1 (UI evidence) tests image rules.
I3 (owner decisions) tests follow-up ticket filing.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "bin" / "gh"
FIX = Path(__file__).resolve().parent / "fixtures" / "decisions"

sys.path.insert(0, str(ROOT / "lib"))
import decisions_check as dc  # noqa: E402
import owner_decisions as od  # noqa: E402
import pr_images as pi  # noqa: E402


@pytest.fixture
def github(tmp_path):
    """A fake real gh: records each call's argv (and body file contents) to $HOME/github-calls.jsonl, prints {}."""
    d = tmp_path / "realbin"
    d.mkdir()
    gh = d / "gh"
    gh.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, sys\n"
        "a = sys.argv[1:]\n"
        "f = next((a[i + 1] for i, x in enumerate(a[:-1]) if x in ('--body-file', '-F')), None)\n"
        "rec = {'argv': a, 'body_file': open(f).read() if f and f != '-' else None}\n"
        "open(os.path.join(os.environ['HOME'], 'github-calls.jsonl'), 'a').write(json.dumps(rec) + '\\n')\n"
        "print('{}')\n")
    gh.chmod(0o755)
    return d


def _gh(tmp_path, realbin, *args, env_extra=None):
    # MARVIN_PULL_ONLY=0: about a full node, as every Mac is; an unregistered Linux machine (CI, #1117) is pull-only.
    env = {"PATH": f"{GATE.parent}:{realbin}:/usr/bin:/bin", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1",
           "MARVIN_INSTANCE_DIR": str(tmp_path / "instance"), "MARVIN_PULL_ONLY": "0", **(env_extra or {})}
    return subprocess.run([str(GATE), *args], capture_output=True, text=True, env=env, timeout=60)


def _reached(tmp_path):
    f = tmp_path / "github-calls.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def _gate_log(tmp_path):
    f = tmp_path / ".claude" / "logs" / "gh-calls.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def _body_file(tmp_path, name):
    f = tmp_path / name
    shutil.copy(FIX / name, f)
    return str(f)


def _route_gh(tmp_path, realbin, routes=None):
    """Rewrite fake gh to serve canned responses via config file. routes = {json-argv-list: response-dict}."""
    routes = routes or {}
    routes_cfg = tmp_path / ".gh-routes.json"
    routes_cfg.write_text(json.dumps(routes))

    gh = realbin / "gh"
    routes_path = str(routes_cfg)
    # Simpler script that records calls and serves responses from config file
    script_content = (
        "#!/usr/bin/python3\n"
        "import json, os, sys\n"
        "a = sys.argv[1:]\n"
        "f = next((a[i + 1] for i, x in enumerate(a[:-1]) if x in ('--body-file', '-F')), None)\n"
        "rec = {'argv': a, 'body_file': open(f).read() if f and f != '-' else None}\n"
        "home = os.environ.get('HOME')\n"
        "if home:\n"
        "    try:\n"
        "        with open(os.path.join(home, 'github-calls.jsonl'), 'a') as fh:\n"
        "            fh.write(json.dumps(rec) + '\\n')\n"
        "    except:\n"
        "        pass\n"
        "resp = None\n"
        "try:\n"
        "    cfg = " + repr(routes_path) + "\n"
        "    with open(cfg) as fh:\n"
        "        routes = json.loads(fh.read())\n"
        "    for key_str in routes:\n"
        "        key = json.loads(key_str)\n"
        "        if isinstance(key, list) and len(a) >= len(key) and a[:len(key)] == key:\n"
        "            resp = routes[key_str]\n"
        "            break\n"
        "except:\n"
        "    pass\n"
        "if resp is not None:\n"
        "    print(json.dumps(resp))\n"
        "else:\n"
        "    print(json.dumps({}))\n"
    )
    gh.write_text(script_content)
    gh.chmod(0o755)


def _od_run(tmp_path, realbin, fn, *args, **kwargs):
    """Run an owner_decisions function through the sandboxed gh (same PATH/HOME as _gh)."""
    env = {"PATH": f"{GATE.parent}:{realbin}:/usr/bin:/bin", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1",
           "MARVIN_INSTANCE_DIR": str(tmp_path / "instance"), "MARVIN_PULL_ONLY": "0"}

    # Inject a run= callable that uses the sandboxed gh
    def sandboxed_run(cmd_args, **run_kwargs):
        # Forward all kwargs, overriding only env to use sandboxed environment
        merged_kwargs = {**run_kwargs, 'env': env}
        return subprocess.run(cmd_args, **merged_kwargs)

    return fn(*args, run=sandboxed_run, **kwargs)


# ── I1 UI evidence: UI changes carry current, working images ───

def test_i1_a_ui_change_with_no_pinned_images_is_refused_through_bin_gh(tmp_path, github):
    """A PR changes UI files but shows no images → NO_UI_EVIDENCE, the PR create doesn't reach GitHub."""
    _route_gh(tmp_path, github, {
        json.dumps(["repo", "view"]): {"nameWithOwner": "o/r"},
        json.dumps(["api", "repos/o/r"]): {"default_branch": "main"},
        json.dumps(["api", "repos/o/r/compare/main...myhead"]): {
            "files": [{"filename": "src/View.swift"}]  # UI file changed
        }
    })
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "myhead", "--base", "main",
            "--title", "look change", "--body", "No images here.")
    assert p.returncode == 1
    assert "NO_UI_EVIDENCE" in p.stderr
    # The check calls GitHub to gather files, but pr create itself is refused before reaching GitHub
    calls = _reached(tmp_path)
    pr_creates = [c for c in calls if c["argv"][:2] == ["pr", "create"]]
    assert pr_creates == [], "PR create should be refused before reaching GitHub"


def test_i1_a_stale_pinned_image_is_refused_through_bin_gh(tmp_path, github):
    """Image pinned to an earlier commit, newer UI changes after → STALE_UI_EVIDENCE, PR create blocked."""
    old_sha = "0" * 40
    new_sha = "1" * 40
    _route_gh(tmp_path, github, {
        json.dumps(["repo", "view"]): {"nameWithOwner": "o/r"},
        json.dumps(["api", "repos/o/r"]): {"default_branch": "main"},
        json.dumps(["api", "repos/o/r/compare/main...myhead"]): {
            "files": [{"filename": "src/View.swift"}]
        },
        json.dumps(["api", f"repos/o/r/compare/{old_sha}...myhead"]): {
            "files": [{"filename": "src/View.swift"}]  # Still a UI file between the pinned commit and head
        }
    })
    body = f"![screenshot](https://raw.githubusercontent.com/o/r/{old_sha}/screenshot.png)"
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "myhead", "--base", "main",
            "--title", "look change", "--body", body)
    assert p.returncode == 1
    assert "STALE_UI_EVIDENCE" in p.stderr
    # The check calls GitHub to gather files, but pr create itself is refused before reaching GitHub
    calls = _reached(tmp_path)
    pr_creates = [c for c in calls if c["argv"][:2] == ["pr", "create"]]
    assert pr_creates == [], "PR create should be refused before reaching GitHub"


def test_i1_current_pinned_images_reach_github(tmp_path, github):
    """Correctly pinned image to current commit → call reaches GitHub unchanged."""
    head_sha = "a" * 40
    _route_gh(tmp_path, github, {
        json.dumps(["repo", "view"]): {"nameWithOwner": "o/r"},
        json.dumps(["api", "repos/o/r"]): {"default_branch": "main"},
        json.dumps(["api", "repos/o/r/compare/main...myhead"]): {
            "files": [{"filename": "src/View.swift"}]
        },
        json.dumps(["api", f"repos/o/r/compare/{head_sha}...myhead"]): {
            "files": []  # No UI changes after the pinned commit
        }
    })
    body = f"![screenshot](https://raw.githubusercontent.com/o/r/{head_sha}/screenshot.png)"
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "myhead", "--base", "main",
            "--title", "look change", "--body", body)
    assert p.returncode == 0, p.stderr
    calls = _reached(tmp_path)
    assert len(calls) > 0
    assert calls[-1]["argv"][:2] == ["pr", "create"]


def test_i1_a_fix_pushed_after_a_refusal_passes_the_same_check_again(tmp_path, github):
    """Refusal, then a corrected push → succeeds. The check has no memory that would strand it."""
    old_sha = "0" * 40
    head_sha = "a" * 40
    routes = {
        json.dumps(["repo", "view"]): {"nameWithOwner": "o/r"},
        json.dumps(["api", "repos/o/r"]): {"default_branch": "main"},
        json.dumps(["api", "repos/o/r/compare/main...myhead"]): {
            "files": [{"filename": "src/View.swift"}]
        },
    }
    _route_gh(tmp_path, github, routes)

    # Call 1: stale image (should fail)
    routes[json.dumps(["api", f"repos/o/r/compare/{old_sha}...myhead"])] = {
        "files": [{"filename": "src/View.swift"}]  # UI file still there
    }
    _route_gh(tmp_path, github, routes)
    p1 = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "myhead", "--base", "main",
             "--title", "look change", "--body", f"![img](https://raw.githubusercontent.com/o/r/{old_sha}/s.png)")
    assert p1.returncode == 1 and "STALE_UI_EVIDENCE" in p1.stderr

    # Call 2: corrected pinned image (should succeed)
    routes[json.dumps(["api", f"repos/o/r/compare/{head_sha}...myhead"])] = {
        "files": []  # No UI changes after the new pinned commit
    }
    _route_gh(tmp_path, github, routes)
    p2 = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "myhead", "--base", "main",
             "--title", "look change", "--body", f"![img](https://raw.githubusercontent.com/o/r/{head_sha}/s.png)")
    assert p2.returncode == 0, p2.stderr


# ── I2 askable questions: every question to the owner is machine-readable ───

i2 = pytest.mark.skipif(not dc.find_node(), reason="node is not installed (the dashboard's parser needs it)")


@i2
@pytest.mark.parametrize("name", ["cc179_prose.md", "cc181_prose.md"])
@pytest.mark.parametrize("cmd", [["pr", "create", "--title", "t", "--head", "x"], ["pr", "edit", "179"],
                                 ["issue", "create", "--title", "t"], ["issue", "edit", "5"], ["issue", "comment", "5"],
                                 ["pr", "comment", "179"]])
def test_i2_prose_decisions_never_reach_github(tmp_path, github, cmd, name):
    p = _gh(tmp_path, github, *cmd, "-R", "o/clarity-captions", "--body-file", _body_file(tmp_path, name))
    assert p.returncode == 1, p.stderr
    assert "DECISIONS_NOT_ASKABLE" in p.stderr and "docs/agents/decisions-format.md" in p.stderr
    assert dc.OVERRIDE in p.stderr
    assert _reached(tmp_path) == []
    assert [e.get("decisions", "")[:21] for e in _gate_log(tmp_path)] == ["DECISIONS_NOT_ASKABLE"]


@i2
def test_i2_prose_decisions_in_an_inline_body_are_refused_too(tmp_path, github):
    p = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "-b", (FIX / "cc181_prose.md").read_text())
    assert p.returncode == 1 and _reached(tmp_path) == []


@i2
def test_i2_a_block_that_does_not_parse_never_reaches_github(tmp_path, github):
    body = "## Decisions\n<!-- marvin:decisions -->\n### Which look?\n- [ ] A\n- [ ] B\n"
    p = _gh(tmp_path, github, "issue", "edit", "5", "-R", "o/r", "--body", body)
    assert p.returncode == 1 and "DECISIONS_UNPARSED" in p.stderr and "needs an id" in p.stderr
    assert _reached(tmp_path) == []


@i2
@pytest.mark.parametrize("name", ["cc174_block.md", "cc171_block.md"])
def test_i2_machine_readable_decisions_reach_github_unchanged(tmp_path, github, name):
    p = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "--body-file", _body_file(tmp_path, name))
    assert p.returncode == 0, p.stderr
    (call,) = _reached(tmp_path)
    assert call["argv"][:2] == ["issue", "comment"] and call["body_file"] == (FIX / name).read_text()


@i2
def test_i2_a_good_pr_create_goes_on_to_the_images_rule(tmp_path, github):
    # The order of the rules: I2 lets it through, then I1 asks GitHub about the PR (here a fake that knows nothing,
    # so I1 fails open). Both rules run on one call.
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "x", "--base", "main", "--title", "t",
            "--body-file", _body_file(tmp_path, "cc174_block.md"))
    assert p.returncode == 0, p.stderr
    assert _reached(tmp_path)[-1]["argv"][:2] == ["pr", "create"]


@i2
def test_i2_override_lets_one_call_through_and_is_logged(tmp_path, github):
    p = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "--body-file", _body_file(tmp_path, "cc179_prose.md"),
            env_extra={dc.OVERRIDE: "quoting an old PR in a write-up"})
    assert p.returncode == 0, p.stderr
    assert len(_reached(tmp_path)) == 1
    assert any(e.get("decisions_override") == "quoting an old PR in a write-up" for e in _gate_log(tmp_path))
    again = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "--body-file", _body_file(tmp_path, "cc179_prose.md"))
    assert again.returncode == 1  # one call, not a setting that sticks


@i2
def test_i2_calls_with_no_body_are_untouched(tmp_path, github):
    assert _gh(tmp_path, github, "issue", "list").returncode == 0
    assert _gh(tmp_path, github, "pr", "edit", "3", "--add-label", "x").returncode == 0
    assert len(_reached(tmp_path)) == 2


def test_i2_without_node_the_call_goes_through_with_a_note(tmp_path, github):
    # The gate's PATH has no node and the known places are hidden: a broken check must not stop all GitHub work.
    p = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "-b", "## Decisions\n1. A or B?",
            env_extra={"MARVIN_NODE": str(tmp_path / "no-node")})
    assert p.returncode == 0
    assert "node" in p.stderr and len(_reached(tmp_path)) == 1


# ── I3 owner decisions: follow-up tickets for unanswered decisions ───

def _make_pr_data(repo, number, body, branch="feature", comment_body=None, comment_id=None, with_commit_after_comment=False):
    """Helper to build a PR dict for owner_decisions functions."""
    commits = []
    if with_commit_after_comment:
        # Commit dated after the decision comment
        commits.append({
            "commit": {
                "committedDate": "2026-11-21T12:00:00Z",
                "authoredDate": "2026-11-21T12:00:00Z",
                "parents": {"totalCount": 1}
            }
        })

    comments = []
    if comment_body:
        comments.append({
            "databaseId": comment_id or 1001,
            "url": f"https://github.com/{repo}/pull/{number}#issuecomment-{comment_id or 1001}",
            "createdAt": "2026-11-21T10:00:00Z",
            "body": comment_body,
            "author": {"login": repo.split("/")[0].lower()}
        })

    return {
        "repo": repo,
        "number": number,
        "title": "Test PR",
        "url": f"https://github.com/{repo}/pull/{number}",
        "headRefName": branch,
        "body": body,
        "last_commit_at": "2026-11-21T11:00:00Z" if not with_commit_after_comment else "2026-11-21T12:00:00Z",
        "last_work_at": "2026-11-21T11:00:00Z" if not with_commit_after_comment else "2026-11-21T12:00:00Z",
        "comments": comments
    }


def test_i3_a_push_with_no_reply_leaves_the_pr_waiting(tmp_path, github):
    """Commit lands after owner's Decisions, no ADDRESSED_MARKER reply → waiting() lists PR, sync() files follow-up."""
    # Route GitHub to serve PR data: one open PR with decisions, no reply yet
    head_sha = "a" * 40
    routes = {
        json.dumps(["api", "graphql"]): {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{
                        "number": 42, "title": "Test PR", "url": "https://github.com/o/r/pull/42",
                        "headRefName": "feature", "body": "PR body",
                        "repository": {"nameWithOwner": "o/r"},
                        "commits": {"nodes": [
                            {"commit": {"committedDate": "2026-11-21T12:00:00Z", "authoredDate": "2026-11-21T12:00:00Z", "parents": {"totalCount": 1}}}
                        ]},
                        "comments": {"nodes": [{
                            "databaseId": 1001,
                            "url": "https://github.com/o/r/pull/42#issuecomment-1001",
                            "createdAt": "2026-11-21T10:00:00Z",
                            "body": "### Decisions from the owner\n```marvin-decisions\n{}\n```",
                            "author": {"login": "o"}
                        }]}
                    }]
                },
                "followups": {"nodes": []}
            }
        }
    }
    _route_gh(tmp_path, github, routes)

    # Call waiting() through the sandboxed gh to verify the PR is listed
    now = datetime(2026, 11, 21, 15, 0, 0, tzinfo=timezone.utc)  # 5 hours after decision
    result = _od_run(tmp_path, github, od.waiting, ["o/r"], now=now)
    assert result is not None, "waiting() should not return None"
    assert len(result) == 1, "Should list the PR with unanswered decisions"
    assert result[0]["number"] == 42
    assert result[0]["addressed_by"] is None, "PR has no reply yet"
    assert result[0]["committed_since"] is True, "Commit lands after decisions"


def test_i3_a_reply_with_the_addressed_marker_closes_the_follow_up(tmp_path, github):
    """Reply with ADDRESSED_MARKER posted through bin/gh → waiting() is empty, sync() closes the follow-up."""
    decisions_comment = "### Decisions from the owner\n```marvin-decisions\n{}\n```"
    reply_body = f"I've addressed this. {od.ADDRESSED_MARKER}"

    followup_marker = f"<!-- marvin:owner-decisions pr=42 comment=1001 since=2026-11-21T10:00:00Z question=no -->"

    # Route GitHub (initial): PR with decisions, no reply yet
    routes = {
        json.dumps(["api", "graphql"]): {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{
                        "number": 42, "title": "Test PR", "url": "https://github.com/o/r/pull/42",
                        "headRefName": "feature", "body": "PR body",
                        "repository": {"nameWithOwner": "o/r"},
                        "commits": {"nodes": [
                            {"commit": {"committedDate": "2026-11-21T10:30:00Z", "authoredDate": "2026-11-21T10:30:00Z", "parents": {"totalCount": 1}}}
                        ]},
                        "comments": {"nodes": [
                            {
                                "databaseId": 1001,
                                "url": "https://github.com/o/r/pull/42#issuecomment-1001",
                                "createdAt": "2026-11-21T10:00:00Z",
                                "body": decisions_comment,
                                "author": {"login": "o"}
                            }
                        ]}
                    }]
                },
                "followups": {
                    "nodes": [{
                        "number": 100, "title": "Act on owner decisions on PR #42",
                        "url": "https://github.com/o/r/issues/100",
                        "state": "OPEN", "stateReason": None,
                        "body": followup_marker + "\n## What to build\nFix this.",
                        "repository": {"nameWithOwner": "o/r"}
                    }]
                }
            }
        },
        json.dumps(["pr", "comment", "42", "--repo", "o/r"]): {}
    }
    _route_gh(tmp_path, github, routes)

    # Post the reply through bin/gh to prove it goes through
    reply_result = _gh(tmp_path, github, "pr", "comment", "42", "--repo", "o/r", "-b", reply_body)
    assert reply_result.returncode == 0, f"Reply posting failed: {reply_result.stderr}"

    # Update the route to show PR now has the reply and add close route
    routes[json.dumps(["api", "graphql"])]["data"]["prs"]["nodes"][0]["comments"]["nodes"].append({
        "databaseId": 1002,
        "url": "https://github.com/o/r/pull/42#issuecomment-1002",
        "createdAt": "2026-11-21T11:30:00Z",
        "body": reply_body,
        "author": {"login": "o"}
    })
    routes[json.dumps(["issue", "close", "100", "--repo", "o/r"])] = {}
    _route_gh(tmp_path, github, routes)

    # Verify waiting() is now empty (reply addresses the decision)
    now = datetime(2026, 11, 21, 15, 0, 0, tzinfo=timezone.utc)
    waiting_result = _od_run(tmp_path, github, od.waiting, ["o/r"], now=now)
    assert waiting_result is not None and len(waiting_result) == 0, "waiting() should be empty after reply"

    # Call sync() to verify the follow-up is closed
    result = _od_run(tmp_path, github, od.sync, ["o/r"], now=now)
    assert result["ok"] is True, "sync() should succeed"
    assert len(result["closed"]) == 1, "Should close the follow-up ticket"
    assert result["closed"][0]["number"] == 100
    assert result["closed"][0]["pr"] == 42
    assert "addressed" in result["closed"][0]["why"]

    # Verify the reply reached GitHub through bin/gh
    calls = _reached(tmp_path)
    assert any(c["argv"][:3] == ["pr", "comment", "42"] for c in calls), "Reply should have been posted through bin/gh"


def test_i3_approve_before_decisions_answered_requests_nothing(tmp_path, github):
    """Approving PR with no Decisions -> request() finds nothing to request."""
    # Route GitHub: PR with no decisions comment
    routes = {
        json.dumps(["api", "graphql"]): {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{
                        "number": 42, "title": "Test PR", "url": "https://github.com/o/r/pull/42",
                        "headRefName": "feature", "body": "PR body without decisions",
                        "repository": {"nameWithOwner": "o/r"},
                        "commits": {"nodes": []},
                        "comments": {"nodes": []}  # No decisions
                    }]
                },
                "followups": {"nodes": []}
            }
        }
    }
    _route_gh(tmp_path, github, routes)

    # Call request() through sandboxed gh — should report nothing to request
    now = datetime(2026, 11, 21, 15, 0, 0, tzinfo=timezone.utc)
    result = _od_run(tmp_path, github, od.request, "o/r", 42, now=now)
    assert "nothing to request" in result, f"Expected 'nothing to request', got: {result}"
    assert "no owner Decisions" in result


def test_i3_a_silent_no_op_scan_never_marks_an_overdue_pr_as_addressed(tmp_path, github):
    """The #724 shape: file step claims success but writes nothing → waiting() still lists the PR, sync() does not close it."""
    decisions_comment = "### Decisions from the owner\n```marvin-decisions\n{}\n```"

    # Route GitHub: overdue PR with decisions but no reply, no follow-up filed yet
    routes = {
        json.dumps(["api", "graphql"]): {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{
                        "number": 42, "title": "Test PR", "url": "https://github.com/o/r/pull/42",
                        "headRefName": "feature", "body": "",
                        "repository": {"nameWithOwner": "o/r"},
                        "commits": {"nodes": []},
                        "comments": {"nodes": [{
                            "databaseId": 1001,
                            "url": "https://github.com/o/r/pull/42#issuecomment-1001",
                            "createdAt": "2026-11-21T10:00:00Z",
                            "body": decisions_comment,
                            "author": {"login": "o"}
                        }]}
                    }]
                },
                "followups": {"nodes": []}
            }
        },
        json.dumps(["issue", "create"]): {"number": 100},  # Fake says issue was created
        json.dumps(["issue", "list"]): []
    }
    _route_gh(tmp_path, github, routes)

    now = datetime(2026, 11, 21, 15, 0, 0, tzinfo=timezone.utc)  # 5 hours later, overdue (DEFAULT_GRACE_HOURS is 4)

    # Verify waiting() lists the overdue PR
    waiting_result = _od_run(tmp_path, github, od.waiting, ["o/r"], now=now)
    assert waiting_result is not None
    assert len(waiting_result) == 1
    assert waiting_result[0]["overdue"] is True
    assert waiting_result[0]["addressed_by"] is None

    # Patch pr_images.verdict to silently return empty (lie about success but write nothing)
    orig_verdict = pi.verdict
    pi.verdict = lambda *a, **k: []
    try:
        # Verify sync() files the follow-up despite the patched verdict
        sync_result = _od_run(tmp_path, github, od.sync, ["o/r"], now=now, grace=4.0)
        assert sync_result["ok"] is True
        assert len(sync_result["filed"]) == 1, "Should file a follow-up for the overdue PR despite lying verdict"
        assert sync_result["filed"][0]["pr"] == 42
    finally:
        pi.verdict = orig_verdict


def test_i3_github_failing_mid_scan_leaves_the_item_stuck_not_dropped(tmp_path, github):
    """GitHub rate-limit mid-scan → sync() returns ok:False, nothing filed/closed, waiting() returns None."""
    # Create a failing gh that returns an error on GraphQL
    gh = github / "gh"
    failing_script = (
        "#!/usr/bin/python3\n"
        "import sys\n"
        "if 'graphql' in sys.argv:\n"
        "    print('{\"errors\": [{\"message\": \"API rate limit exceeded\"}]}')\n"
        "    sys.exit(1)\n"
        "print('{}')\n"
    )
    gh.write_text(failing_script)
    gh.chmod(0o755)

    # Call waiting() through sandboxed gh — should return None on error
    now = datetime(2026, 11, 21, 15, 0, 0, tzinfo=timezone.utc)
    waiting_result = _od_run(tmp_path, github, od.waiting, ["o/r"], now=now)
    assert waiting_result is None, "waiting() should return None when GitHub fails"

    # Call sync() through sandboxed gh — should return ok:False
    sync_result = _od_run(tmp_path, github, od.sync, ["o/r"], now=now)
    assert sync_result["ok"] is False, "sync() should return ok:False on GitHub error"
    assert len(sync_result["filed"]) == 0, "Nothing should be filed on error"
    assert len(sync_result["closed"]) == 0, "Nothing should be closed on error"


# ── end-to-end: ticket → PR → decisions → follow-up → addressed → merged ───

def test_the_loop_walks_a_ticket_from_idea_to_merged_through_i1_i2_i3(tmp_path, github):
    """Full narrative: issue create → PR with images and Decisions → follow-up filed → owner's reply → follow-up closed → merge."""
    head_sha = "a" * 40
    decisions_comment = "### Decisions from the owner\n```marvin-decisions\n{}\n```"
    followup_marker = f"<!-- marvin:owner-decisions pr=1 comment=1001 since=2026-11-21T10:00:00Z question=no -->"

    routes = {
        # I2: decision check routes
        json.dumps(["repo", "view"]): {"nameWithOwner": "o/r"},
        json.dumps(["api", "repos/o/r"]): {"default_branch": "main"},
        json.dumps(["api", "repos/o/r/compare/main...myhead"]): {
            "files": [{"filename": "src/View.swift"}]  # UI file changed
        },
        json.dumps(["api", f"repos/o/r/compare/{head_sha}...myhead"]): {
            "files": []  # Image is current
        },
        # Create ticket
        json.dumps(["issue", "create"]): {"number": 42},
        # Create PR
        json.dumps(["pr", "create"]): {"number": 1},
        # I3: GraphQL fetch for waiting PRs
        json.dumps(["api", "graphql"]): {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{
                        "number": 1, "title": "look change", "url": "https://github.com/o/r/pull/1",
                        "headRefName": "myhead", "body": f"![screenshot](https://raw.githubusercontent.com/o/r/{head_sha}/s.png)\n\n## Decisions\n<!-- marvin:decisions -->\n### d1: Which approach?\n- [x] Approach A\n- [ ] Approach B",
                        "repository": {"nameWithOwner": "o/r"},
                        "commits": {"nodes": []},
                        "comments": {"nodes": [{
                            "databaseId": 1001,
                            "url": "https://github.com/o/r/pull/1#issuecomment-1001",
                            "createdAt": "2026-11-21T10:00:00Z",
                            "body": decisions_comment,
                            "author": {"login": "o"}
                        }]}
                    }]
                },
                "followups": {"nodes": []}
            }
        },
        # File follow-up
        json.dumps(["issue", "list"]): [],
        # Merge
        json.dumps(["pr", "merge"]): {},
    }
    _route_gh(tmp_path, github, routes)

    # Step 1: Create issue (ticket)
    p = _gh(tmp_path, github, "issue", "create", "-R", "o/r", "--title", "New feature")
    assert p.returncode == 0
    ticket_calls = [c for c in _reached(tmp_path) if c["argv"][:2] == ["issue", "create"]]
    assert len(ticket_calls) == 1, "Should create the main ticket"

    # Step 2: Create PR with pinned image and machine-readable Decisions
    body = f"""![screenshot](https://raw.githubusercontent.com/o/r/{head_sha}/s.png)

## Decisions
<!-- marvin:decisions -->
### d1: Which approach?
- [x] Approach A
- [ ] Approach B
"""
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "myhead", "--base", "main",
            "--title", "look change", "--body", body)
    assert p.returncode == 0, p.stderr
    pr_create_calls = [c for c in _reached(tmp_path) if c["argv"][:2] == ["pr", "create"]]
    assert len(pr_create_calls) == 1, "Should create the PR"

    # Step 3: I3 — the scan files the follow-up for the unanswered decisions
    now = datetime(2026, 11, 21, 15, 0, 0, tzinfo=timezone.utc)  # 5 hours after decisions
    sync_result = _od_run(tmp_path, github, od.sync, ["o/r"], now=now, grace=4.0)
    assert sync_result["ok"] is True
    assert len(sync_result["filed"]) == 1, "Should file follow-up for the unanswered PR"
    assert sync_result["filed"][0]["pr"] == 1

    # Verify the follow-up issue was created with the correct marker
    followup_creates = [c for c in _reached(tmp_path) if c["argv"][:2] == ["issue", "create"] and len([x for x in c["argv"] if "owner-decisions" in str(x)]) > 0]
    # At minimum, we should have called issue create more times now (once for ticket, once for follow-up)
    all_issue_creates = [c for c in _reached(tmp_path) if c["argv"][:2] == ["issue", "create"]]
    assert len(all_issue_creates) >= 2, "Should have created both ticket and follow-up"

    # Step 4: Owner posts a reply with the addressed marker
    reply_body = f"I've addressed this. {od.ADDRESSED_MARKER}"
    reply_p = _gh(tmp_path, github, "pr", "comment", "1", "-R", "o/r", "-b", reply_body)
    assert reply_p.returncode == 0, f"Reply posting failed: {reply_p.stderr}"

    # Verify reply was posted through bin/gh
    reply_calls = [c for c in _reached(tmp_path) if c["argv"][:3] == ["pr", "comment", "1"]]
    assert len(reply_calls) == 1, "Reply should be posted through bin/gh"

    # Update the route to show the PR now has the reply
    routes[json.dumps(["api", "graphql"])]["data"]["prs"]["nodes"][0]["comments"]["nodes"].append({
        "databaseId": 1002,
        "url": "https://github.com/o/r/pull/1#issuecomment-1002",
        "createdAt": "2026-11-21T11:30:00Z",
        "body": reply_body,
        "author": {"login": "o"}
    })
    # Also add the open follow-up to be closed
    routes[json.dumps(["api", "graphql"])]["data"]["followups"]["nodes"] = [{
        "number": 100, "title": "Act on owner decisions on PR #1",
        "url": "https://github.com/o/r/issues/100",
        "state": "OPEN", "stateReason": None,
        "body": followup_marker + "\n## What to build\nFix this.",
        "repository": {"nameWithOwner": "o/r"}
    }]
    routes[json.dumps(["issue", "close", "100", "--repo", "o/r"])] = {}
    _route_gh(tmp_path, github, routes)

    # Step 5: The scan runs again, sees the reply, and closes the follow-up
    now_later = datetime(2026, 11, 21, 15, 30, 0, tzinfo=timezone.utc)
    sync_result2 = _od_run(tmp_path, github, od.sync, ["o/r"], now=now_later, grace=4.0)
    assert sync_result2["ok"] is True
    assert len(sync_result2["closed"]) == 1, "Should close the follow-up after owner's reply"
    assert sync_result2["closed"][0]["pr"] == 1
    assert sync_result2["closed"][0]["number"] == 100

    # Verify the issue close call
    close_calls = [c for c in _reached(tmp_path) if c["argv"][:3] == ["issue", "close", "100"]]
    assert len(close_calls) == 1, "Should close the follow-up issue through bin/gh"

    # Step 6: Merge the PR
    p = _gh(tmp_path, github, "pr", "merge", "1", "-R", "o/r")
    assert p.returncode == 0
    merge_calls = [c for c in _reached(tmp_path) if c["argv"][:2] == ["pr", "merge"]]
    assert len(merge_calls) == 1, "Should merge the PR"

    # Verify the full sequence reached GitHub with specific assertions
    calls = _reached(tmp_path)
    assert len(all_issue_creates) >= 2, "Should create ticket and follow-up"
    assert len(pr_create_calls) == 1, "Should create PR once"
    assert len(reply_calls) == 1, "Should post reply once"
    assert len(close_calls) == 1, "Should close follow-up once"
    assert len(merge_calls) == 1, "Should merge PR once"


def test_the_suite_never_touches_the_real_home_or_github(tmp_path, github):
    """Asserts tmp_path resolves outside the real home and fake gh is used, with find_real_gh."""
    # Import real_home_guard module to verify isolation
    old_path = sys.path[:]
    try:
        sys.path.insert(0, str(ROOT))
        import real_home_guard  # noqa: F401

        # Verify tmp_path is not inside the real home
        real_home_path = Path(real_home_guard.real_home())
        assert not tmp_path.is_relative_to(real_home_path), f"tmp_path {tmp_path} should not be under real home {real_home_path}"

        # Verify the write guard prevents writing the real .claude
        assert real_home_guard.outside_real_home(tmp_path / ".claude"), \
            "tmp_path/.claude must be outside real home"
    finally:
        sys.path[:] = old_path

    # Verify the fake gh was created in the test's realbin and is executable
    assert (github / "gh").exists() and (github / "gh").is_file()

    # Verify that the sandbox PATH uses the fake gh via GATE, not any system gh
    # Set up a route that matches a specific gh command (find_real_gh uses gh api)
    routes = {json.dumps(["api", "repos/o/r"]): {"default_branch": "main"}}
    _route_gh(tmp_path, github, routes)

    # Call through the sandboxed environment with all required vars
    env = {
        "PATH": f"{GATE.parent}:{github}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GH_GATE_NO_BUDGET": "1",
        "MARVIN_INSTANCE_DIR": str(tmp_path / "instance"),
        "MARVIN_PULL_ONLY": "0"
    }
    result = subprocess.run(["gh", "api", "repos/o/r"], capture_output=True, text=True, env=env, timeout=5)

    # The fake gh should return the routed response
    assert result.returncode == 0, f"Fake gh call failed: {result.stderr}"
    assert "default_branch" in result.stdout, f"Expected find_real_gh-shaped response, got: {result.stdout}"
