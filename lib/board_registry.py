#!/usr/bin/env python3
"""Project board registry (CONTEXT.md "Project boards").

A board is a registry entry; its tickets are read live from the project's
tracker by the dashboard, so nothing here stores tickets. Idempotent:
`ensure_board` is safe to call every time MARVIN touches a project.

    board_registry.py ensure <owner/repo> [--name N] [--due YYYY-MM-DD] [--hard]
    board_registry.py list
    board_registry.py discover [owner]   # register every repo using the pipeline labels
    board_registry.py similar "<what the new project is>"   # check active AND archived boards first (ADR 0060)

Lifecycle (ADR 0060, Gil 2026-10-08): a board whose tickets are all closed, with no open PR, quiet for
FINISH_AFTER_DAYS, is marked finished (`finishedAt`); the catalog then shows its project as archived and the
dashboard folds it away. Nothing is deleted. New work (an open ticket or PR, or a push) reopens it.
Before any NEW board, `similar` searches active and archived boards and the catalog, by name and by meaning,
so a finished project can be reopened or extended (`project:<parent>` + `area:<sub>`) instead of duplicated.
"""
from __future__ import annotations
import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


def retire_board(repo: str, path: Path | None = None) -> bool:
    """Take a repo's board off the dashboard (its project is archived). Returns whether there was one."""
    path = path or REGISTRY_PATH
    data = _load(path)
    kept = [b for b in data["boards"] if b["repo"] != repo]
    if len(kept) == len(data["boards"]):
        return False
    data["boards"] = kept
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)
    return True


def list_boards(path: Path | None = None) -> list[dict]:
    return _load(path or REGISTRY_PATH)["boards"]


def _save(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


# ── lifecycle ───────────────────────────────────────────────────────────────

FINISH_AFTER_DAYS = 14


def _when(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def update_lifecycle(snapshot: dict, last_activity, now: datetime, path: Path | None = None) -> dict:
    """Mark finished boards, reopen ones with new work. `snapshot` is the ticket agents' {repo: {"issues": open,
    "prs": open}}; a repo missing from it (unreachable) is left as it is. `last_activity(repo)` = the latest of its
    last closed ticket and last push, or None when it never had a ticket (empty, not finished)."""
    path = path or REGISTRY_PATH
    data = _load(path)
    out = {"finished": [], "reopened": []}
    for b in data["boards"]:
        snap = snapshot.get(b["repo"])
        if snap is None:
            continue
        busy = bool(snap.get("issues")) or bool(snap.get("prs"))
        if b.get("finishedAt"):
            last = _when(last_activity(b["repo"])) if not busy else None
            if busy or (last and last > _when(b["finishedAt"])):
                b.pop("finishedAt")
                out["reopened"].append(b["repo"])
            continue
        if busy:
            continue
        last = _when(last_activity(b["repo"]))
        if last and now - last >= timedelta(days=FINISH_AFTER_DAYS):
            b["finishedAt"] = now.isoformat()
            out["finished"].append(b["repo"])
    if out["finished"] or out["reopened"]:
        _save(data, path)
    return out


def last_activity_gh(repo: str, gh=None) -> str | None:
    """Latest of the last closed ticket and the last push; None when the repo never had a ticket."""
    gh = gh or _gh
    try:
        closed = json.loads(gh(["issue", "list", "--repo", repo, "--state", "closed", "--limit", "1", "--json", "closedAt"]))
    except Exception:  # noqa: BLE001 -- unknown is never "finished"
        return None
    if not closed:
        return None
    try:
        pushed = json.loads(gh(["api", f"repos/{repo}", "--jq", "{p: .pushed_at}"])).get("p")
    except Exception:  # noqa: BLE001
        return None
    return max(x for x in (closed[0].get("closedAt"), pushed) if x)


# ── check before a new board ────────────────────────────────────────────────

_STOP = {"a", "an", "the", "for", "my", "to", "of", "and", "app", "project", "new", "with", "on", "in", "website"}
NAME_CLOSE = 0.5          # share of a project's name words in the request
MEANING_CLOSE = 0.6       # nomic-embed-text cosine, and it must lead the next project by MEANING_LEAD
MEANING_LEAD = 0.04       # (raw cosines cluster at 0.5-0.7, so only a clear leader counts; calibrated 2026-10-08)


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w and w not in _STOP}


def candidates(boards: list[dict], catalog: list[dict]) -> list[dict]:
    """Every board and catalog project, archived ones included; a finished board counts as archived."""
    out: dict[str, dict] = {}
    for p in catalog:
        out[p["id"]] = {"id": p["id"], "name": p.get("name") or p["id"], "repo": p.get("repo"),
                        "description": p.get("description") or "", "status": p.get("status") or "recent"}
    for b in boards:
        pid = re.sub(r"[^a-z0-9]+", "-", b["repo"].split("/")[1].lower()).strip("-")
        c = out.setdefault(pid, {"id": pid, "name": b.get("name") or pid, "repo": b["repo"], "description": "", "status": "recent"})
        if b.get("finishedAt"):
            c["status"] = "archived"
    return list(out.values())


def _cos(a, b) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def similar(text: str, cands: list[dict], embed=None, limit: int = 3) -> list[dict]:
    """The closest existing projects to `text`, best first, each {id, name, repo, status, score, close, why}."""
    if embed is None:
        from intent_classify import embed_text as embed
    q = _words(text)
    qv = embed(text, "query")
    rows = []
    for c in cands:
        name = _words(c["name"]) | _words(c["id"])
        shared = q & name
        lex = len(shared) / len(name) if name else 0.0
        v = embed(f"{c['name']}. {c['description']}", "document") if qv else None
        sem = _cos(qv, v) if qv and v else 0.0
        rows.append({**{k: c[k] for k in ("id", "name", "repo", "status")}, "lex": lex, "sem": sem, "shared": sorted(shared)})
    by_sem = sorted((r["sem"] for r in rows), reverse=True)
    for r in rows:
        runner_up = (by_sem[1] if len(by_sem) > 1 else 0.0) if r["sem"] == by_sem[0] else by_sem[0]  # a tie never leads
        meaning = r["sem"] >= MEANING_CLOSE and r["sem"] - runner_up >= MEANING_LEAD
        r["close"] = r["lex"] >= NAME_CLOSE or meaning
        r["score"] = round(max(r["lex"], r["sem"]), 3)
        why = []
        if r["shared"]:
            why.append("name: " + ", ".join(r["shared"]))
        if r["sem"]:
            why.append(f"meaning {r['sem']:.2f}" + (" (clear lead)" if meaning else ""))
        r["why"] = "; ".join(why) or "no overlap"
    rows.sort(key=lambda r: (r["close"], r["score"]), reverse=True)
    return [{k: r[k] for k in ("id", "name", "repo", "status", "score", "close", "why")} for r in rows[:limit]]


def similar_now(text: str, path: Path | None = None) -> list[dict]:
    import project_catalog
    cat = project_catalog.read_catalog(project_catalog.catalog_path()) or {}
    return similar(text, candidates(list_boards(path), cat.get("projects", [])))


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
        if r.get("isArchived"):
            # archived on GitHub = finished history: off the dashboard and out of hourly onboarding (2026-10-08)
            if repo in known:
                retire_board(repo, path=path)
                known.discard(repo)
            continue
        if repo in known:
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
    e.add_argument("--new", action="store_true", help="create it even though a similar project exists")
    sub.add_parser("list")
    sm = sub.add_parser("similar")
    sm.add_argument("text")
    d = sub.add_parser("discover")
    d.add_argument("owner", nargs="?", default="G-Eskayo")
    a = p.parse_args()
    try:
        if a.cmd == "similar":
            for m in similar_now(a.text):
                print(f"{'CLOSE ' if m['close'] else '      '}{m['id']:<32} {m['status']:<9} {m['score']:.2f}  {m['why']}")
            return 0
        if a.cmd == "ensure":
            known = {b["repo"] for b in list_boards()}
            if a.repo not in known and not a.new:
                close = [m for m in similar_now(f"{a.name or a.repo.split('/')[1]}") if m["close"] and m["repo"] != a.repo]
                if close:
                    print("A similar project already exists; reopen or extend it (project:<id> + area:<sub>), "
                          "or pass --new to make a separate board:", file=sys.stderr)
                    for m in close:
                        print(f"  {m['id']} ({m['status']}): {m['why']}", file=sys.stderr)
                    return 3
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
