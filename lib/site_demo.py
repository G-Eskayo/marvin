#!/usr/bin/env python3
"""site_demo.py: a private demo of a MARVIN-built website, served on this machine's Tailscale address only (marvin#1007).

Nothing here is public. The server binds to the machine's Tailscale IPv4 (100.64.0.0/10), never 0.0.0.0, so only
devices on the owner's tailnet can open it. No DNS, no GitHub Pages.

    site_demo.py build [--branch B] [--site S]   fetch B into the demo checkout, build site/, swap it in, write status
    site_demo.py serve [--port N] [--site S]     serve the current build (the launchd/systemd job runs this)
    site_demo.py status [--site S]               print the status file (what the dashboard's website manager reads)
    site_demo.py setup [--branch B] [--site S]   install the demo checkout's post-merge hook and remember B

Layout (all under the home folder, nothing machine-specific):
    ~/.agents-site-demo                           a dedicated clone of the engine, checked out at the demo branch.
                                                  Never the live engine checkout (~/.agents): build resets it hard.
    ~/.local/share/marvin/site-demo/<site>/       builds/<time>-<sha>/ and `current`, a symlink swapped atomically,
                                                  so the server never sees a half-copied site and never restarts
    ~/.claude/logs/site-demo-<site>.json          status: url, branch, commit, built_at, ok, error, rebuild command

Rebuilds are triggered, never polled: run `bin/site-demo build` after pushing (or over ssh from another machine),
and a `git pull` in the demo checkout rebuilds through its post-merge hook. A failed build keeps the last good one
up and says why in the status file.
"""
from __future__ import annotations

import argparse
import fcntl
import functools
import hashlib
import http.server
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_os  # noqa: E402

SITE = "marvin"
DEFAULT_PORT = 8487
DEFAULT_BRANCH = "main"
KEEP_BUILDS = 2
TAILNET = ipaddress.ip_network("100.64.0.0/10")
HOOK_MARK = "# marvin site-demo (marvin#1007)"
REBUILD_COMMAND = "~/.agents-site-demo/bin/site-demo build"


class DemoError(RuntimeError):
    """Something the owner must see: the status file and the exit code carry it."""


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def src_dir() -> Path:
    return home() / ".agents-site-demo"


def data_dir(site: str) -> Path:
    return home() / ".local" / "share" / "marvin" / "site-demo" / site


def status_path(site: str) -> Path:
    return home() / ".claude" / "logs" / f"site-demo-{site}.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── status file ─────────────────────────────────────────────────────────

def read_status(site: str) -> dict:
    try:
        data = json.loads(status_path(site).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(site: str, **fields) -> dict:
    """Merge `fields` into the status file, written whole (temp file + rename) so a reader never sees half of it."""
    data = {**read_status(site), **fields, "site": site, "rebuild_command": REBUILD_COMMAND,
            "serve_dir": str(data_dir(site) / "current"), "source": str(src_dir()), "updated_at": _now()}
    p = status_path(site)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)
    return data


# ── tailnet address ─────────────────────────────────────────────────────

Run = Callable[..., subprocess.CompletedProcess]


def _tailscale(args: list[str], run: Run) -> str | None:
    ts = host_os.tailscale_bin()
    if not ts:
        return None
    try:
        p = run([ts, *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def tailscale_ipv4(run: Run = subprocess.run) -> str | None:
    """This machine's tailnet IPv4, or None when Tailscale is missing, down, or answers anything else."""
    out = _tailscale(["ip", "-4"], run) or ""
    for line in out.split():
        try:
            ip = ipaddress.ip_address(line.strip())
        except ValueError:
            continue
        if ip.version == 4 and ip in TAILNET:
            return str(ip)
    return None


def magicdns_name(run: Run = subprocess.run) -> str | None:
    """This machine's MagicDNS name (host.tailnet.ts.net), or None."""
    try:
        name = json.loads(_tailscale(["status", "--json"], run) or "{}").get("Self", {}).get("DNSName", "")
    except (ValueError, AttributeError):
        return None
    name = name.rstrip(".") if isinstance(name, str) else ""
    return name or None


def check_bind(ip: str) -> str:
    """Only a tailnet address, or loopback for a local check. Anything wider (0.0.0.0, ::, a LAN or public address)
    would publish the demo, so it is refused."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        raise DemoError(f"not an IP address: {ip!r}") from None
    if addr.is_loopback or (addr.version == 4 and addr in TAILNET):
        return str(addr)
    raise DemoError(f"refusing to serve on {ip}: only the tailnet (100.64.0.0/10) or loopback")


# ── serving ─────────────────────────────────────────────────────────────

class Handler(http.server.SimpleHTTPRequestHandler):
    """Static files only: GET and HEAD, no directory listings, the site's own 404 page."""
    server_version = "site-demo"
    sys_version = ""

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def list_directory(self, path):  # a folder without index.html is a 404, never a listing
        self.send_error(404)
        return None

    def send_error(self, code, message=None, explain=None):
        page = Path(self.directory) / "404.html"
        if code == 404 and page.is_file():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{_now()} {self.address_string()} {fmt % args}\n")


def make_server(directory: Path, ip: str, port: int) -> http.server.ThreadingHTTPServer:
    bind = check_bind(ip)
    handler = functools.partial(Handler, directory=str(directory))
    return http.server.ThreadingHTTPServer((bind, port), handler)


def serve(site: str, port: int, run: Run = subprocess.run) -> int:
    ip = tailscale_ipv4(run)
    if not ip:
        # Exit and let the scheduler retry (launchd ThrottleInterval / systemd RestartSec): Tailscale may still be
        # starting after a reboot. Never fall back to a wider address.
        write_status(site, serving=False, error="Tailscale has no IPv4 on this machine; not serving")
        print("site-demo: no Tailscale address; not serving", file=sys.stderr)
        return 1
    current = data_dir(site) / "current"
    current.parent.mkdir(parents=True, exist_ok=True)
    srv = make_server(current, ip, port)
    host = magicdns_name(run) or ip
    write_status(site, serving=True, bind=ip, port=port, url=f"http://{host}:{port}/", serving_since=_now())
    print(f"site-demo: serving {current} on http://{ip}:{port}/ ({host})", file=sys.stderr)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
    return 0


# ── building ────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path, run: Run, timeout: int = 900) -> str:
    p = run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        tail = ((p.stderr or "") + (p.stdout or "")).strip()[-1500:]
        raise DemoError(f"`{' '.join(cmd)}` failed ({p.returncode}): {tail}")
    return p.stdout or ""


def _refuse_engine_checkout(src: Path) -> None:
    if src.resolve() == (home() / ".agents").resolve():
        raise DemoError("the demo checkout can't be the live engine checkout (~/.agents): build resets it hard")


def _swap_current(site: str, built: Path) -> Path:
    """Copy `built` into a new builds/ folder and point `current` at it in one rename. Keeps KEEP_BUILDS."""
    d = data_dir(site)
    builds = d / "builds"
    builds.mkdir(parents=True, exist_ok=True)
    dest = builds / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    shutil.copytree(built, dest)
    tmp = d / "current.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(dest)
    os.replace(tmp, d / "current")
    for old in sorted(p for p in builds.iterdir() if p.is_dir())[:-KEEP_BUILDS]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def build(site: str, branch: str | None = None, run: Run = subprocess.run) -> dict:
    """Fetch `branch` into the demo checkout, build site/, and swap it in. Any failure keeps the last good build
    serving and records why. One build at a time (a lock), so two triggers never interleave."""
    src = src_dir()
    prev = read_status(site)
    branch = branch or prev.get("branch") or DEFAULT_BRANCH
    lock_path = data_dir(site) / "build.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DemoError("another build is running") from None
        try:
            _refuse_engine_checkout(src)
            if not (src / ".git").exists():
                raise DemoError(f"no demo checkout at {src}; clone the engine there first (see the module docstring)")
            if _run(["git", "status", "--porcelain", "--untracked-files=no"], src, run).strip():
                raise DemoError(f"{src} has local edits; it is a build checkout, so nothing should be edited there")
            _run(["git", "fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"], src, run)
            _run(["git", "checkout", "--quiet", "--detach", f"refs/remotes/origin/{branch}"], src, run)
            commit = _run(["git", "rev-parse", "HEAD"], src, run).strip()
            subject = _run(["git", "log", "-1", "--format=%s"], src, run).strip()
            site_dir = src / "site"
            lock_file = site_dir / "package-lock.json"
            lock_hash = hashlib.sha256(lock_file.read_bytes()).hexdigest() if lock_file.is_file() else ""
            if lock_hash != prev.get("lock_hash") or not (site_dir / "node_modules").is_dir():
                _run(["npm", "ci", "--no-audit", "--no-fund"], site_dir, run)
            shutil.rmtree(site_dir / "dist", ignore_errors=True)  # a stale page from the last build must not pass
            _run(["npm", "run", "build"], site_dir, run)
            if not (site_dir / "dist" / "index.html").is_file():
                raise DemoError("the build finished but site/dist/index.html is missing")
            served = _swap_current(site, site_dir / "dist")
        except (DemoError, OSError, subprocess.SubprocessError) as exc:
            return write_status(site, branch=branch, ok=False, error=str(exc)[-2000:], failed_at=_now())
    return write_status(site, branch=branch, ok=True, error=None, commit=commit, commit_subject=subject,
                        built_at=_now(), lock_hash=lock_hash, build_dir=str(served))


def setup(site: str, branch: str) -> dict:
    """Remember the demo branch and install the demo checkout's post-merge hook (a `git pull` there rebuilds)."""
    src = src_dir()
    _refuse_engine_checkout(src)
    hooks = src / ".git" / "hooks"
    if not hooks.is_dir():
        raise DemoError(f"no demo checkout at {src}")
    hook = hooks / "post-merge"
    if hook.exists() and HOOK_MARK not in hook.read_text(errors="replace"):
        raise DemoError(f"{hook} exists and isn't ours; not replacing it")
    hook.write_text(f'#!/bin/sh\n{HOOK_MARK}\nexec "$(git rev-parse --show-toplevel)/bin/site-demo" build --site {site}\n')
    hook.chmod(0o755)
    return write_status(site, branch=branch)


def main(argv: list[str], run: Run = subprocess.run) -> int:
    ap = argparse.ArgumentParser(prog="site-demo", description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["build", "serve", "status", "setup"])
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--branch")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    a = ap.parse_args(argv)
    try:
        if a.command == "serve":
            return serve(a.site, a.port, run)
        if a.command == "status":
            print(json.dumps(read_status(a.site), indent=2))
            return 0
        if a.command == "setup":
            print(json.dumps(setup(a.site, a.branch or DEFAULT_BRANCH), indent=2))
            return 0
        res = build(a.site, a.branch, run)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    except DemoError as exc:
        print(f"site-demo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
