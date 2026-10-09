#!/usr/bin/env python3
"""The MARVIN button's session launcher (marvin#228, ADR 0059): opens a ready Interactive MARVIN session in WezTerm.

    marvin_session.py open [--ticket N] [--repo owner/name]   # prints {"ok": ..., "dir": ..., "error": ...}

- **With a ticket**, the session gets its own worktree on `ticket/<n>-<slug>` (the agreed naming, marvin#226),
  created from origin/main or reused if it already exists. Worktrees live under the pipeline's WORKTREES_ROOT, so
  the daily cleanup sweep removes them once their PR merges or closes (never with uncommitted work) and Health
  already shows their count and disk use. A session never starts in the shared ~/.agents checkout, where
  auto-sync commits.
- **Without a ticket**, it starts at home.
- **Its own environment**: the shell it opens sets PATH, the venv and the GitHub token (read from
  ~/.claude/.gh-token inside the shell, so it never appears on a command line), and marks the run Interactive.
  Nothing is inherited from Electron or launchd. The session itself gets MARVIN's layers from its hooks
  (marvin#291), as any Interactive session does.
- **This machine only**: it opens WezTerm on the machine that runs it. The phone's backend never calls it.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from marvin_launcher import KIND_ENV  # noqa: E402
from sandbox_orchestration import WORKTREES_ROOT  # noqa: E402

HOME = Path.home()
WEZTERM_CANDIDATES = (HOME / ".local/bin/wezterm", Path("/Applications/WezTerm.app/Contents/MacOS/wezterm"),
                      Path("/opt/homebrew/bin/wezterm"))
SESSION_PATH = ":".join([str(HOME / ".agents/venv/bin"), str(HOME / ".local/bin"), "/opt/homebrew/bin",
                         "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
GH_TOKEN_FILE = HOME / ".claude" / ".gh-token"


class SessionError(RuntimeError):
    pass


def slug(title: str, limit: int = 40) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return words[:limit].rsplit("-", 1)[0] if len(words) > limit else words


def branch_for(ticket: int, title: str) -> str:
    return f"ticket/{ticket}-{slug(title)}"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def session_dir(clone: Path, ticket: int | None, title: str | None) -> Path:
    """Where the session starts: this ticket's worktree (created or reused), or home when there's no ticket."""
    if ticket is None:
        return HOME
    branch = branch_for(ticket, title or "")
    path = WORKTREES_ROOT / branch.replace("/", "-")
    if (path / ".git").exists():
        return path
    WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    _git(clone, "fetch", "-q", "origin", "main")
    has_branch = _git(clone, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    args = ["worktree", "add", str(path), branch] if has_branch else \
        ["worktree", "add", "-b", branch, str(path), "origin/main"]
    added = _git(clone, *args)
    if added.returncode != 0:
        raise SessionError(f"couldn't create the worktree for #{ticket}: {added.stderr.strip()[:300]}")
    return path


def shell_script(directory: Path) -> str:
    return "\n".join([
        f"cd {shlex.quote(str(directory))} || exit 1",
        f"export PATH={shlex.quote(SESSION_PATH)}",
        f"export VIRTUAL_ENV={shlex.quote(str(HOME / '.agents/venv'))}",
        f"export {KIND_ENV}=interactive",
        f'[ -f {shlex.quote(str(GH_TOKEN_FILE))} ] && export GH_TOKEN="$(cat {shlex.quote(str(GH_TOKEN_FILE))})"',
        "exec claude",
    ])


def find_wezterm() -> str:
    for candidate in WEZTERM_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    found = shutil.which("wezterm")
    if found:
        return found
    raise SessionError("WezTerm isn't installed on this Mac (looked in ~/.local/bin, /Applications and Homebrew)")


def _start_detached(cmd: list[str]) -> None:
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def open_in_wezterm(directory: Path, wezterm: str | None = None, run: Callable = subprocess.run,
                    start: Callable[[list[str]], None] = _start_detached) -> None:
    """A new window in the running WezTerm; if its mux isn't reachable, start WezTerm with the session."""
    wezterm = wezterm or find_wezterm()
    program = ["/bin/zsh", "-c", shell_script(directory)]
    spawned = run([wezterm, "cli", "spawn", "--new-window", "--cwd", str(directory), "--", *program],
                  capture_output=True, text=True, timeout=15)
    if spawned.returncode == 0:
        return
    try:
        start([wezterm, "start", "--cwd", str(directory), "--", *program])
    except OSError as exc:
        raise SessionError(f"WezTerm isn't running and couldn't be started: {exc}") from exc


def _ticket_title(repo: str, ticket: int) -> str:
    out = subprocess.run(["gh", "issue", "view", str(ticket), "--repo", repo, "--json", "title", "-q", ".title"],
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0 or not out.stdout.strip():
        raise SessionError(f"couldn't read {repo}#{ticket}: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


def _clone_for(repo: str) -> Path:
    import project_profile as pp
    profile = pp.load_profile(repo)
    clone = pp.resolve_clone(profile, pp._catalog(), ensure=True) if profile else None
    if clone is None:
        raise SessionError(f"no local checkout known for {repo} (add it with project onboarding)")
    return clone


def open_session(ticket: int | None, repo: str = "G-Eskayo/marvin") -> Path:
    clone = _clone_for(repo) if ticket is not None else HOME
    directory = session_dir(clone, ticket, _ticket_title(repo, ticket) if ticket is not None else None)
    open_in_wezterm(directory)
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["open"])
    parser.add_argument("--ticket", type=int)
    parser.add_argument("--repo", default="G-Eskayo/marvin")
    args = parser.parse_args(argv)
    try:
        directory = open_session(args.ticket, args.repo)
    except (SessionError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, "dir": str(directory)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
