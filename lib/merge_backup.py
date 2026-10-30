#!/usr/bin/env python3
"""Is this machine fit to merge in the Mac mini's place right now? (marvin#940 part 4)

When the Mini can't merge for memory, a dashboard asks the next merge machine's webhook (GET /merge-ready), which asks
this. The owner's terms (2026-10-30): the MacBook is a backup only when it is awake (it answered), on power, at home
and idle. Idle here means it is doing no merge or test run of its own and its memory is not under pressure; the
owner using it does not count against it (he is often the one clicking Approve on it). The Linux box (marvin#945)
slots in the same way and only for MARVIN's own PRs: other projects need a Mac with Xcode.

Unknown power or home counts as no: a backup is never guessed fit. An unreadable memory level does not block (the same
as the memory guard).

    merge_backup.py ready --repo OWNER/NAME     # one JSON line: {"ready", "why", "machine", "os"}
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MARVIN_REPO = "G-Eskayo/marvin"
POWER_SUPPLY = Path("/sys/class/power_supply")


@dataclass
class Facts:
    machine: str
    platform: str
    os: str
    on_power: bool | None
    at_home: bool | None
    pressure: str | None
    merge_running: bool
    test_run: str | None


def verdict(f: Facts, repo: str) -> dict:
    why = []
    if f.on_power is not True:
        why.append("it is on battery (or its power can't be read)")
    if f.at_home is not True:
        why.append("it is not at home (or that can't be told)")
    if f.pressure in ("warn", "critical"):
        why.append("its memory is under pressure")
    if f.merge_running:
        why.append("it is merging something already")
    if f.test_run:
        why.append(f"it is running {f.test_run}")
    if repo.lower() != MARVIN_REPO.lower() and f.platform != "darwin":
        why.append("this project needs a Mac with Xcode")
    return {"ready": not why, "why": why, "machine": f.machine, "os": f.os}


def on_power_darwin(pmset_out: str) -> bool | None:
    import nightly_reset
    return nightly_reset.parse_on_power(pmset_out)


def on_power_linux(root: Path = POWER_SUPPLY) -> bool | None:
    """Mains online, or no power supply listed at all (a desktop)."""
    try:
        supplies = [d for d in root.iterdir() if (d / "type").exists()]
    except OSError:
        return True
    mains = [d for d in supplies if (d / "type").read_text().strip() == "Mains"]
    if not mains:
        return True if not supplies else None
    return any((d / "online").read_text().strip() == "1" for d in mains)


def _home_anchor() -> str | None:
    try:
        return json.loads((HERE.parent / "config" / "peer_care.json").read_text()).get("home_anchor")
    except (OSError, ValueError):
        return None


def at_home(machine: str) -> bool | None:
    anchor = _home_anchor()
    if not anchor:
        return None
    if machine == anchor:
        return True
    try:
        import peer_care
        return peer_care.same_lan_as(anchor)
    except Exception:  # noqa: BLE001 -- can't tell = not at home
        return None


def os_name() -> str:
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return f"{platform.system()} {platform.release()}"


def gather() -> Facts:
    try:
        from machine_profile import registry_id
        machine = registry_id()
    except Exception:  # noqa: BLE001
        machine = platform.node()
    if sys.platform == "darwin":
        try:
            power = on_power_darwin(subprocess.run(["/usr/bin/pmset", "-g", "batt"], capture_output=True, text=True,
                                                   timeout=10).stdout)
        except (OSError, subprocess.SubprocessError):
            power = None
    else:
        power = on_power_linux()
    import memory_guard
    import test_slot
    holder = test_slot.holder()
    return Facts(machine=machine, platform=sys.platform, os=os_name(), on_power=power, at_home=at_home(machine),
                 pressure=memory_guard.read_level(), merge_running=test_slot.merge_pending(),
                 test_run=(holder or {}).get("what"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="merge_backup", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("ready")
    r.add_argument("--repo", default=MARVIN_REPO)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        print(json.dumps(verdict(gather(), a.repo)))
    except Exception as exc:  # noqa: BLE001 -- an answer, never a crash: not fit when it can't tell
        print(json.dumps({"ready": False, "why": [f"it couldn't check itself ({type(exc).__name__})"],
                          "machine": None, "os": None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
