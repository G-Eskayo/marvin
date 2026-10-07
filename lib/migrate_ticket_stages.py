#!/usr/bin/env python3
"""One-time move of ticket stage logs to project-keyed names (G-Eskayo/marvin#216).

Old names: marvin's `<n>.json`, another project's `<repo>-<n>.json` (owner left out, G-Eskayo assumed).
New name: `<owner>__<repo>-<n>.json` (ticket_stages.stage_key). Dry run by default; --apply moves the files.
When both an old and a new file exist for one ticket, their events are merged in time order.

    ~/.agents/venv/bin/python lib/migrate_ticket_stages.py [--apply] [--dir DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_stages as ts  # noqa: E402

OLD_OWNER = "G-Eskayo"


def _old_repo(stem: str) -> tuple[str, int] | None:
    if "__" in stem:
        return None
    if stem.isdigit():
        return ts.MARVIN_REPO, int(stem)
    name, dash, number = stem.rpartition("-")
    return (f"{OLD_OWNER}/{name}", int(number)) if dash and name and number.isdigit() else None


def plan(directory: Path) -> list[tuple[Path, Path]]:
    moves = []
    for src in sorted(directory.glob("*.json")):
        old = _old_repo(src.stem)
        if old:
            moves.append((src, directory / f"{ts.stage_key(*old)}.json"))
    return moves


def _read(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text()) if path.exists() else []
    except (json.JSONDecodeError, OSError):
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="move the files (default: only print the plan)")
    parser.add_argument("--dir", type=Path, default=ts.STAGES_DIR)
    args = parser.parse_args(argv)
    moves = plan(args.dir)
    for src, dst in moves:
        print(f"{src.name} -> {dst.name}{' (merge)' if dst.exists() else ''}")
        if args.apply:
            events = _read(dst) + _read(src)
            events.sort(key=lambda e: e.get("timestamp", ""))
            dst.write_text(json.dumps(events, indent=2))
            src.unlink()
    print(f"{len(moves)} file(s) {'moved' if args.apply else 'to move (dry run; --apply to move)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
