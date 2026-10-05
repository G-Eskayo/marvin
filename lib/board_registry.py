#!/usr/bin/env python3
"""Project board registry (CONTEXT.md "Project boards").

A board is a registry entry; its tickets are read live from the project's
tracker by the dashboard, so nothing here stores tickets. Idempotent:
`ensure_board` is safe to call every time MARVIN touches a project.

    board_registry.py ensure <owner/repo> [--name N] [--due YYYY-MM-DD] [--hard]
    board_registry.py list
    board_registry.py discover [owner]   # register every repo using the pipeline labels
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_PATH = Path.home() / ".claude" / "boards" / "registry.json"
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _load(path: Path) -> dict:
    if not path.exists():
        return {"boards": []}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        # Never overwrite what we can't parse -- it's synced, shared state.
        raise ValueError(f"{path} is corrupt ({e}); fix or remove it by hand") from e
    if not isinstance(data, dict) or not isinstance(data.get("boards"), list):
        raise ValueError(f"{path} has an unexpected shape")
    return data


def ensure_board(repo: str, name: str | None = None, due: str | None = None,
                 due_hard: bool | None = None, path: Path | None = None) -> dict:
    if not _REPO_RE.match(repo or ""):
        raise ValueError(f"expected owner/repo, got {repo!r}")
    path = path or REGISTRY_PATH
    data = _load(path)
    entry = next((b for b in data["boards"] if b["repo"] == repo), None)
    created = entry is None
    if created:
        entry = {"repo": repo, "name": name or repo.split("/")[1],
                 "addedAt": datetime.now(timezone.utc).isoformat()}
        data["boards"].append(entry)
    changed = created
    if due and entry.get("due") != due:
        entry["due"] = due
        changed = True
    if due_hard is not None and due and entry.get("dueHard") != due_hard:
        entry["dueHard"] = due_hard
        changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(path)
    return {"created": created, "board": entry}


def list_boards(path: Path | None = None) -> list[dict]:
    return _load(path or REGISTRY_PATH)["boards"]


PIPELINE_LABEL = "ready-for-agent"


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=30).stdout


def discover(owner: str, gh=_gh, path: Path | None = None, extra_repos=()) -> list[str]:
    """Register a board for every non-archived repo of `owner` that tracks work in issues (has the ticket
    pipeline's labels, or any issue at all), so a board exists without anyone remembering to ask for it.
    `extra_repos` (e.g. every active or recent project in the catalog) get a board too, so a project has
    somewhere for its first ticket to show up. Returns the newly registered repos. Never raises:
    discovery is best-effort."""
    known = {b["repo"] for b in list_boards(path)}
    added = []
    for repo in extra_repos:
        if repo in known or not _REPO_RE.match(repo or ""):
            continue
        ensure_board(repo, path=path)
        known.add(repo)
        added.append(repo)
    try:
        repos = json.loads(gh(["repo", "list", owner, "--limit", "100", "--json", "nameWithOwner,isArchived"]))
    except Exception:  # noqa: BLE001 -- offline / auth: try again next cycle
        return added
    for r in repos:
        repo = r["nameWithOwner"]
        if r.get("isArchived") or repo in known:
            continue
        try:
            names = {l["name"] for l in json.loads(gh(["label", "list", "--repo", repo, "--limit", "200", "--json", "name"]))}
        except Exception:  # noqa: BLE001
            continue
        has_tickets = PIPELINE_LABEL in names
        if not has_tickets:
            try:  # a repo that tracks work in issues deserves a board even without the pipeline label
                has_tickets = bool(json.loads(gh(["issue", "list", "--repo", repo, "--state", "all", "--limit", "1", "--json", "number"])))
            except Exception:  # noqa: BLE001
                pass
        if has_tickets:
            ensure_board(repo, path=path)
            added.append(repo)
    return added


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("ensure")
    e.add_argument("repo")
    e.add_argument("--name")
    e.add_argument("--due")
    e.add_argument("--hard", action="store_true")
    sub.add_parser("list")
    d = sub.add_parser("discover")
    d.add_argument("owner", nargs="?", default="G-Eskayo")
    a = p.parse_args()
    try:
        if a.cmd == "ensure":
            r = ensure_board(a.repo, a.name, a.due, True if a.hard else None)
            print(("created" if r["created"] else "exists"), r["board"]["repo"])
        elif a.cmd == "discover":
            for repo in discover(a.owner):
                print("created", repo)
        else:
            for b in list_boards():
                print(b["repo"], "-", b["name"], b.get("due", ""))
    except ValueError as err:
        print(f"board_registry: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
