"""UI pull requests carry current, working images (marvin #735). Stdlib only: bin/gh imports it on every PR call.

The owner's hard rule (#374): a change to how something looks shows images before it merges. The pipeline captures
them and the dashboard's Approve checks for one, but a PR opened or merged from an interactive chat went straight
through bin/gh, and three kinds of slip kept reaching the owner: no images at all (screenshots taken but left in a
scratch folder), links that break (`blob/...?raw=true` is a 404 for a private repo in the dashboard), and old photos
(images linked by branch name, or pinned to a commit made before a later look change). This module is the pure part:
which images a body shows, which links break, and whether they're older than the last UI change. bin/gh asks GitHub
for the facts and refuses; bin/pr-shots pins images the one way that keeps working.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from evidence_capture import ui_files

SHOTS_START = "<!-- marvin:shots -->"
SHOTS_END = "<!-- /marvin:shots -->"

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']?([^\"'\s>]+)", re.I)
_RAW = re.compile(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_FILE = re.compile(r"\.(png|jpe?g|gif|webp|mp4|mov)$", re.I)
_GITHUB_BLOB = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/(blob|raw)/([0-9a-f]{40})/")
_GITHUB_UPLOAD = re.compile(r"^https://(?:github\.com/user-attachments/|[a-z-]*user-images\.githubusercontent\.com/)")


def image_urls(body) -> list[str]:
    """Every image the PR description shows, in order: markdown images and HTML <img>. A plain link isn't one."""
    if not isinstance(body, str):
        return []
    found = [(m.start(), m.group(1)) for m in _MD_IMAGE.finditer(body)]
    found += [(m.start(), m.group(1)) for m in _HTML_IMAGE.finditer(body)]
    return [url for _, url in sorted(found)]


def link_problem(url: str) -> str | None:
    """Why this image link breaks or goes stale, or None when it's pinned: "relative" (doesn't render in a PR),
    "blob" (github.com/.../blob/...?raw=true: a 404 for a private repo), "branch" (raw link to a branch or short SHA,
    so it shows whatever is newest, not what was reviewed)."""
    if not url.startswith(("http://", "https://")):
        return "relative"
    if _GITHUB_BLOB.match(url):
        return "blob"
    raw = _RAW.match(url)
    if raw and not _FULL_SHA.match(raw.group(3)):
        return "branch"
    return None


def pinned_shas(urls) -> set[str]:
    """The commits the images are pinned to (raw-host links with a full SHA)."""
    return {m.group(3) for u in urls if (m := _RAW.match(u)) and _FULL_SHA.match(m.group(3))}


def image_pins(body: str) -> list[dict]:
    """Image repos and commits: {repo: "owner/repo", sha: "40-hex"} for each pinned image.
    Captures owner/repo from raw.githubusercontent.com or github.com blob/raw links."""
    seen = {}
    for u in image_urls(body):
        raw = _RAW.match(u)
        if raw and _FULL_SHA.match(raw.group(3)):
            key = f"{raw.group(1)}/{raw.group(2)}@{raw.group(3)}"
            seen[key] = {"repo": f"{raw.group(1)}/{raw.group(2)}", "sha": raw.group(3)}
            continue
        blob = _GITHUB_BLOB.match(u)
        if blob:
            key = f"{blob.group(1)}/{blob.group(2)}@{blob.group(4)}"
            seen[key] = {"repo": f"{blob.group(1)}/{blob.group(2)}", "sha": blob.group(4)}
    return list(seen.values())


_WHY = {"relative": "a repo path, which doesn't show in a PR", "blob": "a blob/...?raw=true link, a 404 for private repos",
        "branch": "linked by branch name or short SHA, so it shows whatever is newest"}
_FIX = "Pin them with `pr-shots <images>` from the PR's worktree (it commits them and links each by full commit SHA)."


def _list(paths, n=3) -> str:
    return ", ".join(paths[:n]) + (f" and {len(paths) - n} more" if len(paths) > n else "")


def verdict(files, body, extra_patterns=(), changed_since=None, pr_repo=None, pr_head=None) -> list[tuple[str, str]]:
    """Problems that keep a PR from opening or merging, as (code, plain message); [] when it may go ahead.
    `changed_since(repo, sha)` lists files changed between that commit and the PR head (or since in cross-repo case),
    or None when it can't be told. Returns STALENESS_UNCHECKED if staleness can't be judged but wasn't explicitly waived.
    Without `changed_since`, staleness isn't judged at all (returns [])."""
    ui = ui_files(files, extra_patterns)
    if not ui:
        return []
    urls = image_urls(body)
    if not urls:
        return [("NO_UI_EVIDENCE", f"This PR changes how something looks ({_list(ui)}) but shows no images. {_FIX}")]
    bad = [(u, p) for u in urls if (p := link_problem(u))]
    if bad:
        lines = "; ".join(f"{u} is {_WHY[p]}" for u, p in bad[:3])
        return [("BAD_IMAGE_LINK", f"Some images won't show or will go stale: {lines}. {_FIX}")]

    if not changed_since:
        return []

    # Check staleness: compare each pinned image's commit to the PR head
    pr_files = set(files) if files else set()
    for pin in image_pins(body):
        if pin["sha"] == pr_head:
            continue  # images pinned to the PR's head are current
        try:
            since = changed_since(pin["repo"], pin["sha"])
        except Exception:
            return [("STALENESS_UNCHECKED", f"Couldn't check whether the images (pinned to {pin['sha'][:7]} in {pin['repo']}) "
                     f"are current. Retake them and re-pin, then try again: {_FIX}")]

        if since is None:
            # changed_since can't tell (GitHub unreachable, etc)
            return [("STALENESS_UNCHECKED", f"Couldn't check whether the images (pinned to {pin['sha'][:7]}) "
                     f"are current. Retake them and re-pin, then try again: {_FIX}")]

        # Only the PR's own files count toward staleness, not main's files from a rebase/merge (marvin#971)
        newer_ui = [f for f in ui_files([s for s in since if s in pr_files], extra_patterns)
                    if not _IMAGE_FILE.search(f)]
        if newer_ui:
            return [("STALE_UI_EVIDENCE", f"The images are older than later changes to how it looks ({_list(newer_ui)}). "
                     f"Retake them and re-pin: {_FIX}")]

    return []


# ── which gh calls are checked ──────────────────────────────────────────────

_VALUE_FLAGS = {"-R": "repo", "--repo": "repo", "-B": "base", "--base": "base", "-H": "head", "--head": "head",
                "-b": "body", "--body": "body", "-F": "body_file", "--body-file": "body_file"}
_OTHER_VALUE_FLAGS = {"-t", "--title", "-a", "--assignee", "-l", "--label", "-m", "--milestone", "-p", "--project",
                      "-r", "--reviewer", "-T", "--template", "--subject", "--author-email", "--match-head-commit",
                      "-A", "--auth"}


def parse_pr_call(argv) -> dict | None:
    """The PR facts in `gh pr create|ready|merge ...`, or None for any call the gate doesn't check."""
    if len(argv) < 2 or argv[0] != "pr" or argv[1] not in ("create", "ready", "merge"):
        return None
    if "--help" in argv or "-h" in argv:
        return None
    call = {"action": argv[1], "repo": None, "base": None, "head": None, "body": None, "body_file": None, "target": None}
    rest = list(argv[2:])
    i = 0
    while i < len(rest):
        a = rest[i]
        flag, eq, value = a.partition("=")
        if flag in _VALUE_FLAGS:
            if not eq:
                i += 1
                value = rest[i] if i < len(rest) else None
            call[_VALUE_FLAGS[flag]] = value
        elif flag in _OTHER_VALUE_FLAGS and not eq:
            i += 1
        elif not a.startswith("-") and call["target"] is None:
            call["target"] = a
        i += 1
    return call


def with_shots_section(body: str, section: str) -> str:
    """The PR body with its screenshots section set to `section`: replaced in place, else put before the Decisions
    (so the owner sees the pictures before he's asked to choose), else at the end."""
    block = f"{SHOTS_START}\n{section.strip()}\n{SHOTS_END}"
    body = body or ""
    start, end = body.find(SHOTS_START), body.find(SHOTS_END)
    if start != -1 and end != -1:
        return body[:start] + block + body[end + len(SHOTS_END):]
    at = body.find("## Decisions")
    if at != -1:
        return body[:at] + block + "\n\n" + body[at:]
    return (body.rstrip() + "\n\n" + block).lstrip() if body.strip() else block


def _parse_pr_url(pr_url: str) -> tuple[str, str, int] | None:
    """Extract owner, repo, and PR number from a GitHub PR URL."""
    try:
        p = urlparse(pr_url)
        if p.hostname != "github.com":
            return None
        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 4 and parts[2] == "pull" and parts[3].isdigit():
            return (parts[0], parts[1], int(parts[3]))
    except Exception:
        pass
    return None


def pr_facts_and_verdict(pr_url: str, ask, extra_patterns=(), read_stdin=None) -> list[tuple[str, str]]:
    """Fetch PR facts from GitHub and return verdict. `ask(args) -> dict` is a callable that runs
    `gh` with the given args and returns parsed JSON. Returns a list of (code, message) tuples."""
    parsed = _parse_pr_url(pr_url)
    if not parsed:
        return [("INVALID_PR_URL", f"PR URL doesn't parse: {pr_url}")]
    owner, repo, number = parsed
    pr_repo = f"{owner}/{repo}"

    try:
        # Fetch PR facts
        pr = ask(["pr", "view", str(number), "--repo", pr_repo, "--json", "files,body,headRefOid"])
        files = [f["path"] for f in pr.get("files", [])] if pr.get("files") else []
        body = pr.get("body") or ""
        head_ref = pr.get("headRefOid")
    except Exception as e:
        return [("PR_FETCH_FAILED", f"Couldn't fetch PR #{number}: {str(e)[:200]}")]

    # Build changed_since for staleness checks
    def changed_since(img_repo: str, img_sha: str) -> list[str] | None:
        try:
            if img_repo == pr_repo:
                # Same repo: compare commits
                result = ask(["api", f"repos/{pr_repo}/compare/{img_sha}...{head_ref}"])
                return [f["filename"] for f in result.get("files", [])]
            else:
                # Cross-repo: compare by commit time (marvin#773)
                # Get the image's commit time
                img_commit = ask(["api", f"repos/{img_repo}/commits/{img_sha}"])
                img_time = img_commit.get("commit", {}).get("committer", {}).get("date")
                if not img_time:
                    return None

                # Find which PR commits are <= that time
                pr_commits = ask(["api", "--paginate", f"repos/{pr_repo}/pulls/{number}/commits?per_page=100"])
                if not isinstance(pr_commits, list):
                    return None

                matching = [c for c in pr_commits
                           if c.get("commit", {}).get("committer", {}).get("date") and
                              c.get("commit", {}).get("committer", {}).get("date") <= img_time]
                if not matching:
                    # Images are older than the whole PR
                    return files

                # Compare the last matching commit to head
                last_sha = matching[-1].get("sha")
                if not last_sha or last_sha == head_ref:
                    return []

                result = ask(["api", f"repos/{pr_repo}/compare/{last_sha}...{head_ref}"])
                return [f["filename"] for f in result.get("files", [])]
        except Exception:
            return None

    return verdict(files, body, extra_patterns, changed_since, pr_repo, head_ref)


def ui_paths_for(repo: str | None, profiles_dir) -> list[str]:
    """The project's own UI paths (`evidence.ui_paths` in its profile), so an app whose views aren't named *View counts."""
    d = Path(profiles_dir)
    if not repo or not d.is_dir():
        return []
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("repo") == repo:
            paths = (data.get("evidence") or {}).get("ui_paths") or []
            return [p for p in paths if isinstance(p, str) and p]
    return []


# ── CLI entry points ────────────────────────────────────────────────────────

def _gh_json(args: list[str]) -> dict:
    """Run gh and return parsed JSON output."""
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip().splitlines()[-1:][0] or "gh failed")
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh call timed out")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"gh returned invalid JSON: {e}")


def _cli_check(args: list[str]) -> int:
    """CLI: pr_images.py check <pr-url> [extra-pattern ...] — full verdict with staleness."""
    if len(args) < 1:
        print(json.dumps({"problems": [{"code": "INVALID_ARGS", "message": "usage: check <pr-url> [extra-pattern ...]"}]}))
        return 1

    pr_url = args[0]
    extra_patterns = args[1:] if len(args) > 1 else []

    try:
        problems = pr_facts_and_verdict(pr_url, _gh_json, extra_patterns)
        print(json.dumps({"problems": [{"code": code, "message": msg} for code, msg in problems]}))
        return 0 if not problems else 1
    except Exception as e:
        print(json.dumps({"problems": [{"code": "CHECK_FAILED", "message": str(e)[:200]}]}), file=sys.stderr)
        return 2


def _cli_check_local(args: list[str]) -> int:
    """CLI: pr_images.py check-local [--files <json-array>] [--body <text>] [extra-pattern ...]
    Check verdict without GitHub calls, using already-known PR facts."""
    files = []
    body = ""
    extra_patterns = []
    i = 0

    while i < len(args):
        if args[i] == "--files" and i + 1 < len(args):
            try:
                files = json.loads(args[i + 1])
                if not isinstance(files, list):
                    files = []
            except (ValueError, json.JSONDecodeError):
                pass
            i += 2
        elif args[i] == "--body" and i + 1 < len(args):
            body = args[i + 1]
            i += 2
        elif not args[i].startswith("--"):
            extra_patterns.append(args[i])
            i += 1
        else:
            i += 1

    try:
        # No staleness check in local mode (no GitHub calls)
        problems = verdict(files, body, extra_patterns)
        print(json.dumps({"problems": [{"code": code, "message": msg} for code, msg in problems]}))
        return 0 if not problems else 1
    except Exception as e:
        print(json.dumps({"problems": [{"code": "CHECK_LOCAL_FAILED", "message": str(e)[:200]}]}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} check <pr-url> [extra-pattern ...] | check-local [--files <json>] [--body <text>]", file=sys.stderr)
        sys.exit(2)

    command = sys.argv[1]
    if command == "check":
        sys.exit(_cli_check(sys.argv[2:]))
    elif command == "check-local":
        sys.exit(_cli_check_local(sys.argv[2:]))
    else:
        print(f"unknown command: {command}", file=sys.stderr)
        sys.exit(2)
