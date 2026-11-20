#!/usr/bin/env python3
"""Cold store: park big folders nobody is using on the cold host, and get them back the moment something needs them
(marvin#1081, storage plan section 5: placement by role, not striping).

The cold host (config/cold_store.json, a registry id; today mac-mini-2012) has the disk the Macs keep running out of.
`park PATH` moves a folder there and leaves a small **marker** folder at the old path: PARKED.txt for people and
.marvin-cold.json for code. `ensure PATH` is what callers run before they read the folder, every time: when the data
is local it returns at once, and when the marker is there it fetches the data back, checks every byte, and returns.
Nothing polls and nothing runs on a timer: data comes back because a caller asked for it.

Layout on the cold host, under `root` (relative to that machine's home, so no home path or user is named here):
    <root>/<name>/data/...        the folder, byte for byte (rsync -a)
    <root>/<name>/entry.json      one line: what it is, where it came from, when, how big, the manifest's sha256
    <root>/<name>/manifest.json   every file's size and sha256, every symlink's target
The parking machine keeps its own copy of the entry and manifest in var/cold-store/<name>.json. That copy is the one
trusted on the way back: the cold host runs untrusted code in VMs (ADR 0069), so bytes fetched from it are checked
against a manifest that never lived only there. A marker records the manifest's sha256 too, so a lost catalog still
leaves a trusted check. Folders that hold secrets (~/.claude, ~/.agents, ~/.ssh, ~/Library, ...) are refused.

park:   hash (O(B) time, O(F) memory for F files, B bytes) -> rsync up, resumable (--partial) -> hash on the cold host
        (O(B) there) -> compare; on a mismatch one --checksum repair pass and compare again -> write the entry ->
        re-stat the folder (anything written since the hash aborts) -> swap the folder for the marker with two
        renames on one filesystem -> delete. Until the swap nothing local is touched, so an interrupted park is
        simply run again: rsync resumes where it stopped.
ensure: no marker -> return (O(1): one stat, one exists check). Marker -> take a per-name lock (two callers never
        fetch twice; the second waits, then finds the data there) -> sizes already present (O(F_part) stats) ->
        free space check before any byte moves -> reachability (calm message when the cold host is asleep or off)
        -> rsync -c down -> sha256 every fetched file against the trusted manifest (O(B_part)) -> drop the marker
        (whole folder) or record the part (--part SUB).

Exit codes for scripts: 0 ok, 2 not parked / bad input, 3 cold host unreachable, 4 not enough free space,
5 verification failed, 6 folder in use or changed while parking, 7 a copy stopped part way (run again).

Usage: marvin-cold park PATH [--name NAME]       (again on a parked folder: parks what came back, marvin#1271)
       marvin-cold ensure PATH|NAME [--part SUB] [--optional] [--min-free-gb N]   (prints the local path)
       marvin-cold ensure PATH|NAME [--part SUB] --then-park -- COMMAND [ARGS...]  (fetch, run, park again)
       marvin-cold list            (alias: where) what is parked, sizes, free space on every machine
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE.parent / "config" / "cold_store.json"
STATE_DIR = Path(os.environ.get("MARVIN_COLD_STATE") or Path.home() / ".agents" / "var" / "cold-store")  # per machine
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new"]
MARKER_JSON = ".marvin-cold.json"
MARKER_TXT = "PARKED.txt"
# Home-relative folders that hold secrets or MARVIN's own state: never sent to a box that runs untrusted code.
REFUSED = (".claude", ".agents", ".ssh", ".gnupg", ".aws", ".config", ".netrc", "Library", ".docker", ".kube")

OK, NOT_PARKED, UNREACHABLE, NO_SPACE, VERIFY_FAILED, BUSY, COPY_STOPPED = 0, 2, 3, 4, 5, 6, 7
UNREACHABLE_HINTS = re.compile(r"Host is down|Connection refused|Connection timed out|Operation timed out|No route to "
                               r"host|Could not resolve|Network is unreachable", re.I)


class ColdError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(name: str) -> str:
    """A name safe in a remote path with no quoting: letters, digits, dot, dash, underscore."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    if not s:
        raise ColdError(NOT_PARKED, f"can't make a cold-store name from {name!r}; pass --name")
    return s


def build_manifest(folder):
    """Every regular file's [size, sha256] and every symlink's target, keyed by path relative to folder.
    O(B) time, O(F) memory. Also runs on the cold host (sent over ssh), so it uses nothing outside this body."""
    import hashlib, os
    files, links = {}, {}
    for base, dirs, names in os.walk(folder):
        for d in list(dirs):
            p = os.path.join(base, d)
            if os.path.islink(p):
                links[os.path.relpath(p, folder)] = os.readlink(p)
                dirs.remove(d)
        for n in names:
            p = os.path.join(base, n)
            rel = os.path.relpath(p, folder)
            if os.path.islink(p):
                links[rel] = os.readlink(p)
                continue
            if not os.path.isfile(p):
                continue
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            files[rel] = [os.path.getsize(p), h.hexdigest()]
    return {"files": files, "links": links}


REMOTE_MANIFEST_PY = inspect.getsource(build_manifest) + (
    "\nimport json, sys\nprint(json.dumps(build_manifest(sys.argv[1]), sort_keys=True))\n")


def stat_snapshot(folder: Path) -> dict:
    """(size, mtime_ns) for every file and the target of every link: O(F) stats, no reads. A folder written to while
    it was being parked shows up as a difference here."""
    out = {}
    for base, dirs, names in os.walk(folder):
        for n in names + [d for d in dirs if os.path.islink(os.path.join(base, d))]:
            p = os.path.join(base, n)
            st = os.lstat(p)
            out[os.path.relpath(p, folder)] = (st.st_size, st.st_mtime_ns)
    return out


MARKER_NAMES = (MARKER_JSON, MARKER_JSON + ".tmp", MARKER_TXT)


def _snapshot_without_marker(folder: Path) -> dict:
    return {k: v for k, v in stat_snapshot(folder).items() if k not in MARKER_NAMES}


def _local_entries(folder: Path) -> list[str]:
    """Top-level names in a parked folder other than its marker: anything here means data came back."""
    try:
        return sorted(n for n in os.listdir(folder) if n not in MARKER_NAMES)
    except OSError:
        return []


def local_bytes(folder: Path) -> int:
    """Bytes of regular files under folder, its marker left out. O(F) stats."""
    total = 0
    for base, dirs, names in os.walk(folder):
        for n in names:
            p = os.path.join(base, n)
            if base == str(folder) and n in MARKER_NAMES:
                continue
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not os.path.islink(p):
                total += st.st_size
    return total


def manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


def manifest_sha(manifest: dict) -> str:
    return hashlib.sha256(manifest_bytes(manifest)).hexdigest()


def compare(want: dict, have: dict, under: str | None = None) -> list[str]:
    """What differs between two manifests, limited to the part `under` when given. Empty list = identical."""
    def sel(d: dict) -> dict:
        if not under:
            return d
        pre = under.rstrip("/") + "/"
        return {k: v for k, v in d.items() if k == under or k.startswith(pre)}
    problems = []
    for kind in ("files", "links"):
        w, h = sel(want.get(kind, {})), sel(have.get(kind, {}))
        problems += [f"missing {k}" for k in sorted(set(w) - set(h))]
        problems += [f"unexpected {k}" for k in sorted(set(h) - set(w))]
        problems += [f"differs {k}" for k in sorted(set(w) & set(h)) if w[k] != h[k]]
    return problems


def local_manifest(path: Path, part: str | None = None) -> dict:
    """The manifest of path, or of just `part` of it (a sub-folder or one file), keyed relative to path. O(B_part)."""
    if not part:
        here = build_manifest(str(path))
        for extra in MARKER_NAMES:
            here["files"].pop(extra, None)
        return here
    target = path / part
    if target.is_symlink():
        return {"files": {}, "links": {part: os.readlink(target)}}
    if target.is_file():
        h = hashlib.sha256()
        with open(target, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return {"files": {part: [target.stat().st_size, h.hexdigest()]}, "links": {}}
    if not target.is_dir():
        return {"files": {}, "links": {}}
    sub = build_manifest(str(target))
    return {k: {f"{part}/{r}": v for r, v in d.items()} for k, d in sub.items()}


def home_relative(path: Path, home: Path) -> str:
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def from_home_relative(origin: str, home: Path) -> Path:
    return home / origin[2:] if origin.startswith("~/") else Path(origin)


def _rsync_old_args(rsync: str) -> bool:
    """openrsync (macOS) and rsync before 3.0 pass remote paths through the remote shell, so they need quoting.
    Real rsync 3.x takes -s (protect-args) and must not be quoted on top."""
    try:
        first = subprocess.run([rsync, "--version"], capture_output=True, text=True, timeout=10).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return True
    line = first[0] if first else ""
    if "openrsync" in line:
        return True
    m = re.search(r"version\s+(\d+)", line)
    return not (m and int(m.group(1)) >= 3)


def free_bytes(path: Path) -> int:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def files_in_use(path: Path) -> list[str]:
    """Processes with a file open under path (lsof +D). lsof exits 1 when there are none. Missing lsof = unknown,
    reported as in use so nothing is deleted on a guess."""
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    try:
        r = subprocess.run([lsof, "-n", "-P", "+D", str(path)], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        return [f"lsof could not run: {e}"]
    if r.returncode == 1 and not r.stdout.strip():
        return []
    rows = r.stdout.strip().splitlines()[1:]
    return sorted({" ".join(row.split()[:2]) for row in rows}) or [f"lsof exit {r.returncode}: {r.stderr.strip()[:200]}"]


@dataclass
class Store:
    host: str                      # ssh target of the cold host
    host_id: str                   # its registry id, for messages and entries
    root: str                      # where parked data lives on the cold host (relative to its home)
    machine: str                   # this machine's registry id
    state_dir: Path = STATE_DIR
    home: Path = field(default_factory=Path.home)
    ssh: list[str] = field(default_factory=lambda: ["ssh", *SSH_OPTS])
    rsync: str = "rsync"
    min_free_bytes: int = 15 * 10**9
    free: Callable[[Path], int] = free_bytes
    in_use: Callable[[Path], list[str]] = files_in_use
    say: Callable[[str], None] = lambda m: print(m, file=sys.stderr, flush=True)

    # ---- the cold host ---------------------------------------------------------------------------------------
    def _remote(self, command: str, stdin: bytes | None = None, timeout: float = 3600) -> subprocess.CompletedProcess:
        try:
            r = subprocess.run([*self.ssh, self.host, command], input=stdin, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ColdError(UNREACHABLE, f"the cold host {self.host_id} stopped answering ({timeout:.0f} s)")
        if r.returncode == 255:
            raise ColdError(UNREACHABLE, self._unreachable_msg(r.stderr.decode(errors="replace")))
        return r

    def _unreachable_msg(self, detail: str = "") -> str:
        d = detail.strip().splitlines()[-1][:160] if detail.strip() else ""
        return (f"the cold host {self.host_id} isn't reachable (asleep or off?). Nothing was changed; wake it and run "
                f"this again." + (f" ssh said: {d}" if d else ""))

    def reachable(self) -> None:
        self._remote("true", timeout=30)

    def _rpath(self, name: str, *parts: str) -> str:
        return "/".join([self.root.rstrip("/"), name, *[p.strip("/") for p in parts if p]])

    def _spec(self, rpath: str) -> str:
        return f"{self.host}:{shlex.quote(rpath) if self._old_args else rpath}"

    @property
    def _old_args(self) -> bool:
        if not hasattr(self, "_old_args_cache"):
            self._old_args_cache = _rsync_old_args(self.rsync)
        return self._old_args_cache

    def _rsync(self, src: str, dst: str, *flags: str) -> None:
        cmd = [self.rsync, "-a", "--partial", *flags, "-e", " ".join(shlex.quote(a) for a in self.ssh)]
        if not self._old_args:
            cmd.append("-s")
        r = subprocess.run([*cmd, src, dst], capture_output=True, text=True)
        if r.returncode == 0:
            return
        if r.returncode == 255 or UNREACHABLE_HINTS.search(r.stderr):
            raise ColdError(UNREACHABLE, self._unreachable_msg(r.stderr))
        raise ColdError(COPY_STOPPED, f"rsync stopped (exit {r.returncode}); nothing local was removed, run again to "
                                      f"resume: {r.stderr.strip()[-300:]}")

    def remote_manifest(self, name: str) -> dict:
        r = self._remote(f"python3 - {shlex.quote(self._rpath(name, 'data'))}", stdin=REMOTE_MANIFEST_PY.encode())
        if r.returncode != 0:
            raise ColdError(VERIFY_FAILED, f"couldn't hash the copy on {self.host_id}: {r.stderr.decode()[-300:]}")
        return json.loads(r.stdout)

    def remote_entries(self) -> list[dict]:
        r = self._remote(f"cat {shlex.quote(self.root)}/*/entry.json 2>/dev/null; true", timeout=60)
        out = []
        for line in r.stdout.decode(errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def remote_entry(self, name: str) -> dict | None:
        r = self._remote(f"cat {shlex.quote(self._rpath(name, 'entry.json'))} 2>/dev/null; true", timeout=60)
        try:
            return json.loads(r.stdout) if r.stdout.strip() else None
        except ValueError:
            return None

    def _remote_write(self, rpath: str, data: bytes) -> None:
        tmp = f"{rpath}.tmp"
        r = self._remote(f"cat > {shlex.quote(tmp)} && mv {shlex.quote(tmp)} {shlex.quote(rpath)}", stdin=data)
        if r.returncode != 0:
            raise ColdError(VERIFY_FAILED, f"couldn't write {rpath} on {self.host_id}: {r.stderr.decode()[-200:]}")

    # ---- the local catalog -----------------------------------------------------------------------------------
    def _catalog_path(self, name: str) -> Path:
        return self.state_dir / f"{name}.json"

    def catalog(self, name: str) -> dict | None:
        try:
            return json.loads(self._catalog_path(name).read_text())
        except (OSError, ValueError):
            return None

    def catalog_all(self) -> list[dict]:
        out = []
        for p in sorted(self.state_dir.glob("*.json")) if self.state_dir.is_dir() else []:
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
        return out

    def _save_catalog(self, name: str, record: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._catalog_path(name).with_suffix(".tmp")
        tmp.write_text(json.dumps(record, sort_keys=True))
        os.replace(tmp, self._catalog_path(name))

    # ---- markers ---------------------------------------------------------------------------------------------
    @staticmethod
    def marker(path: Path) -> dict | None:
        try:
            return json.loads((path / MARKER_JSON).read_text())
        except (OSError, ValueError):
            return None

    def _write_marker(self, folder: Path, entry: dict, parts: list[str]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / (MARKER_JSON + ".tmp")
        tmp.write_text(json.dumps({**entry, "parts": parts}, sort_keys=True))
        os.replace(tmp, folder / MARKER_JSON)
        gb = entry["bytes"] / 1e9
        (folder / MARKER_TXT).write_text(
            f"This folder was parked in MARVIN's cold store on {entry['host']} on {entry['parked_at']} "
            f"({gb:.1f} GB, {entry['files']} files) to free disk on {entry['origin_machine']}.\n\n"
            f"Get it back (checks every file):\n    ~/.agents/bin/marvin-cold ensure {entry['origin_path']}\n"
            f"Only one sub-folder:\n    ~/.agents/bin/marvin-cold ensure {entry['origin_path']} --part SUB/FOLDER\n"
            f"What is parked:\n    ~/.agents/bin/marvin-cold list\n")

    # ---- lock ------------------------------------------------------------------------------------------------
    def _lock(self, name: str):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        f = open(self.state_dir / f"{name}.lock", "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.say(f"waiting: another caller is already moving {name}")
            fcntl.flock(f, fcntl.LOCK_EX)
        return f

    # ---- park ------------------------------------------------------------------------------------------------
    def park(self, path: Path, name: str | None = None) -> dict:
        """Move a folder to the cold host and leave a marker. Idempotent: an already parked folder returns its entry.
        Time O(B) (hash here, copy, hash there), memory O(F)."""
        path = Path(os.path.abspath(os.path.expanduser(str(path))))
        if self.machine == self.host_id:
            raise ColdError(NOT_PARKED, "this machine is the cold host; park from the machine that owns the folder")
        existing = self.marker(path)
        if existing:
            self._finish_swap(path)
            if not _local_entries(path):
                return existing                                        # nothing came back: nothing to do, no network
            return self._repark(path, existing)
        if path.is_symlink() or not path.is_dir():
            raise ColdError(NOT_PARKED, f"{path} is not a folder")
        rel = home_relative(path, self.home)
        if path == self.home or any(rel == f"~/{r}" or rel.startswith(f"~/{r}/") for r in REFUSED):
            raise ColdError(NOT_PARKED, f"{rel} may hold secrets or MARVIN's own state; the cold host runs untrusted "
                                        f"code (ADR 0069), so it is never parked there")
        if (path / MARKER_JSON).exists() or (path / MARKER_TXT).exists():
            raise ColdError(NOT_PARKED, f"{path} already holds a {MARKER_JSON} or {MARKER_TXT}; refusing to guess")
        name = slug(name or path.name)
        with self._lock(name):
            prior = self.remote_entry(name)
            if prior and (prior.get("origin_machine"), prior.get("origin_path")) != (self.machine, rel):
                raise ColdError(NOT_PARKED, f"the cold store already has {name!r} from {prior.get('origin_machine')}:"
                                            f"{prior.get('origin_path')}; pick another --name")
            busy = self.in_use(path)
            if busy:
                raise ColdError(BUSY, f"{path} is in use, nothing was moved: {', '.join(busy[:5])}")
            self.say(f"hashing {path}")
            snap = stat_snapshot(path)
            manifest = build_manifest(str(path))
            total = sum(s for s, _ in manifest["files"].values())
            self.say(f"copying {total / 1e9:.2f} GB to {self.host_id}")
            r = self._remote(f"mkdir -p {shlex.quote(self._rpath(name, 'data'))}", timeout=60)
            if r.returncode != 0:
                raise ColdError(VERIFY_FAILED, f"couldn't create the folder on {self.host_id}: {r.stderr.decode()}")
            dst = self._spec(self._rpath(name, "data") + "/")
            self._rsync(f"{path}/", dst, "--delete")
            problems = compare(manifest, self.remote_manifest(name))
            if problems:
                self.say(f"{len(problems)} file(s) differ on {self.host_id}; one repair pass with --checksum")
                self._rsync(f"{path}/", dst, "--delete", "--checksum")
                problems = compare(manifest, self.remote_manifest(name))
            if problems:
                raise ColdError(VERIFY_FAILED, f"the copy on {self.host_id} doesn't match, nothing local was removed: "
                                               f"{'; '.join(problems[:5])}")
            entry = {"name": name, "host": self.host_id, "root": self.root, "origin_machine": self.machine,
                     "origin_path": rel, "parked_at": _now(), "bytes": total, "files": len(manifest["files"]),
                     "links": len(manifest["links"]), "manifest_sha256": manifest_sha(manifest)}
            self._remote_write(self._rpath(name, "manifest.json"), manifest_bytes(manifest))
            self._remote_write(self._rpath(name, "entry.json"), json.dumps(entry, sort_keys=True).encode() + b"\n")
            self._save_catalog(name, {**entry, "state": "parked", "manifest": manifest})
            if stat_snapshot(path) != snap:
                raise ColdError(BUSY, f"{path} changed while it was being parked; nothing local was removed. Run again "
                                      f"when nothing is writing to it.")
            busy = self.in_use(path)
            if busy:
                raise ColdError(BUSY, f"{path} came into use while parking, nothing local was removed: {busy[:5]}")
            self._swap(path, entry)
            self.say(f"parked {rel} on {self.host_id}: {total / 1e9:.2f} GB, {len(manifest['files'])} files verified")
            return entry

    def _repark(self, path: Path, marker: dict) -> dict:
        """Park again a folder that still has its marker but holds data again: parts `ensure --part` fetched back, or
        files written next to the marker (marvin#1271). The trusted manifest plus what is local now makes the new
        manifest: local files and links win (new or changed), a file inside a fetched part that is gone locally is
        deleted, and every file that never came back is kept. Only then is the cold copy brought to match it (rsync
        up without --delete, then remove what the new manifest no longer has) and hashed there, so nothing local is
        dropped unless the cold copy holds every byte of the new manifest.
        Write order keeps every crash readable: cold data -> cold manifest.json (the sha is first noted in the catalog
        as pending, so the next park accepts it) -> entry.json -> local marker -> catalog -> swap. A marker always
        names a sha that either the catalog or the cold manifest.json holds, so `ensure` can verify at every step.
        Time O(B_local) here + O(B) hashing on the cold host, memory O(F)."""
        name = marker["name"]
        with self._lock(name):
            busy = self.in_use(path)
            if busy:
                raise ColdError(BUSY, f"{path} is in use, nothing was moved: {', '.join(busy[:5])}")
            old_entry = {k: v for k, v in marker.items() if k != "parts"}
            base = self._trusted_manifest(old_entry)
            rec = self.catalog(name) or {}
            accepted = {marker.get("manifest_sha256"), rec.get("pending_manifest_sha256")} - {None}
            cold_sha = self._remote_manifest_sha(name)
            if cold_sha not in accepted:
                raise ColdError(VERIFY_FAILED, f"the manifest for {name} on {self.host_id} doesn't match the one this "
                                               f"folder's marker names; nothing local was removed. Look at it by hand.")
            snap = _snapshot_without_marker(path)
            self.say(f"hashing what is back in {path}")
            here = local_manifest(path)
            fetched = marker.get("parts", [])

            def was_fetched(rel: str) -> bool:
                return any(rel == p or rel.startswith(p + "/") for p in fetched)
            new = {"files": dict(base["files"]), "links": dict(base["links"])}
            local_paths = set(here["files"]) | set(here["links"])
            for kind in ("files", "links"):
                for rel in list(new[kind]):
                    if was_fetched(rel) and rel not in local_paths:
                        del new[kind][rel]                             # deleted after it came back
            for rel, v in here["files"].items():
                new["links"].pop(rel, None)
                new["files"][rel] = v
            for rel, v in here["links"].items():
                new["files"].pop(rel, None)
                new["links"][rel] = v
            sha = manifest_sha(new)
            changed = sha != marker.get("manifest_sha256")
            total = sum(s for s, _ in new["files"].values())
            self.say(f"bringing the copy of {name} on {self.host_id} up to date")
            dst = self._spec(self._rpath(name, "data") + "/")
            excl = [f"--exclude=/{MARKER_JSON}", f"--exclude=/{MARKER_JSON}.tmp", f"--exclude=/{MARKER_TXT}"]
            self._rsync(f"{path}/", dst, *excl)
            problems = self._match_cold(name, new)
            if problems:
                self.say(f"{len(problems)} file(s) differ on {self.host_id}; one repair pass with --checksum")
                self._rsync(f"{path}/", dst, *excl, "--checksum")
                problems = self._match_cold(name, new)
            if problems:
                raise ColdError(VERIFY_FAILED, f"the copy on {self.host_id} doesn't match, nothing local was removed: "
                                               f"{'; '.join(problems[:5])}")
            entry = {**old_entry, "bytes": total, "files": len(new["files"]), "links": len(new["links"]),
                     "manifest_sha256": sha}
            if changed:
                entry["reparked_at"] = _now()
                self._save_catalog(name, {**rec, "pending_manifest_sha256": sha})
                self._remote_write(self._rpath(name, "manifest.json"), manifest_bytes(new))
                self._remote_write(self._rpath(name, "entry.json"), json.dumps(entry, sort_keys=True).encode() + b"\n")
                self._write_marker(path, entry, fetched)
            record = {k: v for k, v in rec.items() if k != "pending_manifest_sha256"}
            self._save_catalog(name, {**record, **entry, "state": "parked", "manifest": new, "parts": []})
            if _snapshot_without_marker(path) != snap:
                raise ColdError(BUSY, f"{path} changed while it was being parked; nothing local was removed. Run again "
                                      f"when nothing is writing to it.")
            busy = self.in_use(path)
            if busy:
                raise ColdError(BUSY, f"{path} came into use while parking, nothing local was removed: {busy[:5]}")
            self._swap(path, entry)
            self.say(f"parked {name} again on {self.host_id}: {total / 1e9:.2f} GB, {len(new['files'])} files verified")
            return entry

    def _remote_manifest_sha(self, name: str) -> str | None:
        r = self._remote(f"cat {shlex.quote(self._rpath(name, 'manifest.json'))}")
        if r.returncode != 0:
            return None
        try:
            return manifest_sha(json.loads(r.stdout))
        except ValueError:
            return None

    def _match_cold(self, name: str, want: dict) -> list[str]:
        """Hash the cold copy, remove what `want` no longer has (files deleted locally, leftovers of an interrupted
        run), and return what still differs. Removal happens only inside this entry's data folder."""
        have = self.remote_manifest(name)
        extra = sorted((set(have["files"]) - set(want["files"])) | (set(have["links"]) - set(want["links"])))
        extra = [p for p in extra if p not in want["files"] and p not in want["links"]]
        if extra:
            data = self._rpath(name, "data")
            r = self._remote(f"cd {shlex.quote(data)} && xargs -0 rm -f --", stdin="\0".join(extra).encode())
            if r.returncode != 0:
                return [f"couldn't remove {len(extra)} old file(s): {r.stderr.decode()[-200:]}"]
            have = {k: {p: v for p, v in d.items() if p not in extra} for k, d in have.items()}
        return compare(want, have)

    @contextmanager
    def fetched(self, target: str, part: str | None = None, optional: bool = False,
                min_free_bytes: int | None = None):
        """`with store.fetched(path, part=...) as p:` ensures the data, runs the block, then parks the whole folder
        again, even when the block fails, so a job's fetch never keeps the disk. A folder that was never parked is
        left alone. A park failure after a failed block is reported and the block's own error is raised."""
        root, entry, _ = self._resolve(target, optional)
        got = self.ensure(target, part, optional, min_free_bytes)
        was_cold = got is not None and (entry is not None or self.marker(root) is not None)
        try:
            yield got
        except BaseException:
            if was_cold:
                try:
                    self.park(root, (entry or {}).get("name"))
                except ColdError as err:
                    self.say(f"couldn't park {root} again: {err}")
            raise
        if was_cold:
            self.park(root, (entry or {}).get("name"))

    def _trash(self, path: Path) -> Path:
        return path.parent / f".{path.name}.cold-trash"

    def _swap(self, path: Path, entry: dict) -> None:
        """Folder -> marker with two renames on one filesystem, then delete the old folder. If this stops halfway,
        the marker is already in place and _finish_swap removes the leftover on the next park or ensure."""
        stage = path.parent / f".{path.name}.cold-marker"
        shutil.rmtree(stage, ignore_errors=True)
        self._write_marker(stage, entry, [])
        trash = self._trash(path)
        if trash.exists():
            raise ColdError(BUSY, f"{trash} is in the way from an earlier run; look at it and remove it by hand")
        os.rename(path, trash)
        os.rename(stage, path)
        self._finish_swap(path)

    def _finish_swap(self, path: Path) -> None:
        trash = self._trash(path)
        if trash.exists() and self.marker(path):
            shutil.rmtree(trash)

    # ---- ensure ----------------------------------------------------------------------------------------------
    def _resolve(self, target: str, optional: bool = False) -> tuple[Path, dict | None, str | None]:
        """A path (the parked folder or anything inside it) or a name -> (the parked folder's local path, its entry or
        None, the path inside it that was asked for or None). O(depth) stats when a marker or the data is here; one
        ssh call only when the path is missing and only the cold host can know it (parked from another machine)."""
        looks_like_path = "/" in target or target.startswith("~") or target.startswith(".")
        if not looks_like_path:
            rec = self.catalog(slug(target)) or self.remote_entry(slug(target))
            if not rec:
                return Path(target), None, None
            path = from_home_relative(rec["origin_path"], self.home)
            return path, (self.marker(path) or rec), None
        path = Path(os.path.abspath(os.path.expanduser(target)))
        for anc in [path, *path.parents]:
            m = self.marker(anc)
            if m:
                inner = str(path.relative_to(anc))
                return anc, m, None if inner == "." else inner
            if anc == self.home:
                break
        if path.exists():
            return path, None, None                                    # here, and never parked
        rel = home_relative(path, self.home)

        def match(rec: dict) -> tuple[Path, dict, str | None] | None:
            origin = (rec.get("origin_path") or "").rstrip("/")
            if origin and (rel == origin or rel.startswith(origin + "/")):
                return from_home_relative(origin, self.home), rec, rel[len(origin) + 1:] or None
            return None
        for rec in self.catalog_all():
            if match(rec):
                return match(rec)
        try:
            remote = self.remote_entries()
        except ColdError as err:
            if not optional:
                raise
            self.say(f"{target} isn't here and {err}")
            return path, None, None
        for e in remote:
            if match(e):
                return match(e)
        return path, None, None

    def _trusted_manifest(self, entry: dict) -> dict:
        want = entry.get("manifest_sha256")
        rec = self.catalog(entry["name"])
        if rec and rec.get("manifest") and manifest_sha(rec["manifest"]) == want:
            return rec["manifest"]
        r = self._remote(f"cat {shlex.quote(self._rpath(entry['name'], 'manifest.json'))}")
        if r.returncode != 0:
            raise ColdError(VERIFY_FAILED, f"no manifest for {entry['name']} on {self.host_id}: {r.stderr.decode()}")
        manifest = json.loads(r.stdout)
        if want and manifest_sha(manifest) != want:
            raise ColdError(VERIFY_FAILED, f"the manifest for {entry['name']} on {self.host_id} doesn't match the "
                                           f"sha256 recorded when it was parked; not trusting it")
        self._save_catalog(entry["name"], {**{k: v for k, v in entry.items() if k != "parts"},
                                           "state": "parked", "manifest": manifest})
        return manifest

    def _present(self, path: Path, manifest: dict, part: str | None) -> tuple[int, int]:
        """(bytes still needed, files whose size is already right) for the selection. O(F_part) stats."""
        need, have = 0, 0
        pre = part.rstrip("/") + "/" if part else ""
        for rel, (size, _) in manifest["files"].items():
            if pre and not (rel.startswith(pre) or rel == part):
                continue
            p = path / rel
            try:
                if p.is_file() and not p.is_symlink() and p.stat().st_size == size:
                    have += 1
                    continue
            except OSError:
                pass
            need += size
        return need, have

    def ensure(self, target: str, part: str | None = None, optional: bool = False,
               min_free_bytes: int | None = None) -> Path | None:
        """The local path of target with its data (or just `part` of it) present and verified. Safe to call on every
        run: a local folder with no marker returns at once without touching the network."""
        if part:
            part = part.strip("/")
            if part.startswith("..") or "/../" in f"/{part}/" or os.path.isabs(part):
                raise ColdError(NOT_PARKED, f"--part must be a sub-folder, got {part!r}")
        path, entry, inner = self._resolve(target, optional)
        if inner:
            part = f"{inner}/{part}" if part else inner
        if entry is None or (path.is_dir() and not self.marker(path)):
            if path.is_dir() and not self.marker(path):
                return path / part if part else path
            if optional:
                self.say(f"{target}: not parked and not here; nothing to fetch")
                return None
            raise ColdError(NOT_PARKED, f"{target} isn't here and isn't in the cold store")
        name = entry["name"]
        with self._lock(name):
            m = self.marker(path)
            if path.is_dir() and not m:
                return path / part if part else path       # another caller finished while we waited
            if m and part and any(part == p or part.startswith(p + "/") for p in m.get("parts", [])):
                return path / part
            entry = m or entry
            manifest = self._trusted_manifest(entry)
            if part and not any(r == part or r.startswith(part + "/") for r in [*manifest["files"], *manifest["links"]]):
                raise ColdError(NOT_PARKED, f"{name} has no {part!r}")
            need, _ = self._present(path, manifest, part)
            floor = self.min_free_bytes if min_free_bytes is None else min_free_bytes
            free = self.free(path)
            if need and free - need < floor:
                raise ColdError(NO_SPACE, f"fetching {name}{'/' + part if part else ''} needs {need / 1e9:.2f} GB and "
                                          f"would leave {(free - need) / 1e9:.2f} GB free, under the {floor / 1e9:.0f} GB "
                                          f"floor. Free some space, fetch less with --part, or pass --min-free-gb.")
            self.reachable()
            if not m:
                self._write_marker(path, entry, [])
            self.say(f"fetching {need / 1e9:.2f} GB of {name}{'/' + part if part else ''} from {self.host_id}")
            src = self._rpath(name, "data", part or "")
            if part and part in manifest["files"]:
                (path / part).parent.mkdir(parents=True, exist_ok=True)
                self._rsync(self._spec(src), str(path / part), "--checksum")
            else:
                (path / (part or "")).mkdir(parents=True, exist_ok=True)
                self._rsync(self._spec(src + "/"), f"{path / part if part else path}/", "--checksum")
            here = local_manifest(path, part)
            problems = compare(manifest, here, under=part)
            if problems:
                raise ColdError(VERIFY_FAILED, f"{name} fetched from {self.host_id} doesn't match its manifest; it "
                                               f"stays parked: {'; '.join(problems[:5])}")
            rec = self.catalog(name) or {**entry, "manifest": manifest}
            if part:
                parts = sorted(set((m or {}).get("parts", []) + [part]))
                self._write_marker(path, entry, parts)
                self._save_catalog(name, {**rec, "state": "parked", "parts": parts})
            else:
                for extra in (MARKER_JSON, MARKER_TXT):
                    (path / extra).unlink(missing_ok=True)
                self._save_catalog(name, {**rec, "state": "restored", "restored_at": _now(), "parts": []})
            self.say(f"{name}{'/' + part if part else ''} is back and verified ({need / 1e9:.2f} GB fetched)")
            return path / part if part else path

    # ---- list ------------------------------------------------------------------------------------------------
    def listing(self, devices: dict[str, str] | None = None) -> dict:
        """What is parked (the cold host's view when it answers, else this machine's catalog) and free GB on each
        machine. One ssh call per machine."""
        out = {"host": self.host_id, "reachable": True, "parked": [], "free_gb": {}}
        try:
            out["parked"] = self.remote_entries()
        except ColdError:
            out["reachable"] = False
            out["parked"] = [{k: v for k, v in r.items() if k != "manifest"} for r in self.catalog_all()]
        for rec in self.catalog_all():
            for e in out["parked"]:
                if e.get("name") == rec.get("name") and rec.get("origin_machine") == self.machine:
                    e["here"] = rec.get("state")
        for e in out["parked"]:
            if e.get("origin_machine") == self.machine and e.get("origin_path"):
                folder = from_home_relative(e["origin_path"], self.home)
                e["local_bytes"] = local_bytes(folder) if folder.is_dir() and not folder.is_symlink() else 0
        out["free_gb"][self.machine] = round(shutil.disk_usage(self.home).free / 1e9, 1)
        for dev, host in (devices or {}).items():
            if dev == self.machine:
                continue
            try:
                r = subprocess.run([*self.ssh, host, "df -Pk ~ | tail -1"], capture_output=True, text=True, timeout=20)
                out["free_gb"][dev] = round(int(r.stdout.split()[3]) * 1024 / 1e9, 1) if r.returncode == 0 else None
            except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                out["free_gb"][dev] = None
        return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {"host": "mac-mini-2012", "root": "marvin-cold"}


def default_store() -> tuple[Store, dict[str, str]]:
    """The store from config/cold_store.json, with the host's ssh name looked up in the machine registry."""
    sys.path.insert(0, str(HERE))
    import machine_profile  # noqa: E402
    cfg = load_config()
    registry = machine_profile._load_registry()
    hosts = {dev: (info or {}).get("tailscale_hostname") or dev for dev, info in registry.items()}
    host_id = cfg.get("host", "mac-mini-2012")
    try:
        import dispatch_concurrency  # the ticket pipeline's own floor: a fetch never stalls ticket work
        floor_gb = dispatch_concurrency.load()["guards"]["min_disk_gb"]
    except Exception:
        floor_gb = 15
    store = Store(host=hosts.get(host_id, host_id), host_id=host_id, root=cfg.get("root", "marvin-cold"),
                  machine=machine_profile.registry_id(), min_free_bytes=int(floor_gb * 1e9))
    return store, hosts


def _print_listing(out: dict) -> None:
    print(f"cold host: {out['host']}" + ("" if out["reachable"] else " (not reachable; showing this machine's catalog)"))
    if not out["parked"]:
        print("  nothing parked")
    for e in out["parked"]:
        here = f", here: {e['here']}" if e.get("here") else ""
        if e.get("local_bytes"):
            here += f", {e['local_bytes'] / 1e9:.2f} GB back on this machine (park it again to free it)"
        print(f"  {e.get('name')}: {e.get('bytes', 0) / 1e9:.2f} GB, {e.get('files')} files, from "
              f"{e.get('origin_machine')}:{e.get('origin_path')} on {e.get('parked_at')}{here}")
    print("free space:")
    for dev, gb in out["free_gb"].items():
        print(f"  {dev}: {'not reachable' if gb is None else f'{gb:g} GB'}")


def _run(command: list[str]) -> int:
    try:
        return subprocess.run(command).returncode
    except FileNotFoundError:
        print(f"marvin-cold: {command[0]}: command not found", file=sys.stderr)
        return 127
    except OSError as err:
        print(f"marvin-cold: {command[0]}: {err}", file=sys.stderr)
        return 126


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, command = argv[:cut], argv[cut + 1:]
    ap = argparse.ArgumentParser(prog="marvin-cold", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("park", help="move a folder to the cold host, leave a marker")
    p.add_argument("path")
    p.add_argument("--name")
    e = sub.add_parser("ensure", help="make a parked folder local again (prints its path)")
    e.add_argument("target", help="the folder's path, or its cold-store name")
    e.add_argument("--part", help="fetch only this sub-folder or file")
    e.add_argument("--optional", action="store_true", help="succeed quietly when nothing by that name is parked")
    e.add_argument("--min-free-gb", type=float, help="free space to leave after the fetch (default: pipeline floor)")
    e.add_argument("--then-park", action="store_true",
                   help="run the command after -- with the data here, then park the whole folder again")
    sub.add_parser("list", help="what is parked, and free space on each machine")
    sub.add_parser("where", help="same as list")
    a = ap.parse_args(argv)
    then_park = getattr(a, "then_park", False)
    if then_park and not command:
        print("marvin-cold: --then-park needs a command after --, e.g. ensure PATH --then-park -- python eval.py",
              file=sys.stderr)
        return NOT_PARKED
    if command and not then_park:
        print("marvin-cold: a command after -- only runs with ensure --then-park", file=sys.stderr)
        return NOT_PARKED
    store, hosts = default_store()
    if then_park:
        floor = None if a.min_free_gb is None else int(a.min_free_gb * 1e9)
        rc = None
        try:
            with store.fetched(a.target, a.part, a.optional, floor) as got:
                if got is not None:
                    print(got, flush=True)
                rc = _run(command)
        except ColdError as err:
            print(f"marvin-cold: {err}", file=sys.stderr)
            return rc if rc else err.code
        return rc
    try:
        if a.cmd == "park":
            print(json.dumps(store.park(Path(a.path), a.name)))
        elif a.cmd == "ensure":
            floor = None if a.min_free_gb is None else int(a.min_free_gb * 1e9)
            got = store.ensure(a.target, a.part, a.optional, floor)
            if got is not None:
                print(got)
        else:
            _print_listing(store.listing(hosts))
    except ColdError as err:
        print(f"marvin-cold: {err}", file=sys.stderr)
        return err.code
    return OK


if __name__ == "__main__":
    sys.exit(main())
