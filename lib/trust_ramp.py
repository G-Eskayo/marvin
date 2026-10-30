#!/usr/bin/env python3
"""trust_ramp.py — a project earns auto-merge with clean PRs Gil approved (ADR 0064, #340).

- Another project's ramp opens after 5 consecutive pipeline PRs Gil approved and merged cleanly ("approved-merge").
- MARVIN's ramp starts open (Gil chose its owned areas), and closes like any other.
- A "deny", a "revert" (of any PR, however old) or a "break" (main red after its merge) resets the streak to 0.
- "manual-merge" (merged on GitHub, around MARVIN) is recorded but counts for nothing.
- The same (repo, PR, event) twice counts once. Repo names compare case-insensitively.
- A PR **author** has a ramp of its own too (ADR 0069 rule 5, #952): the box's bot account (config/auto_merge.json
  ``ramp_authors``) earns auto-merge the same way, 5 clean approvals, and the same events reset it. An author ramp
  always starts closed. Logins compare case-insensitively; the same (repo, PR, event) twice counts once.
- The state lives on the Mac whose merge server acts (the mini): ~/.claude/logs/trust-ramp.json. A missing file is a
  fresh start; a corrupt one means CLOSED for everyone, and is never overwritten (history isn't silently reset).

    trust_ramp.py status           every project's and author's streak, open or not, and why it last reset
"""
from __future__ import annotations
import fcntl
import json
import re
import sys
import time
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "logs" / "trust-ramp.json"
NEEDED = 5
STARTS_OPEN = {"g-eskayo/marvin"}
COUNTS = {"approved-merge"}
RESETS = {"deny", "revert", "break"}
IGNORED = {"manual-merge"}
_REPO = re.compile(r"^[\w.-]+/[\w.-]+$")
# A GitHub login: 1-39 ASCII letters, digits and single hyphens, not starting or ending with one; apps end in [bot].
_LOGIN = re.compile(r"^(?=.{1,39}$)[A-Za-z0-9](?:-?[A-Za-z0-9])*(?:\[bot\])?$")


def _key(repo: str) -> str:
    if not isinstance(repo, str) or not _REPO.match(repo):
        raise ValueError(f"expected owner/repo, got {repo!r}")
    return repo.lower()


def _author_key(login: str) -> str:
    if not isinstance(login, str) or not _LOGIN.fullmatch(login):
        raise ValueError(f"expected a GitHub login, got {login!r}")
    return login.lower()


def _read(path: Path) -> dict | None:
    """The state, {} when there is none yet, or None when it is unreadable (corrupt)."""
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return {"repos": {}, "authors": {}}
    except OSError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("repos"), dict) \
            or not isinstance(data.setdefault("authors", {}), dict):
        return None
    return data


def _entry(state: dict, key: str, name: str) -> dict:
    return state["repos"].setdefault(key, {"name": name, "streak": NEEDED if key in STARTS_OPEN else 0, "seen": [], "last_reset": None})


def _check(pr, event) -> None:
    if not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0:
        raise ValueError(f"expected a PR number, got {pr!r}")
    if event not in COUNTS | RESETS | IGNORED:
        raise ValueError(f"unknown event {event!r}")


def _apply(path: Path, entry_of, mark: str, pr: int, event: str, reason: str, now: float | None) -> dict:
    """Under the lock: read, find the entry, count the event once, write atomically. A corrupt file is refused."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _read(path)
        if data is None:
            raise ValueError(f"{path} is unreadable; fix or remove it by hand (nothing was recorded)")
        e = entry_of(data)
        if mark in e["seen"]:
            return e
        e["seen"] = (e["seen"] + [mark])[-500:]
        if event in COUNTS:
            e["streak"] += 1
        elif event in RESETS:
            e["streak"] = 0
            e["last_reset"] = {"pr": pr, "event": event, "reason": reason[:300], "at": now or time.time()}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)
        return e


def record(repo: str, pr: int, event: str, path: Path = STATE_PATH, reason: str = "", now: float | None = None) -> dict:
    key = _key(repo)
    _check(pr, event)
    return _apply(path, lambda data: _entry(data, key, repo), f"{pr}:{event}", pr, event, reason, now)


def record_author(login: str, pr: int, event: str, path: Path = STATE_PATH, reason: str = "", now: float | None = None,
                  repo: str = "") -> dict:
    """Record a PR event into `login`'s own ramp. `repo` (owner/repo) keeps PR numbers of different repos apart."""
    key = _author_key(login)
    _check(pr, event)
    where = f"{_key(repo)}#" if repo else ""

    def entry_of(data):
        return data["authors"].setdefault(key, {"name": login, "streak": 0, "seen": [], "last_reset": None})
    return _apply(path, entry_of, f"{where}{pr}:{event}", pr, event, reason, now)


def _streak(e) -> int:
    s = e.get("streak") if isinstance(e, dict) else None
    return s if isinstance(s, int) and not isinstance(s, bool) else 0


def author_is_open(login: str, path: Path = STATE_PATH) -> bool:
    """True only once `login` has NEEDED clean approvals in a row. A bad login, a missing or corrupt file: closed."""
    try:
        key = _author_key(login)
    except ValueError:
        return False
    data = _read(Path(path))
    if data is None:
        return False
    return _streak(data["authors"].get(key)) >= NEEDED


def author_streak(login: str, path: Path = STATE_PATH) -> int:
    """`login`'s current streak (0 when unknown, unreadable or a bad login), for "3 of 5" in a reason."""
    try:
        key = _author_key(login)
    except ValueError:
        return 0
    data = _read(Path(path))
    return _streak(data["authors"].get(key)) if data else 0


def is_open(repo: str, path: Path = STATE_PATH) -> bool:
    data = _read(Path(path))
    if data is None:
        return False
    key = _key(repo)
    e = data["repos"].get(key) or {"streak": NEEDED if key in STARTS_OPEN else 0}
    return e["streak"] >= NEEDED


def status(path: Path = STATE_PATH) -> dict:
    """{owner/repo (as first recorded): {streak, open, last_reset}}; MARVIN is listed even before any event.
    Author ramps are listed as "@login" (as first recorded) with "kind": "author"."""
    data = _read(Path(path))
    if data is None:
        return {}
    out = {v.get("name", k): {"streak": v["streak"], "open": v["streak"] >= NEEDED, "last_reset": v.get("last_reset")}
           for k, v in data["repos"].items()}
    if "g-eskayo/marvin" not in data["repos"]:
        out["G-Eskayo/marvin"] = {"streak": NEEDED, "open": True, "last_reset": None}
    for k, v in data["authors"].items():
        out["@" + str(v.get("name", k) if isinstance(v, dict) else k)] = {
            "kind": "author", "streak": _streak(v), "open": _streak(v) >= NEEDED,
            "last_reset": v.get("last_reset") if isinstance(v, dict) else None}
    return out


def main(argv) -> int:
    if argv[:1] == ["status"]:
        st = status(STATE_PATH)
        if not st:
            print("trust ramp state unreadable or empty")
        for repo, s in sorted(st.items()):
            why = f" (reset by {s['last_reset']['event']} of PR #{s['last_reset']['pr']})" if s.get("last_reset") else ""
            print(f"{repo:<45} {'open' if s['open'] else 'closed':<7} {min(s['streak'], NEEDED)}/{NEEDED}{why}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
