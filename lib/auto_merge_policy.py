#!/usr/bin/env python3
"""auto_merge_policy.py — may this PR merge without Gil's Approve? Decided by what it touches (ADR 0064, #338).

Pure: the caller supplies the PR's changed files and the facts (trust ramp, render check, folder counts); this only
reads config/auto_merge.json. Verdict "auto" or "ask", always with readable reasons. Anything doubtful asks:

- one **core** file anywhere (the merge gate and auto-merge itself, hooks / settings / permissions, sync, secrets,
  deletion code, and this rules file) → ask; a rename counts both its old and new path
- a **dependency** manifest or lockfile → ask (outside code needs Gil's trust)
- a **UI** change → ask until its render check passed (#126)
- more than max_changed_lines → ask; an empty PR → ask
- a path that isn't plain (``..``, absolute, backslashes, empty segments, non-ASCII look-alikes) → ask
- a brand-new top-level folder is owned, at most new_top_level_per_week a week (more is sprawl) → ask past that
- a PR by a **ramp author** (``ramp_authors``: mac-mini-2012's bot account, ADR 0069 rule 5) → ask until that
  author's own trust ramp is open (5 clean approvals, trust_ramp.py); ``always_ask_authors`` → always ask. Trust is by
  author only: no label (``from-box``) is an input here
- finance-os → always ask; another project → its profile's ``auto_merge.core`` paths, and its trust ramp must be open
- a missing or corrupt rules file → ask for everything

Paths are compared case-insensitively: on macOS ``Config/Auto_Merge.json`` is the rules file.
"""
from __future__ import annotations
import fnmatch
import json
import re
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "auto_merge.json"
ASK_ALL = {"ask_all": True}
_LIST_KEYS = ("core", "ui", "dependencies")
_AUTHOR_KEYS = ("ramp_authors", "always_ask_authors")   # optional, but a list of logins when present


def _authors_ok(rules: dict) -> bool:
    return all(k not in rules or (isinstance(rules[k], list) and all(isinstance(a, str) for a in rules[k]))
               for k in _AUTHOR_KEYS)


def load_rules(path: Path = RULES_PATH) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return ASK_ALL
    if not isinstance(data, dict) or any(not isinstance(data.get(k), list) for k in _LIST_KEYS) \
            or not isinstance(data.get("max_changed_lines"), int) or not isinstance(data.get("new_top_level_per_week"), int) \
            or not _authors_ok(data):
        return ASK_ALL
    return data


def _plain(path: str) -> bool:
    return bool(path) and path.isascii() and not path.startswith("/") and "\\" not in path \
        and all(seg not in ("", ".", "..") for seg in path.split("/"))


def _matches(path: str, patterns) -> str | None:
    low = path.lower()
    for pat in patterns:
        p = pat.lower()
        if fnmatch.fnmatchcase(low, p) or (p.startswith("**/") and fnmatch.fnmatchcase(low, p[3:])) \
                or (p.endswith("/**") and (low == p[:-3] or low.startswith(p[:-2]))):
            return pat
    return None


def area(path: str, rules: dict, existing_top_level, extra_core=()) -> str:
    """core | dependency | ui | owned | new-top-level | odd"""
    if not _plain(path):
        return "odd"
    if _matches(path, [*rules.get("core", []), *extra_core]):
        return "core"
    if _matches(path, rules.get("dependencies", [])):
        return "dependency"
    if _matches(path, rules.get("ui", [])):
        return "ui"
    top = path.split("/")[0].lower()
    if "/" in path and top not in {t.lower() for t in existing_top_level}:
        return "new-top-level"
    return "owned"


def decide(repo: str, files: list[dict], rules: dict, *, existing_top_level, new_top_level_this_week: int,
           ramp_open: bool, render_check_passed: bool = False, profile: dict | None = None,
           author: str | None = None, author_ramp_open: bool = False, author_ramp_streak: int | None = None) -> dict:
    """`author` is the PR author's login: None when the caller has no author at all (no author rule applies), "" when
    the PR's author couldn't be read (asks whenever any author is on a ramp). `author_ramp_open` must be exactly True
    for a ramp author's PR to go on; `author_ramp_streak` only adds "3 of 5" to the reason."""
    reasons: list[str] = []
    if not rules.get("ask_all") and not _authors_ok(rules):
        return {"verdict": "ask", "reasons": ["the auto-merge rules' author lists are malformed, so everything waits"]}
    # ADR 0069 rule 5: PRs written on mac-mini-2012 (its own GitHub account) wait until that account earns trust.
    ramp = {a.lower() for a in rules.get("ramp_authors", [])}
    always = {a.lower() for a in rules.get("always_ask_authors", [])}
    who = author.strip().lower() if isinstance(author, str) else None
    if who == "" and (ramp or always):
        reasons.append("the PR's author couldn't be read, so it can't be told apart from the box's bot (ADR 0069)")
    elif who and who in always:
        reasons.append(f"{author.strip()} writes from mac-mini-2012, whose PRs always wait for Gil (ADR 0069)")
    elif who and who in ramp and author_ramp_open is not True:
        count = f", {author_ramp_streak} of 5" if isinstance(author_ramp_streak, int) and not isinstance(author_ramp_streak, bool) else ""
        reasons.append(f"{author.strip()} writes from mac-mini-2012; its PRs wait for Gil until 5 clean approvals "
                       f"(ADR 0069{count})")
    if rules.get("ask_all"):
        return {"verdict": "ask", "reasons": ["the auto-merge rules file is missing or unreadable, so everything waits"]}
    if not files:
        return {"verdict": "ask", "reasons": ["the PR changes no files"]}
    if repo in rules.get("always_ask_repos", []):
        return {"verdict": "ask", "reasons": [f"{repo.split('/')[-1]} always waits for Gil"]}
    home = repo == rules.get("home_repo")
    extra_core = []
    if not home:
        if not profile:
            return {"verdict": "ask", "reasons": [f"{repo} has no project profile, so nothing about it is trusted yet"]}
        extra_core = list((profile.get("auto_merge") or {}).get("core", []))
        if not ramp_open:
            reasons.append("this project's trust ramp isn't open yet (5 clean PRs Gil approved)")
    lines = sum(int(f.get("additions") or 0) + int(f.get("deletions") or 0) for f in files)
    if lines > rules["max_changed_lines"]:
        reasons.append(f"{lines} changed lines is over the {rules['max_changed_lines']}-line limit")
    new_tops: set[str] = set()
    for f in files:
        for path in {f.get("path") or "", *([f["previous_path"]] if f.get("previous_path") else [])}:
            a = area(path, rules, existing_top_level, extra_core)
            if a == "odd":
                reasons.append(f"'{path}' isn't a plain path (.., absolute, backslash, empty or non-ASCII)")
            elif a == "core":
                reasons.append(f"{path} is core (always waits for Gil)")
            elif a == "dependency":
                reasons.append(f"{path} adds or changes dependencies (outside code)")
            elif a == "ui" and not render_check_passed:
                reasons.append(f"{path} is a UI change and its render check hasn't passed (#126)")
            elif a == "new-top-level":
                new_tops.add(path.split("/")[0].lower())
    if new_tops and new_top_level_this_week + len(new_tops) > rules["new_top_level_per_week"]:
        reasons.append(f"new top-level folder(s) {', '.join(sorted(new_tops))} would make "
                       f"{new_top_level_this_week + len(new_tops)} this week (limit {rules['new_top_level_per_week']})")
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return {"verdict": "ask", "reasons": reasons}
    return {"verdict": "auto", "reasons": ["only owned areas, no dependencies, within size"]}
