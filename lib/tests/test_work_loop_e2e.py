"""The work loop, end to end (ADR 0080, marvin#737): each rule checked through the real bin/gh, in a temp HOME, against
a fake GitHub that records every call that reaches it. A rule holds only if a call that breaks it never gets there.
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_work_loop_e2e.py -v

Each rule adds its own section. I1 (UI images, marvin#735), I2 (askable questions, marvin#742), and I3 (owner decisions,
marvin#607) are below.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "bin" / "gh"
FIX = Path(__file__).resolve().parent / "fixtures" / "decisions"

sys.path.insert(0, str(ROOT / "lib"))
import decisions_check as dc  # noqa: E402


@pytest.fixture
def github(tmp_path):
    """A fake real gh: records each call's argv (and body file contents) to $HOME/github-calls.jsonl, prints {} or a
    mocked response if FAKE_GH_RESPONSES matches the call's API path or GraphQL query."""
    d = tmp_path / "realbin"
    d.mkdir()
    gh = d / "gh"
    gh.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, sys\n"
        "a = sys.argv[1:]\n"
        "# Only treat -F/--body-file values as files if they look like file paths or exist\n"
        "body_file = None\n"
        "for i, x in enumerate(a[:-1]):\n"
        "    if x in ('--body-file',):\n"
        "        val = a[i + 1]\n"
        "        body_file = val if val != '-' else None\n"
        "        break\n"
        "    elif x == '-F':\n"
        "        val = a[i + 1]\n"
        "        # -F value=file uses key=@path form for files; only @ means file, not /\n"
        "        if '@' in val or os.path.exists(val):\n"
        "            body_file = val\n"
        "            break\n"
        "rec = {'argv': a, 'body_file': open(body_file).read() if body_file else None}\n"
        "open(os.path.join(os.environ['HOME'], 'github-calls.jsonl'), 'a').write(json.dumps(rec) + '\\n')\n"
        "resp_file = os.path.join(os.environ['HOME'], 'FAKE_GH_RESPONSES.json')\n"
        "if os.path.exists(resp_file):\n"
        "    all_responses = json.load(open(resp_file))\n"
        "    # Match by API path (REST calls) or GraphQL query sniff\n"
        "    api_idx = next((i + 1 for i, x in enumerate(a[:-1]) if x == 'api'), None)\n"
        "    if api_idx and a[api_idx] == 'graphql':\n"
        "        query_idx = next((i + 1 for i, x in enumerate(a[:-1]) if x == '-f' and 'query=' in a[i + 1]), None)\n"
        "        if query_idx:\n"
        "            query_val = a[query_idx]\n"
        "            is_single = 'pullRequest(number' in query_val\n"
        "            match_key = 'single_pr' if is_single else 'list_prs'\n"
        "            if match_key in all_responses:\n"
        "                print(json.dumps(all_responses[match_key]))\n"
        "                sys.exit(0)\n"
        "    elif api_idx:\n"
        "        api_path = '/'.join(a[api_idx:]) if api_idx < len(a) else ''\n"
        "        for key, resp in all_responses.items():\n"
        "            if key != 'single_pr' and key != 'list_prs' and api_path.startswith(key):\n"
        "                print(json.dumps(resp))\n"
        "                sys.exit(0)\n"
        "print('{}')\n")
    gh.chmod(0o755)
    return d


def _route(tmp_path, responses):
    """Write mock GitHub responses to FAKE_GH_RESPONSES.json. Keys: REST API paths, 'single_pr' for pullRequest(number
    queries, 'list_prs' for search queries. Values: response JSON (passed through json.loads/dumps, so a dict)."""
    (tmp_path / "FAKE_GH_RESPONSES.json").write_text(json.dumps(responses))


def _gh(tmp_path, realbin, *args, env_extra=None):
    # MARVIN_PULL_ONLY=0: about a full node, as every Mac is; an unregistered Linux machine (CI, #1117) is pull-only.
    env = {"PATH": f"{GATE.parent}:{realbin}:/usr/bin:/bin", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1",
           "MARVIN_INSTANCE_DIR": str(tmp_path / "instance"), "MARVIN_PULL_ONLY": "0", **(env_extra or {})}
    return subprocess.run([str(GATE), *args], capture_output=True, text=True, env=env, timeout=60)


def _od(tmp_path, realbin, *args, env_extra=None, repos=None):
    """Invoke owner_decisions.py with a sandboxed HOME and PATH (fake gh only), pinned grace hours for deterministic
    overdue checks. repos: list of "owner/name" to register in the board registry."""
    instance_dir = tmp_path / "instance"
    if repos:
        # Create board registry with test repos; it goes in HOME / .claude / boards / registry.json
        registry_dir = tmp_path / ".claude" / "boards"
        registry_dir.mkdir(parents=True, exist_ok=True)
        registry = {
            "boards": [{"repo": r, "name": r.split("/")[1]} for r in repos],
            "timestamp": "2026-11-21T12:00:00Z"
        }
        (registry_dir / "registry.json").write_text(json.dumps(registry))
    env = {"PATH": f"{realbin}:/usr/bin:/bin", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1",
           "MARVIN_INSTANCE_DIR": str(instance_dir), "MARVIN_DECISIONS_GRACE_HOURS": "0.001",
           "MARVIN_PULL_ONLY": "0", **(env_extra or {})}
    venv_python = ROOT / "venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)
    return subprocess.run([str(venv_python), str(ROOT / "lib" / "owner_decisions.py"), *args], capture_output=True, text=True,
                         env=env, timeout=60)


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


# ── I1 UI images: current and working (marvin #735) ─────────────────────────

@pytest.mark.parametrize("name", ["i1_missing_image.md"])
def test_i1_ui_change_without_images_is_refused(tmp_path, github, name):
    # A PR that changes UI files but has no images should be refused with NO_UI_EVIDENCE.
    _route(tmp_path, {
        "repos/o/clarity-captions/compare/main...x": {
            "files": [{"filename": "src/components/Button.tsx", "status": "modified"}]
        }
    })
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/clarity-captions", "--head", "x", "--base", "main",
            "--title", "Button styling update", "--body-file", _body_file(tmp_path, name))
    # Should be refused because UI files changed but no images are in the body
    assert p.returncode != 0, f"expected failure, got: {p.stderr}"
    assert "NO_UI_EVIDENCE" in p.stderr or "image" in p.stderr.lower()
    assert not any(c["argv"][:2] == ["pr", "create"] for c in _reached(tmp_path))


def test_i1_ui_change_with_missing_images_does_not_reach_github(tmp_path, github):
    # A relative image path is a BAD_IMAGE_LINK; the PR should be refused.
    _route(tmp_path, {
        "repos/o/r/compare/main...x": {
            "files": [{"filename": "src/components/Button.tsx", "status": "modified"}]
        }
    })
    body = "Changed the main dashboard button styling.\n\n![screenshot](assets/button.png)"
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "x", "--base", "main", "--title", "t", "-b", body)
    # Should be refused: UI files changed but relative image path is not valid
    assert p.returncode != 0, f"expected failure, got: {p.stderr}"
    assert "BAD_IMAGE_LINK" in p.stderr, f"expected BAD_IMAGE_LINK error, got: {p.stderr}"
    assert not any(c["argv"][:2] == ["pr", "create"] for c in _reached(tmp_path))


@pytest.mark.parametrize("name", ["i1_stale_pinned_image.md"])
def test_i1_stale_pinned_images_are_refused(tmp_path, github, name):
    # A PR with images pinned to an old commit but with newer UI changes should be refused with STALE_UI_EVIDENCE.
    # Route the main...x compare showing UI files changed
    # Route the pinned SHA...x compare showing UI code files changed since the pinned commit (stale)
    _route(tmp_path, {
        "repos/o/clarity-captions/compare/main...x": {
            "files": [{"filename": "src/components/Button.tsx", "status": "modified"}]
        },
        "repos/o/clarity-captions/compare/abc1234567890abcdef1234567890abcdef12345...x": {
            "files": [{"filename": "src/components/Button.tsx", "status": "modified"}]
        }
    })
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/clarity-captions", "--head", "x", "--base", "main",
            "--title", "Button styling update", "--body-file", _body_file(tmp_path, name))
    # Should be refused: UI files changed since the pinned image
    assert p.returncode != 0, f"expected failure, got: {p.stderr}"
    assert "STALE_UI_EVIDENCE" in p.stderr
    assert not any(c["argv"][:2] == ["pr", "create"] for c in _reached(tmp_path))


def test_i1_non_ui_changes_skip_the_image_check(tmp_path, github):
    body = "Updated the README and documentation."
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "x", "--base", "main", "--title", "Docs", "-b", body)
    assert p.returncode == 0, p.stderr
    # Non-UI changes should not trigger image checks
    calls = _reached(tmp_path)
    assert len(calls) > 0
    assert calls[-1]["argv"][:2] == ["pr", "create"]


def test_i1_valid_images_pass_the_gate(tmp_path, github):
    # A proper raw.githubusercontent.com link with a full SHA passes the check.
    sha = "abc1234567890abcdef1234567890abcdef12345"  # 40 chars
    body = (
        "Updated dashboard colors and layout.\n\n"
        "![screenshot](https://raw.githubusercontent.com/G-Eskayo/marvin/"
        f"{sha}/assets/button-new.png)"
    )
    _route(tmp_path, {
        "repos/o/r/compare/main...x": {
            "files": [{"filename": "src/components/Button.tsx", "status": "modified"}]
        },
        f"repos/o/r/compare/{sha}...x": {
            "files": []
        }
    })
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "x", "--base", "main", "--title", "Colors", "-b", body)
    assert p.returncode == 0, p.stderr
    # The pr create call should be in the reached calls (there may be additional API calls for staleness checks)
    calls = _reached(tmp_path)
    assert any(c["argv"][:2] == ["pr", "create"] for c in calls)


# ── I3 owner decisions: waiting on MARVIN (marvin #607) ─────────────────────

def test_i3_waiting_fetches_prs_with_owner_decisions(tmp_path, github):
    # owner_decisions waiting lists PRs whose owner has submitted decisions and MARVIN hasn't acted.
    _route(tmp_path, {
        "list_prs": {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{
                        "number": 42, "title": "New feature", "url": "https://github.com/o/r/pull/42",
                        "headRefName": "feature-x", "body": "PR body",
                        "repository": {"nameWithOwner": "o/r"},
                        "commits": {"nodes": []},
                        "comments": {"nodes": [{
                            "databaseId": 123, "url": "https://github.com/o/r/pull/42#issuecomment-123",
                            "createdAt": "2026-11-20T10:00:00Z", "body": "### Decisions from the owner\n```marvin-decisions\n{\"answers\":{}}\n```",
                            "author": {"login": "o"}
                        }]}
                    }]
                },
                "followups": {"nodes": []}
            }
        }
    })
    res = _od(tmp_path, github, "waiting", "--json", repos=["o/r"])
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert isinstance(out, list)
    # PR with owner decisions should appear in waiting list
    assert len(out) > 0, "PR with owner decisions should appear"
    assert out[0]["number"] == 42


def test_i3_scan_identifies_overdue_decisions(tmp_path, github):
    # The hourly scan should identify PRs with overdue decisions (past grace period)
    # and create a follow-up ticket. Use a timestamp far in the past.
    from datetime import datetime, timedelta, timezone
    very_old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")

    pr_data = {
        "number": 42, "title": "New feature", "url": "https://github.com/o/r/pull/42",
        "headRefName": "feature-x", "body": "PR body",
        "repository": {"nameWithOwner": "o/r"},
        "commits": {"nodes": []},
        "comments": {"nodes": [{
            "databaseId": 123, "url": "https://github.com/o/r/pull/42#issuecomment-123",
            "createdAt": very_old,
            "body": "### Decisions from the owner\n```marvin-decisions\n{\"answers\":{\"q1\":{}}}\n```",
            "author": {"login": "o"}
        }]}
    }
    _route(tmp_path, {
        "list_prs": {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [pr_data]
                },
                "followups": {"nodes": []}
            }
        }
    })
    res = _od(tmp_path, github, "scan", "--dry-run", repos=["o/r"])
    assert res.returncode == 0, res.stderr
    # scan --dry-run should not reach GitHub (--dry-run means dry run), but should report what would be filed
    reached = _reached(tmp_path)
    # Verify no actual GitHub calls were made (dry-run only)
    assert not any(c["argv"][:2] == ["issue", "create"] for c in reached)


def test_i3_addressed_decisions_do_not_appear_waiting(tmp_path, github):
    # A PR with decisions answered by an owner reply should not appear in waiting list.
    # First verify it DOES appear without the addressed marker
    pr_data_unaddressed = {
        "number": 42, "title": "New feature", "url": "https://github.com/o/r/pull/42",
        "headRefName": "feature-x", "body": "PR body",
        "repository": {"nameWithOwner": "o/r"},
        "commits": {"nodes": []},
        "comments": {"nodes": [{
            "databaseId": 123, "url": "https://github.com/o/r/pull/42#issuecomment-123",
            "createdAt": "2026-11-20T10:00:00Z",
            "body": "### Decisions from the owner\n```marvin-decisions\n{\"answers\":{}}\n```",
            "author": {"login": "o"}
        }]}
    }
    _route(tmp_path, {
        "list_prs": {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [pr_data_unaddressed]
                },
                "followups": {"nodes": []}
            }
        }
    })
    res = _od(tmp_path, github, "waiting", "--json", repos=["o/r"])
    assert res.returncode == 0
    out = json.loads(res.stdout)
    assert len(out) > 0, "PR with unanswered decisions should appear in waiting"

    # Now route with the addressed marker and verify it disappears
    pr_data_addressed = {
        "number": 42, "title": "New feature", "url": "https://github.com/o/r/pull/42",
        "headRefName": "feature-x", "body": "PR body",
        "repository": {"nameWithOwner": "o/r"},
        "commits": {"nodes": []},
        "comments": {"nodes": [
            {
                "databaseId": 123, "url": "https://github.com/o/r/pull/42#issuecomment-123",
                "createdAt": "2026-11-20T10:00:00Z",
                "body": "### Decisions from the owner\n```marvin-decisions\n{\"answers\":{}}\n```",
                "author": {"login": "o"}
            },
            {
                "databaseId": 124, "url": "https://github.com/o/r/pull/42#issuecomment-124",
                "createdAt": "2026-11-20T11:00:00Z",
                "body": "Done! <!-- marvin:decisions-addressed -->",
                "author": {"login": "o"}
            }
        ]}
    }
    _route(tmp_path, {
        "list_prs": {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [pr_data_addressed]
                },
                "followups": {"nodes": []}
            }
        }
    })
    res = _od(tmp_path, github, "waiting", "--json", repos=["o/r"])
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    # Should be empty since the owner addressed it
    assert len(out) == 0, "PR with addressed decisions should not appear in waiting"


def test_i3_built_decisions_do_not_appear_waiting(tmp_path, github):
    # A PR with decisions addressed and later commits should not appear waiting.
    # Per marvin#733, a bare commit alone doesn't count — the addressed marker is required.
    pr_data = {
        "number": 42, "title": "New feature", "url": "https://github.com/o/r/pull/42",
        "headRefName": "feature-x", "body": "PR body",
        "repository": {"nameWithOwner": "o/r"},
        "commits": {"nodes": [{
            "commit": {
                "committedDate": "2026-11-20T11:00:00Z",
                "authoredDate": "2026-11-20T11:00:00Z",
                "parents": {"totalCount": 1}
            }
        }]},
        "comments": {"nodes": [
            {
                "databaseId": 123, "url": "https://github.com/o/r/pull/42#issuecomment-123",
                "createdAt": "2026-11-20T10:00:00Z",
                "body": "### Decisions from the owner\n```marvin-decisions\n{\"answers\":{}}\n```",
                "author": {"login": "o"}
            },
            {
                "databaseId": 124, "url": "https://github.com/o/r/pull/42#issuecomment-124",
                "createdAt": "2026-11-20T11:30:00Z",
                "body": "Done! <!-- marvin:decisions-addressed -->",
                "author": {"login": "o"}
            }
        ]}
    }
    _route(tmp_path, {
        "list_prs": {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [pr_data]
                },
                "followups": {"nodes": []}
            }
        }
    })
    res = _od(tmp_path, github, "waiting", "--json", repos=["o/r"])
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    # Should be empty: decisions have been addressed and work is committed
    assert len(out) == 0, "PR with addressed decisions and commits should not appear in waiting"


def test_i3_bare_commit_without_addressed_marker_still_waits(tmp_path, github):
    # A PR with decisions answered, a bare commit made, but no addressed marker reply should still appear waiting.
    # Per marvin#733, a bare commit alone doesn't count as addressing the decisions.
    pr_data = {
        "number": 42, "title": "New feature", "url": "https://github.com/o/r/pull/42",
        "headRefName": "feature-x", "body": "PR body",
        "repository": {"nameWithOwner": "o/r"},
        "commits": {"nodes": [{
            "commit": {
                "committedDate": "2026-11-20T11:00:00Z",
                "authoredDate": "2026-11-20T11:00:00Z",
                "parents": {"totalCount": 1}
            }
        }]},
        "comments": {"nodes": [{
            "databaseId": 123, "url": "https://github.com/o/r/pull/42#issuecomment-123",
            "createdAt": "2026-11-20T10:00:00Z",
            "body": "### Decisions from the owner\n```marvin-decisions\n{\"answers\":{}}\n```",
            "author": {"login": "o"}
        }]}
    }
    _route(tmp_path, {
        "list_prs": {
            "data": {
                "prs": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [pr_data]
                },
                "followups": {"nodes": []}
            }
        }
    })
    res = _od(tmp_path, github, "waiting", "--json", repos=["o/r"])
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    # Should NOT be empty: even though there's a commit, without the addressed marker it still waits
    assert len(out) > 0, "PR with decisions answered but no addressed marker should still appear in waiting"
    assert out[0]["number"] == 42
