"""Start a helper in a labelled WezTerm tab on this machine (marvin#753).

    helper-tab --group "Seal Speak" --title "#60 split wiring" [--cwd DIR] [--on-exit CMD] -- command args...
    helper-tab --install-wezterm      # once per machine: colour helper tabs by group

The tab joins the WezTerm window that already holds helper tabs (else any open window, else a new one), is titled
"● <group> · <title>", and stays open when the command ends so it can be read. Everything after that is triggered by
the command's own exit, never by a watcher: the title flips to ✓ or ✗, the run lands in the dashboard's Activity log
(job_events), a macOS notification fires, and --on-exit runs (with HELPER_RC set) so whoever is waiting is told.
Over SSH (the Mini) `open -a WezTerm` starts the GUI in the login session, so the helper gets the keychain login
that a plain SSH process lacks. No LLM and no GitHub calls: plain Python, wezterm cli and the local logs.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

SEP = " · "
MARKS = {"running": "●", "done": "✓", "failed": "✗"}
WEZTERM = os.environ.get("HELPER_TAB_WEZTERM") or shutil.which("wezterm") or "/opt/homebrew/bin/wezterm"
HERE = Path(__file__).resolve()
PY = Path.home() / ".agents" / "venv" / "bin" / "python"
LUA = HERE.parents[1] / "config" / "wezterm" / "helper_tabs_marvin.lua"
WEZTERM_CONFIG = Path.home() / ".config" / "wezterm" / "wezterm.lua"
INSTALL_LINE = "require('helper_tabs_marvin')"


def tab_title(group: str, title: str, state: str) -> str:
    if state not in MARKS:
        raise ValueError(f"unknown state {state!r}")
    group = " ".join(group.replace(SEP.strip(), " ").split())
    title = " ".join(title.split())
    if not group or not title:
        raise ValueError("a helper tab needs both a group and a title")
    return f"{MARKS[state]} {group}{SEP}{title}"


def parse_title(raw: str) -> tuple[str, str, str] | None:
    """(state, group, title) for a helper tab's title, None for any other tab."""
    for state, mark in MARKS.items():
        if raw.startswith(mark + " ") and SEP in raw:
            group, title = raw[len(mark) + 1:].split(SEP, 1)
            return state, group, title
    return None


def pick_window(panes: list[dict]) -> int | None:
    """The window holding the most helper tabs; without helpers the lowest-id open window; None if nothing is open."""
    if not panes:
        return None
    helpers: dict[int, set[int]] = {}
    for p in panes:
        if parse_title(p.get("tab_title") or ""):
            helpers.setdefault(p["window_id"], set()).add(p["tab_id"])
    if helpers:
        return max(sorted(helpers), key=lambda w: len(helpers[w]))
    return min(p["window_id"] for p in panes)


def job_name(group: str, title: str) -> str:
    return "helper-" + re.sub(r"[^a-z0-9]+", "-", f"{group} {title}".lower()).strip("-")[:60]


def wrapper_script(command: list[str], group: str, title: str, on_exit: str | None = None) -> str:
    """The shell the tab runs: the helper under `_run` (which does all the on-exit work), then an interactive shell
    so the tab stays readable."""
    run = [str(PY if PY.exists() else sys.executable), str(HERE), "_run", "--group", group, "--title", title]
    if on_exit:
        run += ["--on-exit", on_exit]
    return f"{shlex.join(run + ['--', *command])}\nexec zsh -l\n"


def run_helper(group: str, title: str, command: list[str], on_exit: str | None = None) -> int:
    """Run the command in this tab, then fire everything its exit triggers. The recording steps are best-effort:
    none of them may change the helper's own exit code."""
    sys.path.insert(0, str(HERE.parent))
    import job_events
    jobs_dir = Path(os.environ["HELPER_TAB_JOBS_DIR"]) if os.environ.get("HELPER_TAB_JOBS_DIR") else None
    rc = 1
    try:
        with job_events.job_run(job_name(group, title), f"{group}: {title}", jobs_dir) as run:
            rc = subprocess.run(command).returncode
            if rc:
                run.fail(f"exited with status {rc}")
    except Exception:  # noqa: BLE001 -- job_run re-raises nothing we need; the exit code is what matters
        pass
    state = "done" if rc == 0 else "failed"
    pane = os.environ.get("WEZTERM_PANE")
    if pane:
        subprocess.run([WEZTERM, "cli", "set-tab-title", "--pane-id", pane, tab_title(group, title, state)],
                       capture_output=True)
    if not os.environ.get("HELPER_TAB_QUIET"):
        import notify
        notify.notify(f"{group}: {'finished' if rc == 0 else 'failed'}", title)
    if on_exit:
        subprocess.run(["zsh", "-c", on_exit], env={**os.environ, "HELPER_RC": str(rc)})
    print(f"\n── {tab_title(group, title, state)}: exit {rc} ──")
    return rc


def _list_panes() -> list[dict] | None:
    """Panes of the running WezTerm GUI, or None when no GUI is running."""
    r = subprocess.run([WEZTERM, "cli", "--no-auto-start", "list", "--format", "json"], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def launch(group: str, title: str, command: list[str], cwd: str, on_exit: str | None = None) -> int:
    running = tab_title(group, title, "running")  # validates before anything opens
    argv = ["zsh", "-lc", wrapper_script(command, group, title, on_exit)]
    panes = _list_panes()
    window = pick_window(panes or [])
    if window is None:
        before = {p["pane_id"] for p in panes or []}
        subprocess.run(["open", "-a", "WezTerm", "--args", "start", "--cwd", cwd, "--", *argv], check=True)
        pane_id = None
        for _ in range(60):  # bounded wait for the GUI we just started to come up, not a standing watcher
            time.sleep(0.5)
            new = [p for p in (_list_panes() or []) if p["pane_id"] not in before]
            if new:
                pane_id = new[0]["pane_id"]
                break
        if pane_id is None:
            print("helper-tab: WezTerm started but no new pane appeared within 30 s", file=sys.stderr)
            return 1
    else:
        r = subprocess.run([WEZTERM, "cli", "spawn", "--window-id", str(window), "--cwd", cwd, "--", *argv],
                           capture_output=True, text=True, check=True)
        pane_id = int(r.stdout.strip())
    subprocess.run([WEZTERM, "cli", "set-tab-title", "--pane-id", str(pane_id), running], check=True)
    print(pane_id)
    return 0


def install_wezterm(config: Path = WEZTERM_CONFIG, lua: Path = LUA) -> str:
    """Load the group colouring from wezterm.lua. Idempotent; the lua itself stays in ~/.agents so it syncs."""
    text = config.read_text() if config.exists() else "local wezterm = require 'wezterm'\nlocal config = wezterm.config_builder()\nreturn config\n"
    if INSTALL_LINE in text:
        return "already installed"
    block = (f"\n-- Helper tabs: colour each group's tabs (marvin#753). Lives in ~/.agents so it syncs.\n"
             f"package.path = package.path .. ';{lua.parent}/?.lua'\n"
             f"{INSTALL_LINE}\n")
    idx = text.rfind("return config")
    if idx < 0:
        raise ValueError(f"{config} has no 'return config'; add `{INSTALL_LINE}` by hand")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text[:idx] + block.lstrip("\n") + "\n" + text[idx:])
    return "installed"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--install-wezterm"]:
        print(install_wezterm())
        return 0
    internal = argv[:1] == ["_run"]
    ap = argparse.ArgumentParser(prog="helper-tab", description=__doc__.split("\n\n")[0])
    ap.add_argument("--group", required=True, help="project or area, e.g. 'Seal Speak', 'MARVIN'")
    ap.add_argument("--title", required=True, help="what it's working on, e.g. '#60 split wiring'")
    ap.add_argument("--cwd", default=".", help="directory the command runs in")
    ap.add_argument("--on-exit", help="shell command run when the helper ends, with HELPER_RC set")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="-- command args...")
    a = ap.parse_args(argv[1:] if internal else argv)
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command:
        ap.error("give the command after --")
    try:
        if internal:
            return run_helper(a.group, a.title, command, a.on_exit)
        return launch(a.group, a.title, command, str(Path(a.cwd).expanduser().resolve()), a.on_exit)
    except ValueError as e:
        ap.error(str(e))


if __name__ == "__main__":
    sys.exit(main())
