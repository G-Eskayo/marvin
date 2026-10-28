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
import re

from evidence_capture import ui_files

SHOTS_START = "<!-- marvin:shots -->"
SHOTS_END = "<!-- /marvin:shots -->"

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']?([^\"'\s>]+)", re.I)
_RAW = re.compile(r"^https://raw\.githubusercontent\.com/[^/]+/[^/]+/([^/]+)/")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_FILE = re.compile(r"\.(png|jpe?g|gif|webp|mp4|mov)$", re.I)


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
    if re.match(r"^https://github\.com/[^/]+/[^/]+/(blob|raw)/", url):
        return "blob"
    raw = _RAW.match(url)
    if raw and not _FULL_SHA.match(raw.group(1)):
        return "branch"
    return None


def pinned_shas(urls) -> set[str]:
    """The commits the images are pinned to (raw-host links with a full SHA)."""
    return {m.group(1) for u in urls if (m := _RAW.match(u)) and _FULL_SHA.match(m.group(1))}


_WHY = {"relative": "a repo path, which doesn't show in a PR", "blob": "a blob/...?raw=true link, a 404 for private repos",
        "branch": "linked by branch name or short SHA, so it shows whatever is newest"}
_FIX = "Pin them with `pr-shots <images>` from the PR's worktree (it commits them and links each by full commit SHA)."


def _list(paths, n=3) -> str:
    return ", ".join(paths[:n]) + (f" and {len(paths) - n} more" if len(paths) > n else "")


def verdict(files, body, extra_patterns=(), changed_since=None) -> list[tuple[str, str]]:
    """Problems that keep a PR from opening or merging, as (code, plain message); [] when it may go ahead.
    `changed_since(sha)` lists files changed between that commit and the PR head, or None when it can't be told;
    without it, staleness isn't judged."""
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
    if changed_since:
        later = []
        for sha in pinned_shas(urls):
            since = changed_since(sha)
            if since is None:
                return []
            newer_ui = [f for f in ui_files(since, extra_patterns) if not _IMAGE_FILE.search(f)]
            if not newer_ui:
                return []  # the newest pinned commit already shows the current look
            later.append(newer_ui)
        if later:
            return [("STALE_UI_EVIDENCE", f"The images are older than later changes to how it looks ({_list(min(later, key=len))}). "
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


def ui_paths_for(repo: str | None, profiles_dir) -> list[str]:
    """The project's own UI paths (`evidence.ui_paths` in its profile), so an app whose views aren't named *View counts."""
    import json
    from pathlib import Path
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
