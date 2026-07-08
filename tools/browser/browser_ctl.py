#!/usr/bin/env python3
"""
browser_ctl.py — persistent Playwright-driven Chromium for recurring browser automation.

Dedicated profile at ~/.agents/browser-profile/, deliberately separate from Comet/the daily-driver
browser — attaching to a real logged-in session would need a remote-debugging port open on that
browser, which lets any local process fully drive it. A separate profile avoids that tradeoff while
still solving the actual recurring need: cookies/logins persist across script invocations, and the
browser itself stays running as a background process so repeated actions within a task don't each
pay Chromium's launch cost. Attach via CDP per-action rather than holding one long-lived Python
process, since each Bash tool call is its own process.

Usage:
  browser_ctl.py start                    # launch the daemon (idempotent)
  browser_ctl.py stop
  browser_ctl.py status
  browser_ctl.py navigate <url>
  browser_ctl.py screenshot [path]
  browser_ctl.py text                     # visible text content of the current page
  browser_ctl.py html                     # full page HTML
  browser_ctl.py click <selector>
  browser_ctl.py fill <selector> <value>
  browser_ctl.py wait <seconds>
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path.home() / ".agents" / "browser-profile"
STATE_FILE = PROFILE_DIR / "daemon.json"
DEBUG_PORT = 9222
CDP_URL = f"http://127.0.0.1:{DEBUG_PORT}"


def _read_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _chromium_executable() -> str:
    with sync_playwright() as p:
        return p.chromium.executable_path


def cmd_start():
    state = _read_state()
    if state and _is_running(state["pid"]):
        print(f"Already running (pid {state['pid']}, port {state['port']})")
        return

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    (PROFILE_DIR / "profile").mkdir(exist_ok=True)

    proc = subprocess.Popen(
        [
            _chromium_executable(),
            f"--remote-debugging-port={DEBUG_PORT}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={PROFILE_DIR / 'profile'}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    STATE_FILE.write_text(json.dumps({"pid": proc.pid, "port": DEBUG_PORT}))
    print(f"Started (pid {proc.pid}, port {DEBUG_PORT})")


def cmd_stop():
    state = _read_state()
    if not state:
        print("Not running")
        return
    if _is_running(state["pid"]):
        os.kill(state["pid"], 15)
    STATE_FILE.unlink(missing_ok=True)
    print("Stopped")


def cmd_status():
    state = _read_state()
    if state and _is_running(state["pid"]):
        print(f"Running (pid {state['pid']}, port {state['port']})")
    else:
        print("Not running")


def _with_page(fn):
    state = _read_state()
    if not state or not _is_running(state["pid"]):
        print("Daemon not running — run 'start' first", file=sys.stderr)
        sys.exit(1)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        result = fn(page)
        browser.close()  # closes the CDP connection only, not the browser process
        return result


def cmd_navigate(url: str):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _with_page(lambda page: page.goto(url, wait_until="domcontentloaded"))
    print(f"Navigated to {url}")


def cmd_screenshot(path: str = None):
    path = path or str(PROFILE_DIR / f"screenshot-{int(time.time())}.png")
    _with_page(lambda page: page.screenshot(path=path, full_page=False))
    print(path)


def cmd_text():
    result = _with_page(lambda page: page.inner_text("body"))
    print(result)


def cmd_html():
    result = _with_page(lambda page: page.content())
    print(result)


def cmd_click(selector: str):
    _with_page(lambda page: page.click(selector))
    print(f"Clicked {selector}")


def cmd_fill(selector: str, value: str):
    _with_page(lambda page: page.fill(selector, value))
    print(f"Filled {selector}")


def cmd_wait(seconds: str):
    time.sleep(float(seconds))


COMMANDS = {
    "start": (cmd_start, 0),
    "stop": (cmd_stop, 0),
    "status": (cmd_status, 0),
    "navigate": (cmd_navigate, 1),
    "screenshot": (cmd_screenshot, (0, 1)),
    "text": (cmd_text, 0),
    "html": (cmd_html, 0),
    "click": (cmd_click, 1),
    "fill": (cmd_fill, 2),
    "wait": (cmd_wait, 1),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    cmd, args = sys.argv[1], sys.argv[2:]
    fn, arity = COMMANDS[cmd]
    if isinstance(arity, tuple):
        if len(args) not in arity:
            print(f"'{cmd}' expects {arity} args, got {len(args)}", file=sys.stderr)
            sys.exit(1)
    elif len(args) != arity:
        print(f"'{cmd}' expects {arity} args, got {len(args)}", file=sys.stderr)
        sys.exit(1)
    fn(*args)


if __name__ == "__main__":
    main()
