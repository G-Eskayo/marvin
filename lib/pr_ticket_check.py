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

_REF = r"(?:https?://github\.com/[\w.-]+/[\w.-]+/issues/\d+|(?:[\w.-]+/[\w.-]+)?#\d+)(?![\w-])"
_CLOSES = re.compile(rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+({_REF})", re.I | re.A)
_PART_OF = re.compile(rf"\bpart of:?\s+({_REF}(?:\s*(?:,|&|\band\b)\s*{_REF})*)", re.I | re.A)
_ONE_REF = re.compile(_REF, re.A)
_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)", re.A)
_CODE = [re.compile(r"```[\s\S]*?```"), re.compile(r"~~~[\s\S]*?~~~"), re.compile(r"`[^`\n]*`")]
_REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", re.A)
_PR_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/\d+", re.A)


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
    """[(repo, number, 'closes' | 'part-of')] in the order written; a ticket named both ways is 'closes'."""
    text = _strip_code(body or "")
    hits = [(m.start(), [m.group(1)], "closes") for m in _CLOSES.finditer(text)]
    hits += [(m.start(), _ONE_REF.findall(m.group(1)), "part-of") for m in _PART_OF.finditer(text)]
    found: dict[str, list] = {}
    for _at, refs, relation in sorted(hits, key=lambda h: h[0]):
        for r in refs:
            repo, n = _parse_ref(r, pr_repo)
            key = f"{str(repo).lower()}#{n}"
            if key not in found:
                found[key] = [repo, n, relation]
            elif relation == "closes":
                found[key][2] = "closes"
    return [tuple(v) for v in found.values()]


def refusal(body: str | None) -> str | None:
    """The refusal message for a PR body that names no ticket either way, else None."""
    if ticket_refs(body, None):
        return None
    return ("PR_NAMES_NO_TICKET: this PR's body doesn't name its ticket, so no board shows it and the dashboard's "
            "parity check flags it. Add one line to the body: \"Closes #N\" if this PR finishes the ticket, or "
            "\"Part of #N\" if it is a step (a mock-up, a stacked slice, a plan, docs). Use owner/repo#N for a ticket "
            f"in another repo. \"for #N\" or a bare \"#N\" doesn't count ({RULE_DOC}).")


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


def gate(argv, say, log, env=None, read_file=None, registry: Path | None = None, here=repo_here) -> int | None:
    """What bin/gh calls: 1 (refused, said why) or None (go on). `log(entry)` records overrides and refusals."""
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
    if not msg:
        return None
    say(msg)
    say(f'(only if a person agrees this PR is for no ticket: {OVERRIDE}="<reason>" gh ...)')
    log({"cmd": call["cmd"], "repo": repo, "rc": 1, "no_ticket": msg[:200]})
    return 1
