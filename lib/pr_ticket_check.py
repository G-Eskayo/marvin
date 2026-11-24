"""A PR names its ticket (marvin#1004, docs/agents/issue-tracker.md "A PR names its ticket").

An open PR says which ticket it is for in one of two ways, in its body:

  - "Closes #N" (or Fixes/Resolves, GitHub's closing words): the PR finishes the ticket; GitHub closes it on merge;
  - "Part of #N": the PR is a step (a mock-up, a stacked slice, a plan, docs); the ticket stays open.

Either takes `owner/repo#N` (or the issue's URL) for a ticket in another repo. Either way the ticket's board card shows
In review and the dashboard's parity check is satisfied. PRs opened by hand or by helpers wrote "for #235" or nothing,
so no board had a card for them (six such PRs on 2026-11-02). bin/gh is the place every chat and agent write passes,
so it refuses `pr create` and `pr edit --body*` when the new body names no ticket either way: PR_NAMES_NO_TICKET.

Only repos with a MARVIN board (an onboarded project, ~/.claude/boards/registry.json) are checked; any other repo,
or one we can't tell, passes. The dashboard's parser is dashboard/electron/main/ticket_refs.js; this is the same rule
in Python (bin/gh must not need node for it), and both run dashboard/test/fixtures/pr_ticket_refs_cases.json.
MARVIN_NO_TICKET="<reason>" lets one call through, logged. Stdlib only: bin/gh imports it on every call.

marvin#1147: a PR that is part of a red ticket prints a warning (not a refusal). Red tickets: label main-red, or bug+p0
titled "Main red".
"""
from __future__ import annotations
import json
import os
import re
import subprocess
from pathlib import Path

import decisions_check

OVERRIDE = "MARVIN_NO_TICKET"
REGISTRY_PATH = Path.home() / ".claude" / "boards" / "registry.json"
RULE_DOC = "docs/agents/issue-tracker.md"
MAX_PART_OF_LOOKUPS = 10

_REF = r"(?:https?://github\.com/[\w.-]+/[\w.-]+/issues/\d+|(?:[\w.-]+/[\w.-]+)?#\d+)(?![\w-])"
_CLOSES = re.compile(rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+({_REF})", re.I | re.A)
_PART_OF = re.compile(rf"\bpart of:?\s+({_REF}(?:\s*(?:,|&|\band\b)\s*{_REF})*)", re.I | re.A)
_BLOCKED_BY = re.compile(rf"\bblocked by:?\s+({_REF}(?:\s*(?:,|&|\band\b)\s*{_REF})*)", re.I | re.A)
_DUPLICATE_OF = re.compile(rf"\bduplicate of:?\s+({_REF}(?:\s*(?:,|&|\band\b)\s*{_REF})*)", re.I | re.A)
_COVERED_BY = re.compile(rf"\bcovered by:?\s+({_REF}(?:\s*(?:,|&|\band\b)\s*{_REF})*)", re.I | re.A)
_SUPERSEDES = re.compile(rf"\bsupersedes:?\s+({_REF}(?:\s*(?:,|&|\band\b)\s*{_REF})*)", re.I | re.A)
_RELATED_TO = re.compile(rf"\brelated to:?\s+({_REF}(?:\s*(?:,|&|\band\b)\s*{_REF})*)", re.I | re.A)
_ONE_REF = re.compile(_REF, re.A)
_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)", re.A)
_CODE = [re.compile(r"```[\s\S]*?```"), re.compile(r"~~~[\s\S]*?~~~"), re.compile(r"`[^`\n]*`")]
_REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", re.A)
_PR_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/\d+", re.A)
FIX_TITLE = re.compile(r"\bmain\s+(?:is\s+)?red\b", re.I | re.A)


def _strip_code(text: str) -> str:
    for rx in _CODE:
        text = rx.sub(" ", text)
    return text


def _parse_ref(text: str, pr_repo: str | None) -> tuple[str | None, int]:
    url = _URL.search(text)
    if url:
        return url.group(1), int(url.group(2))
    repo, _, n = text.partition("#")
    return (repo or pr_repo), int(n)


def ticket_refs(body: str | None, pr_repo: str | None) -> list[tuple[str | None, int, str]]:
    """[(repo, number, 'closes' | 'part-of' | 'blocked-by' | 'duplicate-of' | 'covered-by' | 'supersedes' | 'related-to')] in the order written; closes > part-of > others."""
    text = _strip_code(body or "")
    hits = [(m.start(), [m.group(1)], "closes") for m in _CLOSES.finditer(text)]
    hits += [(m.start(), _ONE_REF.findall(m.group(1)), "part-of") for m in _PART_OF.finditer(text)]
    hits += [(m.start(), _ONE_REF.findall(m.group(1)), "blocked-by") for m in _BLOCKED_BY.finditer(text)]
    hits += [(m.start(), _ONE_REF.findall(m.group(1)), "duplicate-of") for m in _DUPLICATE_OF.finditer(text)]
    hits += [(m.start(), _ONE_REF.findall(m.group(1)), "covered-by") for m in _COVERED_BY.finditer(text)]
    hits += [(m.start(), _ONE_REF.findall(m.group(1)), "supersedes") for m in _SUPERSEDES.finditer(text)]
    hits += [(m.start(), _ONE_REF.findall(m.group(1)), "related-to") for m in _RELATED_TO.finditer(text)]
    found: dict[str, list] = {}
    relation_rank = {"closes": 2, "part-of": 1}
    for _at, refs, relation in sorted(hits, key=lambda h: h[0]):
        for r in refs:
            repo, n = _parse_ref(r, pr_repo)
            key = f"{str(repo).lower()}#{n}"
            if key not in found:
                found[key] = [repo, n, relation]
            elif relation_rank.get(relation, 0) > relation_rank.get(found[key][2], 0):
                found[key][2] = relation
    return [tuple(v) for v in found.values()]


def is_red_ticket(issue: dict | None) -> bool:
    """True when issue says main is red: label main-red, or bug+p0 titled 'Main red'. False if closed."""
    if not issue or not isinstance(issue, dict):
        return False
    state = (issue.get("state") or "").upper()
    if state == "CLOSED":
        return False
    labels = issue.get("labels") or []
    if isinstance(labels, list):
        label_names = set()
        for label in labels:
            if isinstance(label, dict):
                label_names.add((label.get("name") or "").lower())
            elif isinstance(label, str):
                label_names.add(label.lower())
    else:
        return False
    if "main-red" in label_names:
        return True
    if "bug" in label_names and "priority:p0" in label_names:
        title = issue.get("title") or ""
        return bool(FIX_TITLE.search(title))
    return False


def refusal(body: str | None) -> str | None:
    """The refusal message for a PR body that names no ticket either way, else None."""
    refs = ticket_refs(body, None)
    if any(r[2] in ('closes', 'part-of') for r in refs):
        return None
    return ("PR_NAMES_NO_TICKET: this PR's body doesn't name its ticket, so no board shows it and the dashboard's "
            "parity check flags it. Add one line to the body: \"Closes #N\" if this PR finishes the ticket, or "
            "\"Part of #N\" if it is a step (a mock-up, a stacked slice, a plan, docs). Use owner/repo#N for a ticket "
            f"in another repo. \"for #N\" or a bare \"#N\" doesn't count ({RULE_DOC}).")


def red_ticket_warning(body: str | None, repo: str | None, ask) -> str | None:
    """A warning message if this PR is part of a red ticket, else None. `ask(args)` runs gh and returns JSON.
    Returns None on any failure (fails open) or if nothing's red."""
    if not ask or not repo or not body:
        return None
    try:
        refs = ticket_refs(body, repo)
        part_of_refs = [(r, n) for r, n, rel in refs if rel == "part-of"]
        for idx, (target_repo, number) in enumerate(part_of_refs):
            if idx >= MAX_PART_OF_LOOKUPS:
                break
            try:
                issue = ask(["issue", "view", str(number), "--repo", target_repo or repo, "--json", "labels,title,state"])
                if is_red_ticket(issue):
                    return (f"warning: this PR is part of a red ticket (#{number}). "
                            f"Main merges are blocked until it is fixed.")
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return None


def pr_call(argv) -> dict | None:
    """{cmd, body, body_file, repo, target} for `pr create` / `pr edit` with a new body, else None."""
    if len(argv) < 2 or argv[0] != "pr" or argv[1] not in ("create", "edit"):
        return None
    call = decisions_check.body_call(argv)
    if not call:
        return None
    repo = target = None
    rest = list(argv[2:])
    i = 0
    while i < len(rest):
        flag, eq, value = rest[i].partition("=")
        if flag in ("--repo", "-R"):
            if not eq:
                i += 1
                value = rest[i] if i < len(rest) else None
            repo = value
        elif flag in decisions_check._VALUED or flag in decisions_check._BODY:
            i += 0 if eq else 1
        elif not rest[i].startswith("-") and target is None and argv[1] == "edit":
            target = rest[i]
        i += 1
    if not repo and target:
        m = _PR_URL.search(target)
        repo = m.group(1) if m else None
    return {**call, "repo": repo, "target": target}


def repo_here(cwd: str | None = None) -> str | None:
    """owner/repo of this checkout's origin on GitHub, from git alone (no GitHub call), else None."""
    try:
        p = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=cwd, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    m = _REMOTE.search(p.stdout.strip()) if p.returncode == 0 else None
    return m.group(1) if m else None


def onboarded(repo: str | None, registry: Path = REGISTRY_PATH) -> bool:
    """True when repo has a MARVIN board. No repo, no registry or an unreadable one: False (the rule is skipped)."""
    if not repo:
        return False
    import stamped
    boards = (stamped.read(Path(registry)).value or {}).get("boards")
    if not isinstance(boards, list):
        return False
    want = repo.lower()
    return any(isinstance(b, dict) and str(b.get("repo", "")).lower() == want for b in boards)


def gate(argv, say, log, env=None, read_file=None, registry: Path | None = None, here=repo_here, ask=None) -> int | None:
    """What bin/gh calls: 1 (refused, said why) or None (go on). `log(entry)` records overrides and refusals.
    `ask(args)` runs gh with JSON output for red ticket checks."""
    env = os.environ if env is None else env
    call = pr_call(argv)
    if not call:
        return None
    repo = call["repo"] or here()
    if not onboarded(repo, registry or REGISTRY_PATH):
        return None
    override = (env.get(OVERRIDE) or "").strip()
    if override:
        log({"cmd": call["cmd"], "repo": repo, "no_ticket_override": override[:200]})
        return None
    if call["body_file"] and call["body"] is None:
        try:
            body = (read_file or (lambda f: Path(f).read_text()))(call["body_file"])
        except OSError:
            return None  # gh says the file is missing, in its own words
    else:
        body = call["body"]
    msg = refusal(body)
    if msg:
        say(msg)
        say(f'(only if a person agrees this PR is for no ticket: {OVERRIDE}="<reason>" gh ...)')
        log({"cmd": call["cmd"], "repo": repo, "rc": 1, "no_ticket": msg[:200]})
        return 1
    warn = red_ticket_warning(body, repo, ask)
    if warn:
        say(warn)
        log({"cmd": call["cmd"], "repo": repo, "red_ticket_warning": warn[:200]})
    return None
