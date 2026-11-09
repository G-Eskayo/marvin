#!/usr/bin/env python3
"""Disposable VMs on mac-mini-2012 (ADR 0069, CONTEXT.md "Disposable VM").

Each run gets a throwaway copy of a frozen golden image, boots it, optionally copies a directory in, runs one
command over SSH, and is ALWAYS destroyed afterwards -- on success, failure, timeout or a crash mid-run.

- marvin-test: clean MARVIN test environment (role b2). NAT network, so it can install what a test needs.
- quarantine: untrusted outside code (role b1). Host-only network with no route out, until Gil decides whether
  quarantine runs may go through Whonix.
- marvin-build: a ticket build (marvin #949). NAT, the test key; made from marvin-test by
  config/mac-mini-2012/build-builder-image.sh (`--freeze-to`), so it lives in a folder the box's user can write.

A run leaves `<name>.owner` (its pid) beside its disk while it runs. `vm_run.py sweep` removes any run VM and disk whose
owner is gone: what a run killed with SIGKILL, or a box that lost power, left behind.

Runs on the box itself; Macs reach it through task dispatch with `--needs test` / `--needs quarantine`:
    ~/.agents/venv/bin/python ~/.agents/lib/vm_run.py --image marvin-test [--repo-dir DIR] -- COMMAND
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

IMAGES_DIR = Path("/var/lib/libvirt/images")
GOLDEN_DIR = IMAGES_DIR / "golden"
RUNS_DIR = IMAGES_DIR / "runs"
NETWORKS = {"marvin-test": "default", "quarantine": "marvin-isolated", "marvin-build": "default"}
# One key per trust class: a compromised quarantine VM learns nothing that opens a test or build VM.
VM_KEYS = {"marvin-test": Path.home() / ".ssh" / "marvin_vm", "quarantine": Path.home() / ".ssh" / "marvin_quarantine",
           "marvin-build": Path.home() / ".ssh" / "marvin_vm"}
# Images root built (golden/) or the box's user built (runs/golden/: golden/ is root's and nothing here may use sudo).
USER_BUILT = {"marvin-build"}
VIRSH = ["virsh", "-q", "-c", "qemu:///system"]
RUN_NAME = re.compile(r"^run-(?:%s)-[0-9a-f]{8}$" % "|".join(map(re.escape, NETWORKS)))
MAX_VCPUS = 8


def golden_path(image: str) -> Path:
    """Where `image`'s frozen golden copy lives (read at call time, so tests can move the folders)."""
    return (RUNS_DIR / "golden" if image in USER_BUILT else GOLDEN_DIR) / f"{image}.qcow2"


def _ssh_opts(image: str) -> list[str]:
    return ["-i", str(VM_KEYS[image]), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]


@dataclass
class RunResult:
    ok: bool
    output: str = ""
    error: str = ""
    exit_code: int | None = None


def _host(cmd: list[str], timeout: float | None = None, check: bool = True,
          input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check, input=input)


_SECRET_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_RESERVED = {"PATH", "HOME", "SHELL", "USER", "IFS", "PS4", "BASH_ENV", "ENV", "LD_PRELOAD", "LD_LIBRARY_PATH"}


def _check_secrets(image: str, secrets: dict[str, str]) -> str | None:
    """Why these secrets can't be handed in, or None. Quarantine never gets one: it runs untrusted code (ADR 0069)."""
    if not secrets:
        return None
    if image == "quarantine":
        return "quarantine VMs never receive secrets"
    for name, value in secrets.items():
        if not isinstance(name, str) or not _SECRET_NAME.match(name) or name in _RESERVED:
            return f"bad secret name {name!r}"
        if not isinstance(value, str) or "\n" in value or "\r" in value or "\0" in value:
            return f"secret {name} has a line break or isn't text"
    return None


def _wait_for_ip(name: str, host, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while True:
        out = host(VIRSH + ["domifaddr", name], check=False).stdout
        m = re.search(r"ipv4\s+(\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return m.group(1)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"no IP for {name} within {timeout:.0f}s")
        time.sleep(2)


def _wait_for_ssh(ip: str, opts: list[str], host, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while host(["ssh", *opts, f"marvin@{ip}", "true"], timeout=15, check=False).returncode != 0:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"no SSH on {ip} within {timeout:.0f}s")
        time.sleep(2)


def _wait_for_shutoff(name: str, host, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while host(VIRSH + ["domstate", name], check=False).stdout.strip() != "shut off":
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{name} did not shut down within {timeout:.0f}s")
        time.sleep(2)


def _freeze(name: str, ip: str, opts: list[str], disk: Path, out: Path, host, timeout: float) -> None:
    """Stop the VM cleanly, then flatten its disk (backing file included) into a standalone read-only image at `out`.
    Written beside `out` and renamed into place, so a failure never leaves a half image or harms the current one."""
    host(["ssh", *opts, f"marvin@{ip}", "sudo truncate -s0 /etc/machine-id; sudo cloud-init clean --logs >/dev/null 2>&1;"
          " sudo poweroff"], timeout=30, check=False)
    _wait_for_shutoff(name, host, timeout)
    tmp = out.with_name(f".{out.name}.building")
    try:
        host(["qemu-img", "convert", "-q", "-O", "qcow2", str(disk), str(tmp)], timeout=3600)
        tmp.chmod(0o444)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)


def _freeze_target_refused(out: Path) -> str | None:
    out = Path(out).resolve()
    if out.parent == RUNS_DIR.resolve() or out.parent == GOLDEN_DIR.resolve():
        return f"refusing to freeze into {out.parent}: runs/ is swept and golden/ is root's"
    if any(out == golden_path(i).resolve() for i in NETWORKS if i not in USER_BUILT):
        return f"refusing to overwrite {out}"
    return None


def run(image: str, command: str, repo_dir: Path | None = None, timeout: float = 1800, memory_mb: int = 2048,
        boot_timeout: float = 180, host=_host, secrets: dict[str, str] | None = None, vcpus: int = 2,
        freeze_to: Path | None = None) -> RunResult:
    """`secrets` (e.g. the bot's GitHub token for one ticket run) go in through ssh's stdin, are exported for this one
    command only, and are never written to disk or put in any argv on the box or in the VM.

    `freeze_to` (building a golden image): when the command succeeds, the VM is shut down and its disk flattened into a
    read-only image there. A failed command freezes nothing."""
    if image not in NETWORKS:
        return RunResult(ok=False, error=f"unknown image {image!r}; known: {', '.join(NETWORKS)}")
    if not isinstance(vcpus, int) or isinstance(vcpus, bool) or not 1 <= vcpus <= MAX_VCPUS:
        return RunResult(ok=False, error=f"vcpus must be a whole number from 1 to {MAX_VCPUS}")
    secrets = secrets or {}
    refused = _check_secrets(image, secrets)
    if refused:
        return RunResult(ok=False, error=refused)
    if freeze_to is not None:
        refused = _freeze_target_refused(Path(freeze_to))
        if refused:
            return RunResult(ok=False, error=refused)
    golden = golden_path(image)
    if not golden.exists():
        return RunResult(ok=False, error=f"no golden image at {golden}; build it with "
                                         f"config/mac-mini-2012/build-builder-image.sh" if image in USER_BUILT
                         else f"no golden image at {golden}; build it with config/mac-mini-2012/build-golden.sh")
    opts = _ssh_opts(image)
    name = f"run-{image}-{uuid.uuid4().hex[:8]}"
    disk = RUNS_DIR / f"{name}.qcow2"
    owner = RUNS_DIR / f"{name}.owner"
    step = "start"
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        owner.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}))
        step = "qemu-img"
        host(["qemu-img", "create", "-q", "-f", "qcow2", "-b", str(golden), "-F", "qcow2", str(disk)])
        step = "virt-install"
        host(["virt-install", "--connect", "qemu:///system", "--name", name, "--import",
              "--memory", str(memory_mb), "--vcpus", str(vcpus), "--cpu", "host-passthrough", "--osinfo", "debian13",
              "--disk", f"path={disk},format=qcow2,bus=virtio",
              "--network", f"network={NETWORKS[image]},model=virtio",
              # A video device is required: with --graphics none Kali's virt-install adds none, and Debian's GRUB
              # then resets the VM in a loop before the kernel prints a line (found 2026-10-16). Local-only VNC.
              "--graphics", "vnc,listen=127.0.0.1", "--video", "vga",
              "--noautoconsole"], timeout=120)
        step = "domifaddr"
        ip = _wait_for_ip(name, host, boot_timeout)
        step = "ssh"
        _wait_for_ssh(ip, opts, host, boot_timeout)
        if repo_dir is not None:
            step = "rsync"
            host(["rsync", "-a", "--delete", "--exclude", ".venv", "--exclude", "node_modules",
                  "-e", "ssh " + " ".join(opts), f"{repo_dir}/", f"marvin@{ip}:work/"], timeout=600)
        step = "command"
        cd = "cd ~/work && " if repo_dir is not None else ""
        names = sorted(secrets)
        reads = "".join(f"IFS= read -r {n}; export {n}; " for n in names)
        remote = f"bash -c {shlex.quote(reads + cd + command)}" if names else f"{cd}{command}"
        stdin = "".join(secrets[n] + "\n" for n in names) if names else None
        proc = host(["ssh", *opts, f"marvin@{ip}", remote], timeout=timeout, check=False, input=stdin)
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0 and freeze_to is not None:
            step = "freeze"
            _freeze(name, ip, opts, disk, Path(freeze_to), host, boot_timeout)
        return RunResult(ok=proc.returncode == 0, output=output, exit_code=proc.returncode,
                         error="" if proc.returncode == 0 else f"command exited {proc.returncode}")
    except subprocess.TimeoutExpired:
        return RunResult(ok=False, error=f"{step} timed out")
    except subprocess.CalledProcessError as exc:
        return RunResult(ok=False, error=f"{step} failed: {(exc.stderr or exc.stdout or '').strip()[:300]}")
    except Exception as exc:
        return RunResult(ok=False, error=f"{step} failed: {exc}")
    finally:
        _remove(name, host)


def _remove(name: str, host) -> None:
    host(VIRSH + ["destroy", name], check=False)
    host(VIRSH + ["undefine", name, "--nvram"], check=False)
    (RUNS_DIR / f"{name}.qcow2").unlink(missing_ok=True)
    (RUNS_DIR / f"{name}.owner").unlink(missing_ok=True)


def _pid_alive(pid) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _owner_alive(name: str, alive) -> bool:
    try:
        return bool(alive(json.loads((RUNS_DIR / f"{name}.owner").read_text())["pid"]))
    except (OSError, ValueError, KeyError, TypeError):
        return False   # no record, or one that can't be read: nothing owns it


def sweep(host=_host, alive=_pid_alive) -> list[str]:
    """Remove every run VM and run disk whose owning vm_run process is gone. Only names vm_run itself makes
    (run-<image>-<8 hex>) are touched: never Whonix, a golden image, or a live run. O(runs). Returns what it removed."""
    names: set[str] = set()
    listed = host(VIRSH + ["list", "--all", "--name"], check=False)
    if listed.returncode == 0:
        names |= {n.strip() for n in (listed.stdout or "").splitlines() if RUN_NAME.match(n.strip())}
    if RUNS_DIR.is_dir():
        names |= {p.name[:-len(p.suffix)] for p in RUNS_DIR.iterdir()
                  if p.suffix in (".qcow2", ".owner") and RUN_NAME.match(p.name[:-len(p.suffix)])}
    removed = sorted(n for n in names if not _owner_alive(n, alive))
    for n in removed:
        _remove(n, host)
    return removed


def _terminate_cleanly(signum, _frame):
    """GNU timeout's SIGTERM (and a hang-up) must run run()'s cleanup, not kill the process mid-way."""
    raise SystemExit(128 + signum)


def main() -> None:
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _terminate_cleanly)
    if sys.argv[1:2] == ["sweep"]:
        print("\n".join(sweep()) or "nothing to sweep")
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, choices=sorted(NETWORKS))
    ap.add_argument("--repo-dir", type=Path, default=None, help="directory copied into the VM as ~/work")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--memory-mb", type=int, default=2048)
    ap.add_argument("--vcpus", type=int, default=2)
    ap.add_argument("--freeze-to", type=Path, default=None,
                    help="on success, shut the VM down and flatten its disk into this read-only golden image")
    ap.add_argument("--secret-env", action="append", default=[], metavar="NAME",
                    help="read one line from stdin per NAME and export it for the command only (never quarantine)")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = " ".join(args.command[1:] if args.command[:1] == ["--"] else args.command)
    if not command:
        ap.error("no command given")
    secrets = {name: sys.stdin.readline().rstrip("\n") for name in args.secret_env}
    r = run(args.image, command, repo_dir=args.repo_dir, timeout=args.timeout, memory_mb=args.memory_mb, secrets=secrets,
            vcpus=args.vcpus, freeze_to=args.freeze_to)
    print(r.output, end="")
    if not r.ok:
        print(f"[vm_run] FAILED: {r.error}", file=sys.stderr)
        sys.exit(r.exit_code or 1)


if __name__ == "__main__":
    main()
