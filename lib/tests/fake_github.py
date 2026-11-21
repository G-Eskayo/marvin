#!/usr/bin/env python3
"""Fake GitHub for testing the work loop (ADR 0080, marvin#737): a pure in-process GitHubState + subprocess dispatch.

Simulates: gh repo view, gh issue create/list/comment/close/edit, gh pr create/view/edit/ready/merge,
gh label create, gh api repos/{repo}, gh api repos/{repo}/compare/..., gh api graphql (owner_decisions queries).

FakeGitHub.run(argv, **subprocess_kwargs) mimics subprocess.run, reading/writing a JSON state file.
The subprocess entry point is a tiny shell shim that sets FAKE_GH_STATE and FAKE_GH_ACTOR env vars.

Usage:
    # In-process (preserves state across calls in memory):
    gh = FakeGitHub(state_file)
    result = gh.run(["issue", "create", ...])

    # Subprocess (each call gets fresh env, state persisted in file):
    env = {"PATH": f"{worktree}/lib/tests:{PATH}", ...}
    subprocess.run(["gh", "issue", "list"], env=env)
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


class GitHubState:
    """Mutable record of repos, issues, PRs, comments, labels, commits. Serializable to/from dict."""

    def __init__(self):
        self.repos = {}  # {repo_name: {owner, name, ...}}
        self.issues = {}  # {repo_name: {issue_number: {number, title, state, body, labels, ...}}}
        self.prs = {}  # {repo_name: {pr_number: {number, title, state, body, head_ref, base_ref, labels, ...}}}
        self.comments = {}  # {repo_name: {"issue:number" | "pr:number": [comment_dicts]}} - prefixed keys separate issue/PR namespaces
        self.labels = {}  # {repo_name: {label_name: {name, color, description}}}
        self.commits = {}  # {repo_name: [commit_dicts with message, files, author_date]}
        self.counter = 1000  # monotonic ID for comments and commits

    def _int_keys(self, d: dict) -> dict:
        """Convert string keys to ints (from JSON deserialization)."""
        result = {}
        for k, v in d.items():
            # Try to convert key to int
            try:
                int_key = int(k)
                result[int_key] = v
            except (ValueError, TypeError):
                result[k] = v
        return result

    def to_dict(self, fail_next: dict = None) -> dict:
        """Serialize to a dict for JSON."""
        return {
            "repos": self.repos,
            "issues": self.issues,
            "prs": self.prs,
            "comments": self.comments,
            "labels": self.labels,
            "commits": self.commits,
            "counter": self.counter,
            "fail_next": fail_next or {},
        }

    @classmethod
    def from_dict(cls, d: dict) -> tuple[GitHubState, dict]:
        """Deserialize from a dict. Returns (state, fail_next)."""
        s = cls()
        s.repos = d.get("repos", {})
        # Convert string keys to ints for issues, prs, comments (from JSON)
        issues_raw = d.get("issues", {})
        for repo, issue_dict in issues_raw.items():
            s.issues[repo] = s._int_keys(issue_dict)
        prs_raw = d.get("prs", {})
        for repo, pr_dict in prs_raw.items():
            s.prs[repo] = s._int_keys(pr_dict)
        comments_raw = d.get("comments", {})
        for repo, comment_dict in comments_raw.items():
            s.comments[repo] = comment_dict  # comments use string keys like "pr:1", no int conversion needed
        s.labels = d.get("labels", {})
        s.commits = d.get("commits", {})
        s.counter = d.get("counter", 1000)
        fail_next = d.get("fail_next", {})
        return s, fail_next


def dispatch(state: GitHubState, argv: list[str], actor: str, fail_next: dict = None) -> tuple[int, str, str]:
    """
    Pure dispatch: (rc, stdout_json_or_text, stderr).

    fail_next: a dict with optional keys:
      {match: str pattern to match in cmd, kind: str (rate_limit|server_error), times: int}

    Returns (0, json_str, "") on success, (rc, "", stderr) on GitHub error.
    """
    fail_next = fail_next or {}

    # Check if this call should fail
    cmd_str = " ".join(argv)
    if fail_next.get("match") and re.search(fail_next["match"], cmd_str):
        times = fail_next.get("times", 1)
        if times > 0:
            fail_next["times"] = times - 1
            kind = fail_next.get("kind", "rate_limit")
            if kind == "rate_limit":
                return (1, "", "HTTP 403: API rate limit exceeded for user ID 1.")
            elif kind == "server_error":
                return (1, "", "HTTP 500: Internal Server Error")
            elif kind == "burst":
                return (1, "", "You have exceeded a secondary rate limit. Please wait a few minutes before trying again.")
            # Unknown kind falls through to success (no error)

    if not argv:
        return (1, "", "usage: gh <command>")

    cmd = argv[0]

    # ── repo ────────────────────────────────────────────────────────────────
    if cmd == "repo" and len(argv) > 1:
        if argv[1] == "view":
            repo = _repo_from_argv(argv, 2)
            if not repo:
                return (1, "", f"flag provided but not defined: -R")
            owner, name = repo.split("/")
            if repo not in state.repos:
                return (1, "", f"repository not found")
            r = state.repos[repo]
            return (0, json.dumps({"owner": {"login": owner}, "name": name, "url": f"https://github.com/{repo}"}), "")

    # ── issue ───────────────────────────────────────────────────────────────
    if cmd == "issue":
        if len(argv) > 1:
            if argv[1] == "create":
                repo = _repo_from_argv(argv, 2)
                if not repo:
                    return (1, "", "flag provided but not defined: -R")
                title = _flag_value(argv, "--title", "-t")
                body = _flag_value(argv, "--body", "-b")
                body_file = _flag_value(argv, "--body-file", "-F")
                if body_file and body_file != "-":
                    try:
                        body = Path(body_file).read_text()
                    except Exception as e:
                        return (1, "", str(e))
                if not title:
                    return (1, "", "required flag --title not provided")

                _ensure_repo(state, repo)
                num = _next_issue_number(state, repo)
                issue = {
                    "number": num, "title": title, "body": body or "", "state": "open",
                    "labels": [], "created_at": _now(), "author": {"login": actor},
                    "url": f"https://github.com/{repo}/issues/{num}"
                }
                state.issues.setdefault(repo, {})[num] = issue
                return (0, json.dumps(issue), "")

            elif argv[1] == "view":
                if len(argv) < 3:
                    return (1, "", "issue number required")
                result = _parse_num(argv[2], "issue view", "issue_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                issue_num = result
                repo = _repo_from_argv(argv, 3) or "G-Eskayo/marvin"
                if repo not in state.issues or issue_num not in state.issues[repo]:
                    return (1, "", f"issue #{issue_num} not found")
                return (0, json.dumps(state.issues[repo][issue_num]), "")

            elif argv[1] == "list":
                repo = _repo_from_argv(argv, 2) or "G-Eskayo/marvin"
                state_arg = _flag_value(argv, "--state", "-S")
                issues = state.issues.get(repo, {}).values()
                if state_arg:
                    issues = [i for i in issues if i.get("state") == state_arg]
                return (0, json.dumps(list(issues)), "")

            elif argv[1] == "comment":
                if len(argv) < 3:
                    return (1, "", "issue number required")
                result = _parse_num(argv[2], "issue comment", "issue_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                issue_num = result
                repo = _repo_from_argv(argv, 3)
                if not repo:
                    return (1, "", "flag provided but not defined: -R")
                body = _flag_value(argv, "--body", "-b")
                body_file = _flag_value(argv, "--body-file", "-F")
                if body_file and body_file != "-":
                    try:
                        body = Path(body_file).read_text()
                    except Exception as e:
                        return (1, "", str(e))
                if not body:
                    return (1, "", "body required")

                if repo not in state.issues or issue_num not in state.issues[repo]:
                    return (1, "", f"issue #{issue_num} not found")

                _ensure_repo(state, repo)
                cid = state.counter
                state.counter += 1
                comment = {
                    "databaseId": cid, "body": body, "createdAt": _now(),
                    "author": {"login": actor}, "url": f"https://github.com/{repo}/issues/{issue_num}#issuecomment-{cid}"
                }
                state.comments.setdefault(repo, {}).setdefault(f"issue:{issue_num}", []).append(comment)
                return (0, json.dumps(comment), "")

            elif argv[1] == "close":
                if len(argv) < 3:
                    return (1, "", "issue number required")
                result = _parse_num(argv[2], "issue close", "issue_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                issue_num = result
                repo = _repo_from_argv(argv, 3) or "G-Eskayo/marvin"
                if repo not in state.issues or issue_num not in state.issues[repo]:
                    return (1, "", f"issue #{issue_num} not found")
                state.issues[repo][issue_num]["state"] = "closed"
                return (0, json.dumps({"state": "closed"}), "")

            elif argv[1] == "edit":
                if len(argv) < 3:
                    return (1, "", "issue number required")
                result = _parse_num(argv[2], "issue edit", "issue_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                issue_num = result
                repo = _repo_from_argv(argv, 3) or "G-Eskayo/marvin"
                body = _flag_value(argv, "--body", "-b")
                body_file = _flag_value(argv, "--body-file", "-F")
                if body_file and body_file != "-":
                    try:
                        body = Path(body_file).read_text()
                    except Exception as e:
                        return (1, "", str(e))

                if repo not in state.issues or issue_num not in state.issues[repo]:
                    return (1, "", f"issue #{issue_num} not found")
                if body is not None:
                    state.issues[repo][issue_num]["body"] = body
                return (0, json.dumps(state.issues[repo][issue_num]), "")

    # ── pr ──────────────────────────────────────────────────────────────────
    if cmd == "pr":
        if len(argv) > 1:
            if argv[1] == "create":
                repo = _repo_from_argv(argv, 2)
                if not repo:
                    return (1, "", "flag provided but not defined: -R")
                title = _flag_value(argv, "--title", "-t")
                body = _flag_value(argv, "--body", "-b")
                body_file = _flag_value(argv, "--body-file", "-F")
                if body_file and body_file != "-":
                    try:
                        body = Path(body_file).read_text()
                    except Exception as e:
                        return (1, "", str(e))
                head = _flag_value(argv, "--head")
                base = _flag_value(argv, "--base") or "main"

                _ensure_repo(state, repo)
                num = _next_pr_number(state, repo)
                pr = {
                    "number": num, "title": title or "", "body": body or "", "state": "open",
                    "headRefName": head or "feature", "baseRefName": base, "labels": [],
                    "created_at": _now(), "author": {"login": actor},
                    "url": f"https://github.com/{repo}/pull/{num}", "mergeable": True,
                    "commits": []
                }
                state.prs.setdefault(repo, {})[num] = pr
                return (0, json.dumps(pr), "")

            elif argv[1] == "view":
                if len(argv) < 3:
                    return (1, "", "PR number required")
                result = _parse_num(argv[2], "pr view", "pr_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                pr_num = result
                repo = _repo_from_argv(argv, 3) or "G-Eskayo/marvin"
                if repo not in state.prs or pr_num not in state.prs[repo]:
                    return (1, "", f"pull request not found")
                return (0, json.dumps(state.prs[repo][pr_num]), "")

            elif argv[1] == "edit":
                if len(argv) < 3:
                    return (1, "", "PR number required")
                result = _parse_num(argv[2], "pr edit", "pr_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                pr_num = result
                repo = _repo_from_argv(argv, 3) or "G-Eskayo/marvin"
                body = _flag_value(argv, "--body", "-b")
                body_file = _flag_value(argv, "--body-file", "-F")
                if body_file and body_file != "-":
                    try:
                        body = Path(body_file).read_text()
                    except Exception as e:
                        return (1, "", str(e))

                if repo not in state.prs or pr_num not in state.prs[repo]:
                    return (1, "", f"pull request not found")
                if body is not None:
                    state.prs[repo][pr_num]["body"] = body
                return (0, json.dumps(state.prs[repo][pr_num]), "")

            elif argv[1] == "ready":
                if len(argv) < 3:
                    return (1, "", "PR number required")
                result = _parse_num(argv[2], "pr ready", "pr_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                pr_num = result
                repo = _repo_from_argv(argv, 3) or "G-Eskayo/marvin"
                if repo not in state.prs or pr_num not in state.prs[repo]:
                    return (1, "", f"pull request not found")
                state.prs[repo][pr_num]["draft"] = False
                return (0, json.dumps({"state": "ready"}), "")

            elif argv[1] == "merge":
                if len(argv) < 3:
                    return (1, "", "PR number required")
                result = _parse_num(argv[2], "pr merge", "pr_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                pr_num = result
                repo = _repo_from_argv(argv, 3) or "G-Eskayo/marvin"
                if repo not in state.prs or pr_num not in state.prs[repo]:
                    return (1, "", f"pull request not found")
                pr = state.prs[repo][pr_num]
                if pr.get("state") != "open":
                    return (1, "", f"pull request is not open")
                pr["state"] = "merged"
                return (0, json.dumps({"state": "merged"}), "")

            elif argv[1] == "comment":
                if len(argv) < 3:
                    return (1, "", "PR number required")
                result = _parse_num(argv[2], "pr comment", "pr_num")
                if isinstance(result, tuple):
                    return (1, "", result[1])
                pr_num = result
                repo = _repo_from_argv(argv, 3) or "G-Eskayo/marvin"
                body = _flag_value(argv, "--body", "-b")
                body_file = _flag_value(argv, "--body-file", "-F")
                if body_file and body_file != "-":
                    try:
                        body = Path(body_file).read_text()
                    except Exception as e:
                        return (1, "", str(e))
                if not body:
                    return (1, "", "body required")

                # Check that the PR exists
                if repo not in state.prs or pr_num not in state.prs[repo]:
                    return (1, "", f"pull request not found")

                cid = state.counter
                state.counter += 1
                comment = {
                    "databaseId": cid, "body": body, "createdAt": _now(),
                    "author": {"login": actor}, "url": f"https://github.com/{repo}/pull/{pr_num}#issuecomment-{cid}"
                }
                state.comments.setdefault(repo, {}).setdefault(f"pr:{pr_num}", []).append(comment)
                return (0, json.dumps(comment), "")

    # ── label ───────────────────────────────────────────────────────────────
    if cmd == "label" and len(argv) > 1 and argv[1] == "create":
        repo = _repo_from_argv(argv, 2)
        if not repo:
            return (1, "", "flag provided but not defined: -R")
        name = _flag_value(argv, "--name", "-n")
        color = _flag_value(argv, "--color", "-c") or "000000"
        description = _flag_value(argv, "--description", "-d") or ""

        _ensure_repo(state, repo)
        state.labels.setdefault(repo, {})[name] = {"name": name, "color": color, "description": description}
        return (0, json.dumps({"name": name, "color": color}), "")

    # ── api ─────────────────────────────────────────────────────────────────
    if cmd == "api":
        if len(argv) < 2:
            return (1, "", "api path required")

        path = argv[1]

        # repos/{owner}/{repo}
        if path.startswith("repos/"):
            parts = path.split("/")
            if len(parts) >= 3:
                owner, name = parts[1], parts[2]
                repo = f"{owner}/{name}"
                if len(parts) == 3:
                    # repos/{owner}/{repo}
                    if repo not in state.repos:
                        return (1, "", f"repository not found")
                    return (0, json.dumps({"owner": {"login": owner}, "name": name}), "")
                elif len(parts) >= 5 and parts[3] == "compare":
                    # repos/{owner}/{repo}/compare/{base}...{head}
                    return (0, json.dumps({"status": "ahead", "ahead_by": 1, "behind_by": 0}), "")

        # graphql
        if path == "graphql":
            query_param = _flag_value(argv, "-f")
            if not query_param:
                return (1, "", "graphql: query required (-f)")
            # Check if this is a search-based query or single-PR query
            if "search(" in query_param or ("query=" in query_param and "is:open" in query_param):
                # owner_decisions queries - return actual PRs from state
                prs_nodes = []
                for repo, prs_dict in state.prs.items():
                    for pr_num, pr_data in prs_dict.items():
                        if pr_data.get("state") == "open":
                            owner, name = repo.split("/")
                            comments = state.comments.get(repo, {}).get(f"pr:{pr_num}", [])
                            prs_nodes.append({
                                "number": pr_num,
                                "title": pr_data.get("title", ""),
                                "url": pr_data.get("url", ""),
                                "headRefName": pr_data.get("headRefName", ""),
                                "body": pr_data.get("body", ""),
                                "repository": {"nameWithOwner": repo},
                                "commits": {"nodes": []},
                                "comments": {"nodes": comments}
                            })
                return (0, json.dumps({
                    "data": {
                        "prs": {"nodes": prs_nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}},
                        "followups": {"nodes": []},
                        "rateLimit": {"remaining": 5000, "resetAt": _future_iso()}
                    }
                }), "")
            elif "repository(" in query_param:
                # Single PR query (from fetch_pr)
                # For simplicity, return empty result for single PR queries in tests
                return (0, json.dumps({
                    "data": {
                        "repository": {
                            "pullRequest": None
                        }
                    }
                }), "")
            else:
                return (1, "", f"graphql: unsupported query")

        # rate_limit
        if path == "rate_limit":
            return (0, json.dumps({
                "resources": {"core": {"remaining": 5000}, "graphql": {"remaining": 5000}}
            }), "")

        return (1, "", f"api path not recognized: {path}")

    return (1, "", f"command not recognized: {cmd}")


class FakeGitHub:
    """In-process interface to GitHubState, with state file persistence."""

    def __init__(self, state_file: str | Path):
        self.state_file = Path(state_file)
        self.state = self._load_state()
        self._fail_next_state = {}

    def _load_state(self) -> GitHubState:
        """Load state from file, or empty state if file doesn't exist."""
        if self.state_file.exists():
            try:
                state, fail_next = GitHubState.from_dict(json.loads(self.state_file.read_text()))
                self._fail_next_state = fail_next
                return state
            except Exception:
                pass
        self._fail_next_state = {}
        return GitHubState()

    def _save_state(self) -> None:
        """Persist state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state.to_dict(fail_next=self._fail_next_state)))

    def run(self, argv: list[str], actor: str = "MARVIN", capture_output: bool = True, text: bool = True,
            **kwargs) -> SimpleNamespace:
        """
        Run a gh command. Returns a subprocess.CompletedProcess-like object.

        Args:
            argv: Command arguments (without "gh" prefix)
            actor: GitHub login to use for created comments/issues
            capture_output, text: Mimics subprocess.run

        Returns:
            SimpleNamespace with returncode, stdout, stderr
        """
        self.state = self._load_state()
        rc, stdout, stderr = dispatch(self.state, argv, actor, self._fail_next_state)
        self._save_state()
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)

    def fail_next(self, match: str = None, kind: str = "rate_limit", times: int = 1) -> None:
        """Set up the next call matching `match` to fail with `kind` error, up to `times` calls."""
        self._fail_next_state = {"match": match, "kind": kind, "times": times}
        self._save_state()  # Persist to file so subprocess calls see it


# ── Helpers ─────────────────────────────────────────────────────────────────

def _parse_num(arg: str, cmd: str, item_type: str) -> int | tuple[int, str]:
    """Parse a number, return the int or (None, error_msg) tuple."""
    try:
        return int(arg)
    except ValueError:
        return None, f"argument {item_type} of command {cmd}: not a valid integer"


def _now() -> str:
    """Current time in ISO format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _future_iso() -> str:
    """Future time for rate limit reset."""
    from datetime import timedelta
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    return future.isoformat().replace("+00:00", "Z")


def _ensure_repo(state: GitHubState, repo: str) -> None:
    """Ensure repo exists in state."""
    if repo not in state.repos:
        owner, name = repo.split("/")
        state.repos[repo] = {"owner": owner, "name": name, "url": f"https://github.com/{repo}"}


def _repo_from_argv(argv: list[str], start: int = 0) -> str | None:
    """Extract repo from -R flag."""
    for i in range(start, len(argv) - 1):
        if argv[i] in ("-R", "--repo"):
            return argv[i + 1]
    return None


def _flag_value(argv: list[str], long_flag: str, short_flag: str = None) -> str | None:
    """Extract flag value from argv."""
    for i, arg in enumerate(argv):
        if arg == long_flag or (short_flag and arg == short_flag):
            if "=" in arg:
                return arg.split("=", 1)[1]
            if i + 1 < len(argv):
                return argv[i + 1]
    for i, arg in enumerate(argv):
        if arg.startswith(long_flag + "="):
            return arg.split("=", 1)[1]
        if short_flag and arg.startswith(short_flag + "="):
            return arg.split("=", 1)[1]
    return None


def _next_issue_number(state: GitHubState, repo: str) -> int:
    """Next available issue number for this repo."""
    nums = state.issues.get(repo, {}).keys()
    return max(nums, default=0) + 1


def _next_pr_number(state: GitHubState, repo: str) -> int:
    """Next available PR number for this repo."""
    nums = state.prs.get(repo, {}).keys()
    return max(nums, default=0) + 1


# ── Subprocess entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    state_file = Path(os.environ.get("FAKE_GH_STATE", "/tmp/fake-github.json"))
    actor = os.environ.get("FAKE_GH_ACTOR", "MARVIN")
    if state_file.exists():
        state, fail_next = GitHubState.from_dict(json.loads(state_file.read_text()))
    else:
        state = GitHubState()
        fail_next = {}
    rc, stdout, stderr = dispatch(state, sys.argv[1:], actor, fail_next)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state.to_dict(fail_next=fail_next)))
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    sys.exit(rc)
