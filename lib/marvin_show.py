#!/usr/bin/env python3
"""marvin show: put one thing in front of Gil, inside MARVIN, in that project's own window (marvin#715).

    marvin-show <file>                         a file in any project's clone, the outbox, or a temp folder
    marvin-show <path> --pr 934 [--repo o/r]   a file on a PR branch (not on main yet), read at the PR's head
    marvin-show <url>                          a web address (a GitHub blob link opens as that file)
    options: --project <id>  --topic <words>  --label <text>  --no-launch  --json

Any session or helper runs it whenever a reply asks Gil to look at something. Never a file card or a temp path.

What it does:
1. A file under /tmp, /private/tmp or /var/folders (a session scratchpad) is copied into
   ~/.claude/outbox/<project>-<YYYY-MM-DD>-<topic>/ first, so nothing Gil is shown lives only in temp. The folder name
   starts with the project's slug, which is how the Docs tab (deliverables.js) files it under that project.
2. It asks the running dashboard to show it: POST http://127.0.0.1:7879/show (the local refresh server, the same one
   the webhook pings). The dashboard opens that project's window, or reuses it, and brings it to the front.
3. The dashboard isn't running: it is started (`open -b`), and the request is sent once it answers.

Exit codes: 0 shown; 2 refused (outside the allowed folders, a secret, gone, too big); 3 the dashboard can't be reached.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

HOME = Path.home()
OUTBOX = HOME / ".claude" / "outbox"
CATALOG_DIR = HOME / ".claude" / "catalog"
TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
BUNDLE_ID = "com.gileskayo.marvin-metrics-dashboard"
DEFAULT_PORT = 7879
# The outbox syncs between the Macs through git (code_sync), and GitHub refuses files over 100 MB: a bigger copy
# would wedge the sync. 50 MB is the largest PDF the viewer opens (outbox.js MAX_PDF_BYTES).
MAX_COPY_BYTES = 50 * 1024 * 1024
# An HTML mock-up brings the folder it sits in (its scripts, styles, images), when that folder is small.
MAX_PAGE_DIR_BYTES = 20 * 1024 * 1024
MAX_PAGE_DIR_FILES = 300
SECRET_NAME = re.compile(r"^(\.env(\..*)?|\.gh-token|\.netrc|\.npmrc|\.pypirc|id_[a-z0-9]+(\.pub)?|.*\.(pem|key|p12|pfx|keychain(-db)?))$", re.I)
SECRET_DIRS = {".ssh", ".gnupg", ".aws"}
GITHUB_BLOB = re.compile(r"^https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)/blob/([A-Za-z0-9._/-]+)$")


class Refused(Exception):
    """A plain reason the item can't be shown (exit 2)."""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def within(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip("/") + "/")


def is_temp(p: str | Path) -> bool:
    s = os.path.abspath(str(p))
    return any(within(s, r) for r in TEMP_ROOTS)


def read_catalog(catalog_dir: Path = CATALOG_DIR) -> list[dict]:
    """Projects from the newest per-machine catalog (lib/project_catalog.py writes it; the dashboard reads the same)."""
    try:
        files = sorted(catalog_dir.glob("projects.*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        return json.loads(files[0].read_text()).get("projects", []) if files else []
    except (OSError, ValueError, IndexError):
        return []


def allowed_roots(projects: list[dict], home: Path = HOME) -> list[str]:
    roots = {str(home / ".claude" / "outbox"), str(home / ".agents"), str(home / "Developer")}
    for p in projects:
        for lp in p.get("localPaths") or []:
            if isinstance(lp, str) and os.path.isabs(lp):
                roots.add(os.path.abspath(lp))
    return sorted(roots)


def project_of_path(p: str, projects: list[dict]) -> str | None:
    """The project whose local clone holds `p` (longest clone wins: ~/.agents/instance before ~/.agents)."""
    best = None
    for proj in projects:
        for lp in proj.get("localPaths") or []:
            if isinstance(lp, str) and within(p, os.path.abspath(lp)) and (best is None or len(lp) > best[1]):
                best = (proj["id"], len(lp))
    return best[0] if best else None


def project_of_repo(repo: str, projects: list[dict]) -> str | None:
    return next((p["id"] for p in projects if str(p.get("repo") or "").lower() == repo.lower()), None)


def repo_of_dir(d: str) -> str | None:
    """owner/name of the git repo at `d` (its origin), or None."""
    try:
        url = subprocess.run(["git", "-C", d, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[:/]([A-Za-z0-9-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def session_project(cwd: str, projects: list[dict]) -> str | None:
    """The project the calling session works in: its folder's clone, else its git origin."""
    real = os.path.realpath(cwd)
    found = project_of_path(real, projects) or project_of_path(cwd, projects)
    if found:
        return found
    repo = repo_of_dir(cwd)
    return project_of_repo(repo, projects) if repo else None


def project_slug(project_id: str, projects: list[dict]) -> str:
    """The slug the outbox folder starts with: the id the Docs tab matches by name (deliverables.js tier 1)."""
    return slug(str(project_id).split(":")[-1]) or "unsorted"


def check_path(p: str, roots: list[str]) -> str:
    """The real path of a file Gil may be shown (temp paths are allowed here: they are copied, never shown)."""
    if "\0" in p:
        raise Refused("Bad path")
    if not os.path.lexists(p):
        raise Refused(f"Not found: {p} (a temp file deleted before it could be copied?)")
    real = os.path.realpath(p)
    if not os.path.exists(real):
        raise Refused(f"Not found: {p}")
    parts = Path(real).parts
    if any(x in SECRET_DIRS for x in parts) or SECRET_NAME.match(os.path.basename(real)):
        raise Refused("That looks like a secret, so it is never shown")
    if os.path.isdir(real):
        raise Refused("Name a file, not a folder")
    if is_temp(real):
        return real
    real_roots = [os.path.realpath(r) for r in roots]
    if not any(within(real, r) for r in real_roots):
        raise Refused("Outside the folders MARVIN shows from (the outbox, ~/.agents, project clones, ~/Developer, or a temp folder)")
    return real


ASSET_REF = re.compile(r"""(?:\bsrc|\bhref)\s*=\s*["']([^"'#?]+)|url\(\s*["']?([^"')#?]+)""", re.I)


def page_assets(page: Path) -> list[str]:
    """The files next to an HTML page that it loads by relative path (scripts, styles, images), so its copy still
    works from the outbox. Only what the page names, never the whole folder (a scratchpad holds unrelated work):
    no scheme, no absolute path, no `..`, no symlink, no secret, regular files only, at most 300 or 20 MB."""
    try:
        text = page.read_text(errors="replace")
    except OSError:
        return []
    out, total = [], 0
    base = page.parent.resolve()
    for m in ASSET_REF.finditer(text):
        ref = (m.group(1) or m.group(2) or "").strip()
        if not ref or re.match(r"^[a-z][a-z0-9+.-]*:", ref, re.I) or ref.startswith(("/", "//")) or "\\" in ref:
            continue
        parts = Path(ref).parts
        if ".." in parts or any(SECRET_NAME.match(x) or x in SECRET_DIRS for x in parts):
            continue
        f = page.parent / ref
        if f.is_symlink() or not f.is_file() or not within(str(f.resolve()), str(base)) or ref in out:
            continue
        total += f.stat().st_size
        if len(out) >= MAX_PAGE_DIR_FILES or total > MAX_PAGE_DIR_BYTES:
            break
        out.append(str(Path(ref)))
    return out


def copy_to_outbox(real: str, project_id: str, topic: str | None, outbox: Path = OUTBOX, today: date | None = None) -> Path:
    """Copy a temp file into ~/.claude/outbox/<project>-<date>-<topic>/ and return the copy's path.

    An HTML page brings the files it names (page_assets), so it still works from the outbox. A name
    already taken by a different file gets -2, -3...; the same file shown twice lands once."""
    src = Path(real)
    try:
        size = src.stat().st_size
    except FileNotFoundError:
        raise Refused(f"Not found: {real} (deleted before it could be copied)") from None
    if size > MAX_COPY_BYTES:
        raise Refused(f"Too big for the outbox ({size // (1024 * 1024)} MB; the limit is {MAX_COPY_BYTES // (1024 * 1024)} MB, "
                      "because the outbox syncs between the Macs through git). Make it smaller, or put it in the project's repo.")
    day = (today or date.today()).isoformat()
    words = slug(topic or src.stem) or "item"
    folder = outbox / f"{project_slug(project_id, [])}-{day}-{words}"[:120]
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if src.suffix.lower() in (".html", ".htm"):
            for rel in page_assets(src):
                d = folder / rel
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src.parent / rel, d)
        dest = folder / src.name
        n = 2
        while dest.exists() and not _same(dest, src):
            dest = folder / f"{src.stem}-{n}{src.suffix}"
            n += 1
        if not dest.exists():
            tmp = dest.with_name(f".{dest.name}.part")
            shutil.copy2(src, tmp)
            tmp.replace(dest)
        return dest
    except FileNotFoundError:
        try:
            folder.rmdir()  # only when nothing landed in it: never leave an empty folder behind
        except OSError:
            pass
        raise Refused(f"Not found: {real} (deleted while it was being copied)") from None


def _same(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def build_request(target: str, *, pr: int | None, repo: str | None, project: str | None, topic: str | None,
                  label: str | None, cwd: str, projects: list[dict], outbox: Path = OUTBOX, today: date | None = None,
                  home: Path = HOME, branch_exists=None) -> tuple[dict, str]:
    """The /show body for what was named, and one line saying what happens. Copies a temp file first."""
    extra = {k: v for k, v in (("label", label),) if v}
    if pr is not None or (repo and not target.startswith(("http://", "https://", "/"))):
        repo = repo or repo_of_dir(cwd)
        if not repo:
            raise Refused("Say which repo the PR is in: --repo owner/name")
        body = {"kind": "pr", "repo": repo, "path": target.removeprefix("./"), **extra}
        if pr is not None:
            body["number"] = pr
        pid = project or project_of_repo(repo, projects) or session_project(cwd, projects)
        if pid:
            body["project"] = pid
        return body, f"{target} on {repo}" + (f" PR #{pr}" if pr is not None else "")
    if target.startswith(("http://", "https://")):
        m = GITHUB_BLOB.match(target)
        if m:
            ref, path = split_blob(m.group(1), m.group(2), projects, branch_exists)
            return {"kind": "pr", "repo": m.group(1), "ref": ref, "path": path, **extra}, target
        pid = project or session_project(cwd, projects)
        return {"kind": "url", "url": target, **({"project": pid} if pid else {}), **extra}, target
    path = os.path.abspath(os.path.join(cwd, os.path.expanduser(target)))
    real = check_path(path, allowed_roots(projects, home))
    if is_temp(real):
        pid = project or session_project(cwd, projects)
        if not pid:
            ids = ", ".join(p["id"] for p in projects[:8])
            raise Refused(f"That file is in a temp folder and this session isn't in a project: say whose it is with --project (e.g. {ids})")
        copy = copy_to_outbox(real, pid, topic, outbox=outbox, today=today)
        body = {"kind": "file", "path": str(copy), "project": pid, "outboxName": copy.relative_to(outbox).parts[0], **extra}
        return body, f"copied to {copy}"
    body = {"kind": "file", "path": real, **extra}
    pid = project or project_of_path(real, projects)
    if pid:
        body["project"] = pid
    return body, real


def split_blob(repo: str, rest: str, projects: list[dict], branch_exists=None) -> tuple[str, str]:
    """A blob URL's "<ref>/<path>" split where the branch really ends: branch names have slashes (design/924), so the
    longest prefix the repo's local clone knows as a branch wins; a commit SHA or an unknown ref is the first part."""
    parts = rest.split("/")
    first = (parts[0], "/".join(parts[1:]))
    if re.fullmatch(r"[0-9a-f]{7,40}", parts[0]) or len(parts) < 3:
        return first
    exists = branch_exists or (lambda ref: _clone_has_branch(repo, ref, projects))
    for n in range(len(parts) - 1, 1, -1):
        ref = "/".join(parts[:n])
        if exists(ref):
            return ref, "/".join(parts[n:])
    return first


def _clone_has_branch(repo: str, ref: str, projects: list[dict]) -> bool:
    pid = project_of_repo(repo, projects)
    clones = next((p.get("localPaths") or [] for p in projects if p["id"] == pid), [])
    for d in clones[:1]:
        try:
            r = subprocess.run(["git", "-C", d, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{ref}"],
                               capture_output=True, timeout=10)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return False


def post_show(body: dict, port: int, timeout: float = 30) -> tuple[int, dict] | None:
    """(status, answer) from the dashboard, or None when nothing answers on the port."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/show", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return None


def launch_dashboard() -> bool:
    try:
        return subprocess.run(["open", "-b", BUNDLE_ID], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def deliver(body: dict, port: int, *, launch: bool = True, post=post_show, start=launch_dashboard,
            sleep=time.sleep, wait_s: float = 60) -> tuple[int, dict]:
    """Send the request; a dashboard that isn't running is started and asked again once it answers (bounded)."""
    got = post(body, port)
    if got is None and launch and start():
        waited = 0.0
        while got is None and waited < wait_s:
            sleep(1.0)
            waited += 1.0
            got = post(body, port)
    if got is None:
        return 3, {"ok": False, "reason": "The dashboard isn't running and couldn't be started" if launch else "The dashboard isn't running"}
    status, answer = got
    if status == 404:
        return 3, {"ok": False, "reason": "The running dashboard is older than marvin show; it needs the update (rebuild) first"}
    return (0 if status == 200 and answer.get("ok") else 2), answer


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="marvin-show", description="Show Gil one thing in its project's MARVIN window.")
    ap.add_argument("target", help="a file path, a repo path with --pr, or a URL")
    ap.add_argument("--pr", type=int, help="the PR whose branch holds the file")
    ap.add_argument("--repo", help="owner/name (default: this folder's repo)")
    ap.add_argument("--project", help="the project it belongs to (default: this folder's project)")
    ap.add_argument("--topic", help="words for the outbox folder name (default: the file's name)")
    ap.add_argument("--label", help="the title shown in the window")
    ap.add_argument("--no-launch", action="store_true", help="don't start the dashboard if it isn't running")
    ap.add_argument("--json", action="store_true", help="print the answer as JSON")
    a = ap.parse_args(argv)
    port_env = os.environ.get("MARVIN_DASHBOARD_REFRESH_PORT", "")
    port = int(port_env) if port_env.isdigit() and 0 < int(port_env) < 65536 else DEFAULT_PORT
    projects = read_catalog()
    try:
        body, what = build_request(a.target, pr=a.pr, repo=a.repo, project=a.project, topic=a.topic, label=a.label,
                                   cwd=os.getcwd(), projects=projects)
    except Refused as e:
        print(f"marvin show: {e}", file=sys.stderr)
        return 2
    code, answer = deliver(body, port, launch=not a.no_launch)
    if a.json:
        print(json.dumps({**answer, "request": body}))
    elif code == 0:
        print(f"Shown in the {answer.get('projectName') or answer.get('project')} window ({answer.get('window')}): {answer.get('label')}"
              + (f"\n  {what}" if what.startswith("copied") else ""))
    else:
        print(f"marvin show: {answer.get('reason') or 'not shown'}", file=sys.stderr)
        if body.get("kind") == "file":
            print(f"  the file: {body['path']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
