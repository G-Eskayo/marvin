"""Tests never touch the real ~/.claude (marvin pipeline review 2026-10-21, finding F10).

Tests kept writing into the real logs: 147 of 160 "mr:approve failed" lines in errors.jsonl and every line of
gate-run-durations.jsonl were test fixtures, and on 2026-10-09 a test wiped ~/.claude/logs. A rule ("tests use a temp
HOME") existed, but nothing enforced it. The repo-wide conftest.py uses this module to enforce it two ways:

- ``make_test_home``: a fresh HOME for the test process that mirrors the real one through symlinks (so ~/.agents,
  ~/.gitconfig, ~/Developer and the rest read as before) except ``.claude*``, which is a new empty folder. Every
  ``Path.home()`` constant and every subprocess (python, node, git, sh) then lands in the temp copy.
- ``install_write_guard``: an audit hook that refuses, in this process, any write, rename, removal or database open
  under the real ~/.claude (or ~/.claude.json), and records which test tried, so the test fails by name even when the
  code under test swallows the error.

Cost: the mirror is O(entries in the real HOME) symlinks once per test process; the hook is an O(1) set lookup per
audit event, plus a string prefix check for the few path events.
"""
from __future__ import annotations

import os
import pwd
import tempfile
from pathlib import Path

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# Audit events whose first argument is a path the call changes.
_PATH_EVENTS = frozenset({"os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.truncate", "os.symlink", "os.link",
                          "os.chmod", "os.chown", "os.utime", "shutil.rmtree", "shutil.move", "sqlite3.connect"})
# Events whose SECOND argument is the destination.
_DEST_EVENTS = frozenset({"os.rename", "os.symlink", "os.link", "shutil.move"})
# Copies only write their destination (reading a real file is not what this guards).
_DEST_ONLY_EVENTS = frozenset({"shutil.copyfile"})


def real_home() -> Path:
    """The account's home from the password database: right even when HOME was already pointed elsewhere."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def protected_roots(home: Path) -> tuple[str, ...]:
    roots = {str(home / ".claude"), str(home / ".claude.json")}
    try:
        roots.add(os.path.realpath(home / ".claude"))
    except OSError:
        pass
    return tuple(sorted(roots))


def read_through(real: Path) -> tuple[str, ...]:
    """Inputs under the real ~/.claude that code reads as configuration, linked into the temp .claude so tests see
    them as before: the settings (which name the memory folder), the memory itself, the lexicon, the skill manifest,
    the organize scripts that live there, and the captured portfolio inventory the portfolio parity tests compare
    against (main-health only). Writes through these links are still refused (WriteGuard resolves them)."""
    return ("settings.json", "manifest.json", "lexicon.md", "organize", "portfolio/inventory", f"projects/{str(real).replace('/', '-')}/memory")


def make_test_home(real: Path, parent: str | None = None, links: tuple[str, ...] | None = None) -> Path:
    """A new temp HOME: one symlink per entry of the real home, except anything named .claude*, plus a fresh
    .claude holding only links to the read-only inputs (``read_through``). Never follows or copies what links point to."""
    home = Path(tempfile.mkdtemp(prefix="marvin-test-home-", dir=parent))
    try:
        names = os.listdir(real)
    except OSError:
        names = []
    for name in names:
        if name.startswith(".claude"):
            continue
        try:
            os.symlink(real / name, home / name)
        except OSError:
            pass
    (home / ".claude").mkdir()
    for rel in (read_through(real) if links is None else links):
        src = real / ".claude" / rel
        if not src.exists():
            continue
        dst = home / ".claude" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(src, dst)
        except OSError:
            pass
    return home


def _is_write(event: str, args: tuple) -> list:
    """The paths this audit event would change, or [] when it changes nothing."""
    if event == "open":
        # open(path, mode, flags): builtins.open passes a mode string; os.open passes mode None and int flags.
        path, mode = args[0], args[1]
        flags = args[2] if len(args) > 2 else 0
        if isinstance(path, int) or path is None:
            return []
        if isinstance(mode, str):
            return [path] if any(c in mode for c in "wax+") else []
        if isinstance(mode, int):
            flags = mode
        return [path] if isinstance(flags, int) and flags & _WRITE_FLAGS else []
    if event in _DEST_ONLY_EVENTS:
        return [args[1]] if len(args) > 1 else []
    if event in _PATH_EVENTS:
        paths = [args[0]] if args else []
        if event in _DEST_EVENTS and len(args) > 1:
            paths.append(args[1])
        return paths
    return []


def _under(path, roots: tuple[str, ...]) -> bool:
    try:
        p = os.path.abspath(os.fsdecode(path))
    except (TypeError, ValueError):
        return False
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def _real(path) -> str:
    """realpath of the path, or of its nearest existing parent for a file not created yet."""
    try:
        p = os.path.abspath(os.fsdecode(path))
    except (TypeError, ValueError):
        return ""
    head, tail = p, ""
    while head and not os.path.lexists(head):
        head, name = os.path.split(head)
        tail = os.path.join(name, tail) if tail else name
        if head == os.sep:
            break
    return os.path.join(os.path.realpath(head), tail) if tail else os.path.realpath(head)


class WriteGuard:
    """Refuses writes under ``roots`` while ``armed``; each refusal is kept in ``violations`` as (test, event, path)."""

    def __init__(self, roots: tuple[str, ...], resolve_under: tuple[str, ...] = ()):
        self.roots = roots
        # Paths under these (the temp .claude) may be links into the real one: resolve them before judging.
        self.resolve_under = resolve_under
        self.armed = True
        self.violations: list[tuple[str, str, str]] = []
        self._watched = _PATH_EVENTS | _DEST_ONLY_EVENTS | {"open"}

    def __call__(self, event: str, args: tuple) -> None:
        if event not in self._watched or not self.armed:
            return
        for path in _is_write(event, args):
            if _under(path, self.roots) or (_under(path, self.resolve_under) and _under(_real(path), self.roots)):
                where = os.environ.get("PYTEST_CURRENT_TEST", "(outside a test)").rsplit(" (", 1)[0]
                self.violations.append((where, event, os.fsdecode(path)))
                raise PermissionError(f"tests must not write the real ~/.claude ({event} {os.fsdecode(path)}): "
                                      "use tmp_path or monkeypatch the module's path constant")


ACTIVE: WriteGuard | None = None  # the guard this process installed (conftest.py), for the harness's own tests


def outside_real_home(path, real: Path | None = None) -> bool:
    """True when ``path`` does not resolve into the real home (temp folders do not)."""
    real = os.path.realpath(real or real_home())
    p = os.path.realpath(os.fsdecode(path))
    return not (p == real or p.startswith(real + os.sep))


def install_write_guard(roots: tuple[str, ...], resolve_under: tuple[str, ...] = ()) -> WriteGuard:
    import sys
    global ACTIVE
    guard = WriteGuard(roots, resolve_under)
    ACTIVE = guard
    sys.addaudithook(guard)  # cannot be removed; disarm with guard.armed = False
    return guard
