#!/usr/bin/env python3
"""Disposable VMs on mac-mini-2012 (ADR 0069, CONTEXT.md "Disposable VM").

Each run gets a throwaway copy of a frozen golden image, boots it, optionally copies a directory in, runs one
command over SSH, and is ALWAYS destroyed afterwards -- on success, failure, timeout or a crash mid-run.

- marvin-test: clean MARVIN test environment (role b2). NAT network, so it can install what a test needs.
- quarantine: untrusted outside code (role b1). Host-only network with no route out, until Gil decides whether
  quarantine runs may go through Whonix.

Runs on the box itself; Macs reach it through task dispatch with `--needs test` / `--needs quarantine`:
    ~/.agents/venv/bin/python ~/.agents/lib/vm_run.py --image marvin-test [--repo-dir DIR] -- COMMAND
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

IMAGES_DIR = Path("/var/lib/libvirt/images")
GOLDEN_DIR = IMAGES_DIR / "golden"
RUNS_DIR = IMAGES_DIR / "runs"
NETWORKS = {"marvin-test": "default", "quarantine": "marvin-isolated"}
# One key per image: a compromised quarantine VM learns nothing that opens a test VM.
VM_KEYS = {"marvin-test": Path.home() / ".ssh" / "marvin_vm", "quarantine": Path.home() / ".ssh" / "marvin_quarantine"}
VIRSH = ["virsh", "-q", "-c", "qemu:///system"]


def _ssh_opts(image: str) -> list[str]:
    return ["-i", str(VM_KEYS[image]), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]


@dataclass
class RunResult:
    ok: bool
    output: str = ""
    error: str = ""
    exit_code: int | None = None


def _host(cmd: list[str], timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)


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


def run(image: str, command: str, repo_dir: Path | None = None, timeout: float = 1800, memory_mb: int = 2048,
        boot_timeout: float = 180, host=_host) -> RunResult:
    if image not in NETWORKS:
        return RunResult(ok=False, error=f"unknown image {image!r}; known: {', '.join(NETWORKS)}")
    golden = GOLDEN_DIR / f"{image}.qcow2"
    opts = _ssh_opts(image)
    name = f"run-{image}-{uuid.uuid4().hex[:8]}"
    disk = RUNS_DIR / f"{name}.qcow2"
    step = "start"
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        step = "qemu-img"
        host(["qemu-img", "create", "-q", "-f", "qcow2", "-b", str(golden), "-F", "qcow2", str(disk)])
        step = "virt-install"
        host(["virt-install", "--connect", "qemu:///system", "--name", name, "--import",
              "--memory", str(memory_mb), "--vcpus", "2", "--cpu", "host-passthrough", "--osinfo", "debian13",
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
        proc = host(["ssh", *opts, f"marvin@{ip}", f"{cd}{command}"], timeout=timeout, check=False)
        output = (proc.stdout or "") + (proc.stderr or "")
        return RunResult(ok=proc.returncode == 0, output=output, exit_code=proc.returncode,
                         error="" if proc.returncode == 0 else f"command exited {proc.returncode}")
    except subprocess.TimeoutExpired:
        return RunResult(ok=False, error=f"{step} timed out")
    except subprocess.CalledProcessError as exc:
        return RunResult(ok=False, error=f"{step} failed: {(exc.stderr or exc.stdout or '').strip()[:300]}")
    except Exception as exc:
        return RunResult(ok=False, error=f"{step} failed: {exc}")
    finally:
        host(VIRSH + ["destroy", name], check=False)
        host(VIRSH + ["undefine", name, "--nvram"], check=False)
        disk.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, choices=sorted(NETWORKS))
    ap.add_argument("--repo-dir", type=Path, default=None, help="directory copied into the VM as ~/work")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--memory-mb", type=int, default=2048)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = " ".join(args.command[1:] if args.command[:1] == ["--"] else args.command)
    if not command:
        ap.error("no command given")
    r = run(args.image, command, repo_dir=args.repo_dir, timeout=args.timeout, memory_mb=args.memory_mb)
    print(r.output, end="")
    if not r.ok:
        print(f"[vm_run] FAILED: {r.error}", file=sys.stderr)
        sys.exit(r.exit_code or 1)


if __name__ == "__main__":
    main()
