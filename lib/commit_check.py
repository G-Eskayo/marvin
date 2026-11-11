#!/usr/bin/env python3
"""commit_check.py — a direct commit that changes code without a test needs a stated reason (ADR 0063 gate 4, #337).

Interactive sessions (and anyone) can commit straight to main, around the pipeline's verify step. This git commit-msg
hook applies the same rule as verify (lib/test_change_rule.py, so the two gates can't disagree): when the staged code
changed and no test did, the commit is refused unless its message has its own line

    No-test-reason: <why there's no test, in words>

Filler (empty, TBD, n/a, a dash) doesn't count. Reasons are logged (~/.claude/logs/test-skips.jsonl) for the Health
trend (#342). Never blocked, but logged: auto-sync commits (MARVIN_COMMIT_KIND=auto-sync, they sweep up whatever is in
the working tree). Not re-checked: merges, rebases, cherry-picks and reverts (their commits were checked when made).
`git commit --no-verify` skips any hook; the Health trend still sees code that landed without tests.

Parked choices (marvin#1222; Gil 2026-11-09: refuse, with a logged override): text in `config/` or `instance/config/`
that parks a choice on the owner ("until <name> decides", "once the owner decides", "ask <Name>") is refused unless the
choice has a home: in a JSON file, a non-empty "parked" entry (lib/parked.py's grammar: decision ticket + review_by);
in any other file, a "parked as <id>" pointer to one. Code blocks don't count. MARVIN_PARKED_OK="<reason>" lets one
commit through, logged to ~/.claude/logs/parked-overrides.jsonl.

    commit_check.py install [repo]     put the hook in <repo>/.git/hooks (never over a different commit-msg hook)
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_change_rule as tcr  # noqa: E402

MARK = "# marvin-commit-check (ADR 0063 gate 4)"
_REASON = re.compile(r"^No-test-reason:[ \t]*(.*)$", re.M)
_FILLER = re.compile(r"^(tbd|todo|n/?a|none|-+|\.+)$", re.I)


def _log_path() -> Path:
    return Path(os.environ.get("MARVIN_TEST_SKIP_LOG") or Path.home() / ".claude" / "logs" / "test-skips.jsonl")


def _log(kind: str, files: list[str], reason: str, repo: Path) -> None:
    try:
        p = _log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps({"at": time.time(), "kind": kind, "repo": str(repo), "files": files, "reason": reason[:300]}) + "\n")
    except OSError:
        pass  # the log must never decide whether a commit lands


def reason_in(message: str) -> str | None:
    for m in _REASON.finditer(message or ""):
        why = m.group(1).strip()
        if len(why) >= 3 and not _FILLER.match(why):
            return why
    return None


# Any one-word name (each install's owner differs, ADR 0071) or "the owner"; "ask <Name>" only with a capitalised name.
PARKING = re.compile(r"\b(?i:until|once|till)\s+(?:(?i:the owner)|\w+)\s+(?i:decides|answers|says)\b|\b[Aa]sk [A-Z][a-z]+\b(?! (?:for|about|to)\b)")
_CONFIG = re.compile(r"^(?:instance/)?config/")
_FENCE = re.compile(r"```.*?```", re.S)


def _parked_log() -> Path:
    return Path(os.environ.get("MARVIN_PARKED_LOG") or Path.home() / ".claude" / "logs" / "parked-overrides.jsonl")


def parking_problems(repo: Path) -> list[str]:
    """Staged config files that park a choice on the owner without giving it a home."""
    names = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], cwd=repo,
                           capture_output=True, text=True).stdout.split("\n")
    out = []
    for path in filter(None, names):
        if not _CONFIG.match(path):
            continue
        text = subprocess.run(["git", "show", f":{path}"], cwd=repo, capture_output=True, text=True).stdout
        if not PARKING.search(_FENCE.sub(" ", text)):
            continue
        if path.endswith(".json"):
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            if isinstance(data, dict) and isinstance(data.get("parked"), dict) and data["parked"]:
                continue
        elif re.search(r"\bparked as [\w.-]+", text, re.I):
            continue
        out.append(path)
    return out


def _replaying(repo: Path) -> bool:
    gitdir = Path(subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True, text=True).stdout.strip())
    gitdir = gitdir if gitdir.is_absolute() else repo / gitdir
    return any((gitdir / n).exists() for n in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"))


def check(repo: Path, message: str, env=os.environ) -> tuple[bool, str]:
    repo = Path(repo)
    if _replaying(repo):
        return True, "replaying commits that were checked when made"
    parks = parking_problems(repo)
    if parks and env.get("MARVIN_COMMIT_KIND") != "auto-sync":
        override = (env.get("MARVIN_PARKED_OK") or "").strip()
        if not override:
            return False, (f"{', '.join(parks)} parks a choice on the owner in free text, where nothing will ever "
                           f"bring it back. Give it a home: a ticket with a Decisions block, and in the file a "
                           f'"parked": {{"<id>": {{"decision": "owner/repo#N", "review_by": "YYYY-MM-DD"}}}} entry '
                           f"(or, outside JSON, \"parked as <id>\" pointing at one). See lib/parked.py. "
                           f'MARVIN_PARKED_OK="<reason>" lets one commit through, logged.')
        try:
            lp = _parked_log()
            lp.parent.mkdir(parents=True, exist_ok=True)
            with open(lp, "a") as f:
                f.write(json.dumps({"at": time.time(), "repo": str(repo), "files": parks, "reason": override[:300]}) + "\n")
        except OSError:
            pass
    changes = tcr.staged_changes(repo)
    ok, why = tcr.check(changes, tcr.MARVIN_RULES)
    if ok:
        return True, why
    code = [c["path"] for c in changes if tcr.kind(c["path"], tcr.MARVIN_RULES) == "code"]
    if env.get("MARVIN_COMMIT_KIND") == "auto-sync":
        _log("auto-sync", code, "auto-sync swept up code without tests", repo)
        return True, "auto-sync (logged)"
    stated = reason_in(message)
    if stated:
        _log("reason", code, stated, repo)
        return True, "reason stated (logged)"
    return False, (f"{why}\n\nIf this change really has no test (docs-like code, a constant tuned from data, a revert), "
                   f"say why on its own line in the commit message:\n\n    No-test-reason: <why, in words>\n\n"
                   f"It is logged and shown in Health (ADR 0063).")


def _hook_text() -> str:
    return (f"#!/bin/sh\n{MARK}\n# Installed by lib/commit_check.py; see that file. Remove this file to switch it off.\n"
            f'exec "{sys.executable}" "{Path(__file__).resolve()}" hook "$1"\n')


def install_hook(repo: Path, force: bool = False) -> str:
    gitdir = Path(subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repo, capture_output=True, text=True).stdout.strip())
    gitdir = gitdir if gitdir.is_absolute() else Path(repo) / gitdir
    hook = gitdir / "hooks" / "commit-msg"
    if hook.exists():
        current = hook.read_text(errors="replace")
        if MARK not in current and not force:
            return "skipped: a different commit-msg hook is already installed"
        if current == _hook_text():
            return "already installed"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(_hook_text())
    hook.chmod(0o755)
    return "installed"


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "hook":
        try:
            message = Path(argv[1]).read_text(errors="replace")
            ok, why = check(Path.cwd(), message)
        except Exception as e:  # noqa: BLE001 -- a broken check must say so, not silently pass or block forever
            sys.stderr.write(f"commit check could not run ({e}); committing anyway. Health will show it.\n")
            return 0
        if not ok:
            sys.stderr.write(f"commit refused (ADR 0063, tests try to break it):\n{why}\n")
            return 1
        return 0
    if argv[:1] == ["install"]:
        print(install_hook(Path(argv[1]) if len(argv) > 1 else Path.home() / ".agents"))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
