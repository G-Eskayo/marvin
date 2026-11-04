"""The one place MARVIN talks to WezTerm (marvin#1059, PRD #1058).

Every `wezterm cli` call goes through here so three things are decided once:
  - which binary: MARVIN_WEZTERM (or the older HELPER_TAB_WEZTERM), then the known install paths, then PATH;
  - which WezTerm: each call names a GUI's socket, so with two GUIs running (a second one started with
    --always-new-process, say) the right one is addressed. Inside a WezTerm pane that is the pane's own GUI;
    outside, the oldest running GUI, which is the one a person started first;
  - how long: every call has a time limit and never auto-starts a hidden mux server (a session spawned into one
    is invisible), so "WezTerm isn't running" is reported, not papered over.

Standard library only: hooks import it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

HOME = Path.home()
CANDIDATES = (HOME / ".local/bin/wezterm", Path("/Applications/WezTerm.app/Contents/MacOS/wezterm"),
              Path("/opt/homebrew/bin/wezterm"))
SOCK_DIR = HOME / ".local/share/wezterm"
TIMEOUT_S = 15
GLOBAL_OPTS = {"--no-auto-start", "--prefer-mux"}


class WeztermError(RuntimeError):
    """WezTerm couldn't be found, didn't answer in time, or refused a call."""


def find_binary(env: dict | None = None, candidates: Iterable[Path] | None = None,
                which: Callable[[str], str | None] | None = None, strict: bool = True) -> str:
    """The wezterm binary. strict=False never raises: on a machine without WezTerm (a CI runner) it names the usual
    Homebrew path, so a Wezterm can still be made and a real call fails then, with a clear WeztermError."""
    env = os.environ if env is None else env
    candidates = CANDIDATES if candidates is None else candidates     # read at call time, so tests can patch them
    which = which or shutil.which
    for key in ("MARVIN_WEZTERM", "HELPER_TAB_WEZTERM"):
        if env.get(key) and Path(env[key]).exists():
            return env[key]
    for c in candidates:
        if Path(c).exists():
            return str(c)
    found = which("wezterm")
    if found:
        return found
    if not strict:
        return str(list(candidates)[-1]) if list(candidates) else "/opt/homebrew/bin/wezterm"
    raise WeztermError("WezTerm isn't installed on this Mac (looked in ~/.local/bin, /Applications and Homebrew)")


@dataclass(frozen=True)
class Gui:
    pid: int
    started: str          # ps lstart: changes when WezTerm restarts, so "pid started" identifies one run
    socket: str | None    # its gui-sock, None if the file isn't there

    @property
    def identity(self) -> str:
        return f"{self.pid} {self.started}"


def guis(run: Callable | None = None, sock_dir: Path = SOCK_DIR) -> list[Gui]:
    """Running WezTerm GUI processes, oldest first; [] if ps can't tell."""
    run = run or subprocess.run   # looked up at call time, so a test that patches subprocess.run is honoured
    try:
        out = run(["/bin/ps", "-axo", "pid=,lstart=,comm="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    found = []
    for line in out.stdout.splitlines():
        fields = line.split()
        if len(fields) < 7 or not fields[-1].endswith("/wezterm-gui") or not fields[0].isdigit():
            continue
        pid = int(fields[0])
        sock = Path(sock_dir) / f"gui-sock-{pid}"
        found.append(Gui(pid, " ".join(fields[1:6]), str(sock) if sock.exists() else None))
    from datetime import datetime

    def when(g: Gui):
        try:
            return datetime.strptime(" ".join(g.started.split()), "%a %b %d %H:%M:%S %Y")
        except ValueError:
            return datetime.max
    return sorted(found, key=lambda g: (when(g), g.pid))


def main_gui(run: Callable | None = None, sock_dir: Path = SOCK_DIR, env: dict | None = None) -> Gui | None:
    """The GUI to talk to: this pane's own when inside WezTerm, else the oldest running one; None if none runs."""
    env = os.environ if env is None else env
    running = guis(run, sock_dir)
    mine = env.get("WEZTERM_UNIX_SOCKET")
    for g in running:
        if mine and g.socket == mine:
            return g
    return running[0] if running else None


def subcommand(cmd: list[str]) -> str | None:
    """The cli subcommand of a command line (`list`, `spawn`, ...), skipping global options; None if not a cli call."""
    if len(cmd) < 2 or cmd[1] != "cli":
        return None
    for part in cmd[2:]:
        if part not in GLOBAL_OPTS:
            return part
    return None


def _pane(pane) -> str:
    if not isinstance(pane, int) or isinstance(pane, bool) or pane < 0:
        raise ValueError(f"not a pane id: {pane!r}")
    return str(pane)


def _detached(cmd: list[str]) -> None:
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


class Wezterm:
    """`wezterm cli` aimed at one GUI. socket=None leaves the target to WezTerm's own choice (and drops any socket
    inherited from the calling pane, so nothing is aimed somewhere by accident)."""

    def __init__(self, binary: str | None = None, socket: str | None = None, run: Callable | None = None,
                 timeout: float = TIMEOUT_S, start: Callable[[list[str]], None] | None = None):
        self.binary = binary or find_binary(strict=False)
        self.socket, self._run, self.timeout, self._start_fn = socket, run, timeout, start

    def run(self, *a, **k):
        return (self._run or subprocess.run)(*a, **k)

    @classmethod
    def for_gui(cls, gui: Gui | None, **kw) -> "Wezterm":
        return cls(socket=gui.socket if gui else None, **kw)

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        cmd = [self.binary, "cli", "--no-auto-start", *args]
        env = {k: v for k, v in os.environ.items() if k != "WEZTERM_UNIX_SOCKET"}
        if self.socket:
            env["WEZTERM_UNIX_SOCKET"] = self.socket
        try:
            return self.run(cmd, capture_output=True, text=True, timeout=self.timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            raise WeztermError(f"wezterm cli {args[0]} didn't answer within {self.timeout:g} s") from exc
        except OSError as exc:
            raise WeztermError(f"wezterm cli {args[0]} couldn't run: {exc}") from exc

    def _ok(self, *args: str) -> str:
        r = self.cli(*args)
        if r.returncode != 0:
            raise WeztermError(f"wezterm cli {args[0]} failed: {(r.stderr or r.stdout or '').strip()[:300]}")
        return r.stdout

    def list(self) -> list[dict] | None:
        """Every pane of this GUI; None when no GUI answers."""
        r = self.cli("list", "--format", "json")
        if r.returncode != 0 or not (r.stdout or "").strip():
            return None
        try:
            rows = json.loads(r.stdout)
        except ValueError as exc:
            raise WeztermError(f"wezterm cli list gave output that isn't JSON: {r.stdout[:120]!r}") from exc
        if not isinstance(rows, list) or not all(isinstance(x, dict) and "pane_id" in x for x in rows):
            raise WeztermError("wezterm cli list gave rows without pane ids")
        return rows

    def spawn(self, cwd: Path, program: list[str], window_id: int | None = None, new_window: bool = False) -> int:
        if window_id is not None and new_window:
            raise ValueError("spawn into a window or a new window, not both")
        where = ["--window-id", _pane(window_id)] if window_id is not None else ["--new-window"] if new_window else []
        out = self._ok("spawn", *where, "--cwd", str(cwd), "--", *program).strip()
        if not out.isdigit():
            raise WeztermError(f"wezterm cli spawn didn't return a pane id: {out[:80]!r}")
        return int(out)

    def set_tab_title(self, pane: int, title: str) -> None:
        self._ok("set-tab-title", "--pane-id", _pane(pane), *(["--", title] if title.startswith("-") else [title]))

    def activate_pane(self, pane: int) -> None:
        self._ok("activate-pane", "--pane-id", _pane(pane))

    def get_text(self, pane: int) -> str:
        return self._ok("get-text", "--pane-id", _pane(pane))

    def send_text(self, pane: int, text: str, paste: bool = True) -> None:
        """Raw: callers that send a person's or the dashboard's words must clean them first (marvin#1067)."""
        self._ok("send-text", "--pane-id", _pane(pane), *([] if paste else ["--no-paste"]),
                 *(["--", text] if text.startswith("-") else [text]))

    def kill_pane(self, pane: int) -> None:
        self._ok("kill-pane", "--pane-id", _pane(pane))

    def list_clients(self) -> list[dict]:
        """The GUI clients attached to this mux, each with its focused_pane_id; [] when none answers."""
        r = self.cli("list-clients", "--format", "json")
        if r.returncode != 0 or not (r.stdout or "").strip():
            return []
        try:
            rows = json.loads(r.stdout)
        except ValueError:
            return []
        return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []

    def focused_panes(self) -> set[int]:
        return {c["focused_pane_id"] for c in self.list_clients() if isinstance(c.get("focused_pane_id"), int)}

    def start(self, cwd: Path, program: list[str]) -> None:
        """Start WezTerm itself (its own GUI) with this program, detached."""
        try:
            (self._start_fn or _detached)([self.binary, "start", "--cwd", str(cwd), "--", *program])
        except OSError as exc:
            raise WeztermError(f"WezTerm couldn't be started: {exc}") from exc
