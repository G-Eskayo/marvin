#!/usr/bin/env python3
"""Project catalog: one record per project Gil has, discovered automatically.

Design: CONTEXT.md "Project catalog and the master 'Where things are' doc".
Generated output is per machine (`~/.claude/catalog/projects.<device>.json`, not
synced: local paths differ per machine). Decisions live in the shared
`~/.claude/catalog/overrides.json`, which discovery only ever reads.

    project_catalog.py refresh [--if-older-than SECONDS]
    project_catalog.py render        # the master-doc "Projects" section (markdown)
    project_catalog.py show [id]
"""
from __future__ import annotations
import argparse
from urllib.parse import quote
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

OWNER = "G-Eskayo"
HOME = Path.home()
CATALOG_DIR = HOME / ".claude" / "catalog"
OVERRIDES_PATH = CATALOG_DIR / "overrides.json"
LOCAL_ROOTS = [HOME / "Documents" / "Projects", HOME / "Developer", HOME / "Documents" / "Money-and-Admin" / "budgeting"]
EXTRA_LOCAL = [HOME / ".agents"]
MEMORY_DIR = HOME / ".claude" / "projects" / ("-" + str(HOME).strip("/").replace("/", "-")) / "memory"

PORTFOLIO_REPO_ID = "portfolio-website-updater"
_PORTFOLIO_DEFAULT = HOME / "Documents" / "Projects" / "portfolio-website-updater"

ACTIVE_DAYS, RECENT_DAYS = 30, 180
STOP = {"ml", "ai", "project", "projects", "using", "and", "the", "of", "for", "in", "a", "an", "powered", "full", "with", "to"}
MATCH_THRESHOLD = 0.5


# ── portfolio repo lookup ───────────────────────────────────────────────────

def portfolio_repo_path() -> Path:
    import os
    override = os.environ.get("MARVIN_PORTFOLIO_PATH")
    if override:
        return Path(override).expanduser()
    cat = read_catalog(catalog_path())
    for p in (cat or {}).get("projects", []):
        if p.get("id") == PORTFOLIO_REPO_ID and p.get("localPaths"):
            return Path(p["localPaths"][0])
    return _PORTFOLIO_DEFAULT


# ── pure helpers ────────────────────────────────────────────────────────────

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in STOP}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def derive_status(last_activity: str | None, archived: bool, now: datetime) -> str:
    if archived:
        return "archived"
    d = _parse(last_activity)
    if d is None:
        return "dormant"
    age = now - d
    if age <= timedelta(days=ACTIVE_DAYS):
        return "active"
    return "recent" if age <= timedelta(days=RECENT_DAYS) else "dormant"


def match_portfolio(entries: list[dict], names: list[str]) -> dict[str, str]:
    """portfolio url -> project name. Slug-token overlap, one-to-one, best pair first."""
    pairs = []
    for e in entries:
        etoks = tokens(e["url"].rstrip("/").rsplit("/", 1)[-1])
        if not etoks:
            continue
        for n in names:
            score = len(etoks & tokens(n)) / len(etoks)
            if score >= MATCH_THRESHOLD:
                pairs.append((score, len(tokens(n)) * -1, e["url"], n))
    pairs.sort(key=lambda p: (-p[0], p[1]))  # best score first; among equals the tighter name
    out: dict[str, str] = {}
    taken: set[str] = set()
    for _score, _len, url, n in pairs:
        if url in out or n in taken:
            continue
        out[url] = n
        taken.add(n)
    return out


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _docs_summary(d: dict) -> str:
    bits = (["CONTEXT.md"] if d.get("context") else []) + (["README.md"] if d.get("readme") else [])
    if d.get("adrCount"):
        bits.append(f"{d['adrCount']} ADR{'s' if d['adrCount'] != 1 else ''}")
    return ", ".join(bits) if bits else "none yet"


def render_card(p: dict) -> str:
    L = [f"# {p['name']}", ""]
    if p.get("description"):
        L += [p["description"], ""]
    la = (p.get("lastActivity") or "")[:10]
    L.append(f"- **Status:** {p['status']}" + (f" (last activity {la})" if la else ""))
    L.append(f"- **Kind:** {p['kind']}")
    if p.get("repo"):
        L.append(f"- **GitHub:** {p['repo']}" + (f" ({p['visibility']})" if p.get("visibility") else ""))
    if p["localPaths"]:
        L.append("- **Local:** " + "; ".join(p["localPaths"]))
    L.append(f"- **Docs:** {_docs_summary(p['docs'])}")
    if p.get("portfolio"):
        L.append(f"- **Portfolio page:** [{p['portfolio']['title']}]({p['portfolio']['url']}) — {p['portfolio'].get('category', '')}")
    L.append(f"- **Board:** {'yes (Activity tab)' if p['board'] else 'no'}")
    if p["memory"]:
        L.append("- **Memory notes:** " + ", ".join(p["memory"]))
    L.append("- **Tags:** " + (", ".join(p["tags"]) or "none"))
    if p.get("notes"):
        L += ["", p["notes"]]
    return "\n".join(L) + "\n"


# ── build ───────────────────────────────────────────────────────────────────

def _topics(repo: dict) -> list[str]:
    out = []
    for t in repo.get("repositoryTopics") or []:
        name = t.get("name") or (t.get("topic") or {}).get("name")
        if name:
            out.append(name)
    return out


def choose_primary(paths: list[dict], override: str | None = None) -> str | None:
    """The one real copy of a project when several folders hold it (clarity-captions had three, 2026-10-07):
    Gil's override first, then a full clone over a worktree, then ~/Developer over the rest over iCloud ~/Documents
    (where git + node_modules can hang), then the most recently active. `paths` arrive newest first."""
    if override:
        return override
    if not paths:
        return None
    def place(path: str) -> int:
        if path.startswith(str(HOME / "Developer") + "/"):
            return 0
        return 2 if path.startswith(str(HOME / "Documents") + "/") else 1
    best = min(range(len(paths)), key=lambda i: (bool(paths[i].get("worktree")), place(paths[i]["path"]), i))
    return paths[best]["path"]


def build_catalog(github: list[dict], locals_: list[dict], manifest: list[dict], memory: list[dict],
                  overrides: dict, board_repos: set[str], now: datetime | None = None,
                  docs_probe=None) -> dict:
    now = now or datetime.now(timezone.utc)
    recs: dict[str, dict] = {}

    def blank(pid, name, kind):
        return {"id": pid, "name": name, "kind": kind, "repo": None, "visibility": None, "description": "",
                "localPaths": [], "docs": {"context": False, "readme": False, "adrCount": 0}, "tags": [],
                "status": "dormant", "lastActivity": None, "portfolio": None, "board": False, "memory": [],
                "notes": "", "_archived": False, "_topics": [], "_lang": None}

    for r in github:
        rec = blank(slug(r["name"]), r["name"], "repo")
        rec.update(repo=f"{OWNER}/{r['name']}", visibility=r.get("visibility"), description=r.get("description") or "",
                   lastActivity=r.get("pushedAt"), _archived=bool(r.get("isArchived")), _topics=_topics(r),
                   _lang=(r.get("primaryLanguage") or {}).get("name"))
        recs[rec["id"]] = rec

    by_repo_name = {r["name"].lower(): slug(r["name"]) for r in github}
    attached: dict[str, list[dict]] = {}
    for l in locals_:
        pid = by_repo_name.get((l.get("origin") or "").lower()) or by_repo_name.get(l["name"].lower())
        if pid is None:
            pid = slug(l["name"])
            if pid not in recs:
                rec = blank(pid, l["name"], "local")
                recs[pid] = rec
        attached.setdefault(pid, []).append(l)

    for pid, ls in attached.items():
        ls.sort(key=lambda l: l.get("last_activity") or "", reverse=True)
        rec = recs[pid]
        rec["localPaths"] = [l["path"] for l in ls]
        rec["docs"] = {"context": any(l["docs"]["context"] for l in ls), "readme": any(l["docs"]["readme"] for l in ls),
                       "adrCount": max(l["docs"]["adrCount"] for l in ls)}
        acts = [a for a in [rec["lastActivity"], *(l.get("last_activity") for l in ls)] if a]
        rec["lastActivity"] = max(acts, key=lambda a: _parse(a) or datetime.min.replace(tzinfo=timezone.utc)) if acts else None

    if docs_probe:
        for rec in recs.values():
            if rec["kind"] == "repo" and not rec["localPaths"]:
                try:
                    rec["docs"] = docs_probe(rec["repo"].split("/", 1)[1])
                except Exception:  # noqa: BLE001 -- unknown stays "none yet", next refresh retries
                    pass

    # portfolio
    forced = {pid: o["portfolio"] for pid, o in overrides.items() if o.get("portfolio")}
    by_url = {e["url"]: e for e in manifest}
    auto = match_portfolio([e for e in manifest if e["url"] not in forced.values()],
                           [r["name"] for r in recs.values() if r["kind"] != "portfolio-only"])
    name_to_id = {r["name"]: pid for pid, r in recs.items()}
    used: set[str] = set()
    for url, name in auto.items():
        forced.setdefault(name_to_id[name], url)
    for pid, url in forced.items():
        if pid in recs and url in by_url:
            e = by_url[url]
            recs[pid]["portfolio"] = {"url": url, "title": e["title"], "category": e.get("category", "")}
            used.add(url)
    for e in manifest:
        if e["url"] in used:
            continue
        pid = "portfolio:" + slug(e["url"].rstrip("/").rsplit("/", 1)[-1])
        rec = blank(pid, e["title"], "portfolio-only")
        rec.update(description=e.get("description", ""), portfolio={"url": e["url"], "title": e["title"], "category": e.get("category", "")})
        recs[pid] = rec

    # memory pointers
    for pid, rec in recs.items():
        needles = _dedupe([rec["id"] if ":" not in rec["id"] else rec["id"].split(":", 1)[1], slug(rec["name"]),
                           *[slug(a) for a in overrides.get(pid, {}).get("aliases", [])]])
        file_hits, text_hits = [], []
        for m in memory:
            fname, text = m["file"].lower(), re.sub(r"[_\s]+", "-", m["text"].lower())
            if any(n in fname for n in needles if len(n) >= 4):
                file_hits.append(m["file"])
            elif any(n in text for n in needles if len(n) >= 5):
                text_hits.append(m["file"])
        rec["memory"] = sorted(file_hits)[:8] + sorted(text_hits)[: max(0, 8 - len(file_hits))]

    # finish: status, board, overrides, tags, card
    for pid in list(recs):
        o = overrides.get(pid, {})
        if o.get("ignore"):
            del recs[pid]
            continue
        rec = recs[pid]
        if o.get("name"):
            rec["name"] = o["name"]
        rec["notes"] = o.get("notes", "")
        rec["primaryPath"] = choose_primary(attached.get(pid, []), o.get("primaryPath"))
        if rec["primaryPath"] in rec["localPaths"]:
            rec["localPaths"] = [rec["primaryPath"], *[x for x in rec["localPaths"] if x != rec["primaryPath"]]]
        if rec["kind"] != "portfolio-only":
            rec["status"] = o.get("status") or derive_status(rec["lastActivity"], rec["_archived"], now)
        else:
            rec["status"] = o.get("status") or "dormant"
        rec["board"] = bool(rec["repo"] and rec["repo"] in board_repos)
        cat = rec["portfolio"]["category"] if rec["portfolio"] else ""
        rec["tags"] = _dedupe([f"kind:{rec['kind']}", f"status:{rec['status']}",
                               f"lang:{rec['_lang'].lower()}" if rec["_lang"] else None,
                               *[f"topic:{t}" for t in rec["_topics"]],
                               f"portfolio:{slug(cat)}" if cat else None,
                               "has:docs" if rec["docs"]["context"] or rec["docs"]["readme"] else None,
                               "has:board" if rec["board"] else None, *o.get("tags", [])])
        for k in ("_archived", "_topics", "_lang"):
            rec.pop(k)
        rec["summary_md"] = render_card(rec)

    projects = sorted(recs.values(), key=lambda r: (r["lastActivity"] or "", r["name"].lower()), reverse=True)
    return {"generated_at": now.isoformat(), "projects": projects}


# ── master doc ──────────────────────────────────────────────────────────────

def render_master(catalog: dict) -> str:
    groups = [("Active", "active"), ("Recent", "recent"), ("Dormant", "dormant"), ("Archived", "archived")]
    projs = catalog["projects"]
    L = ["## Projects", "", f"_{len(projs)} projects, discovered automatically from GitHub, local folders, the portfolio site and memory. "
         "Generated; edit decisions in ~/.claude/catalog/overrides.json._", ""]

    def file_link(path: str) -> str:
        return "file://" + quote(path)

    def line(p):
        bits = []
        doc = "CONTEXT.md" if p["docs"]["context"] else "README.md" if p["docs"]["readme"] else None
        if doc:
            bits.append(f"[Docs](dash://doc/{p['id']}/{doc})")
        primary = p.get("primaryPath") or (p["localPaths"][0] if p["localPaths"] else None)
        if primary:
            bits.append(f"[Open folder]({file_link(primary)})")
        if p.get("repo"):
            bits.append(f"[{p['repo']}](https://github.com/{p['repo']})")
        bits.append(f"docs: {_docs_summary(p['docs'])}")
        if p.get("portfolio"):
            bits.append(f"site: {p['portfolio']['url']}")
        if p["board"]:
            bits.append("board")
        head = f"- **{p['name']}**" + (f" — {p['description']}" if p.get("description") else "")
        others = [x for x in p["localPaths"] if x != primary]
        tail = ("\n  other copies: " + " · ".join(f"[{'/'.join(Path(x).parts[-2:])}]({file_link(x)})" for x in others)) if others else ""
        return head + "\n  " + " · ".join(bits) + tail

    for title, status in groups:
        rows = [p for p in projs if p["status"] == status and p["kind"] != "portfolio-only"]
        if rows:
            L += [f"### {title}", *map(line, rows), ""]
    po = [p for p in projs if p["kind"] == "portfolio-only"]
    if po:
        L += ["### Portfolio only  (on the site, no repo or folder of their own)", *map(line, po), ""]
    return "\n".join(L)


# ── persistence ─────────────────────────────────────────────────────────────

def write_catalog(catalog: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalog, indent=1))
    tmp.replace(path)


def read_catalog(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def is_stale(path: Path, max_age_s: float, now: datetime | None = None) -> bool:
    cat = read_catalog(path)
    gen = _parse((cat or {}).get("generated_at"))
    if gen is None:
        return True
    return ((now or datetime.now(timezone.utc)) - gen).total_seconds() > max_age_s


def load_overrides(path: Path = OVERRIDES_PATH) -> dict:
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        # hand-edited: "_comment"-style keys and stray non-objects must not break discovery
        return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}
    except (OSError, json.JSONDecodeError):
        return {}


def catalog_path() -> Path:
    import machine_profile
    return CATALOG_DIR / f"projects.{machine_profile.registry_id() or 'unknown'}.json"


def refresh(path: Path, github, local, manifest, memory, overrides, boards, now=None, docs_probe=None, report=None) -> dict:
    """Rebuild and write the catalog. Any discovery failure keeps the last good file.
    `report(step, detail)` is told each phase as it starts, so the dashboard can show progress."""
    report = report or (lambda step, detail="": None)
    phase = "starting"
    try:
        def run(name, fn, count=lambda r: f"{len(r)} found"):
            nonlocal phase
            phase = name
            report(name)
            result = fn()
            report(name, count(result))
            return result

        gh = run("GitHub repos", github)
        loc = run("Local folders", local)
        man = run("Portfolio manifest", manifest)
        mem = run("Memory notes", memory)
        brd = run("Boards", boards)
        ovr = overrides()
        phase = "Building catalog"
        report(phase, "matching repos, folders, portfolio pages and memory")
        cat = build_catalog(gh, loc, man, mem, ovr, brd, now=now, docs_probe=docs_probe)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{phase}: {e}"}
    report("Writing catalog", f"{len(cat['projects'])} projects")
    write_catalog(cat, path)
    return {"ok": True, "count": len(cat["projects"])}


# ── real discoverers ────────────────────────────────────────────────────────

def run_env(token_file: Path = HOME / ".claude" / ".gh-token") -> dict:
    """launchd jobs get a bare PATH and no gh login of their own (both bit this repo before):
    add Homebrew and reuse the pipeline's shared token, never overriding an explicit one."""
    import os
    env = dict(os.environ)
    parts = env.get("PATH", "").split(":")
    env["PATH"] = ":".join(_dedupe(["/opt/homebrew/bin", "/usr/local/bin", *parts]))
    if not env.get("GH_TOKEN"):
        try:
            tok = token_file.read_text().strip()
            if tok:
                env["GH_TOKEN"] = tok
        except OSError:
            pass
    return env


def _run(args: list[str], cwd: Path | None = None, timeout: int = 60) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True, cwd=cwd, timeout=timeout, env=run_env()).stdout


def discover_github() -> list[dict]:
    out = _run(["gh", "repo", "list", OWNER, "--limit", "200", "--json",
                "name,description,visibility,isArchived,pushedAt,primaryLanguage,repositoryTopics"])
    return json.loads(out)


def github_docs_probe(repo_name: str) -> dict:
    names = {e["name"] for e in json.loads(_run(["gh", "api", f"repos/{OWNER}/{repo_name}/contents"]))}
    adr = 0
    if "docs" in names:
        try:
            adr = sum(1 for e in json.loads(_run(["gh", "api", f"repos/{OWNER}/{repo_name}/contents/docs/adr"])) if e["name"].endswith(".md"))
        except Exception:  # noqa: BLE001
            pass
    return {"context": "CONTEXT.md" in names, "readme": "README.md" in names, "adrCount": adr}


def _local_record(p: Path) -> dict:
    origin = None
    last = None
    if (p / ".git").exists():
        try:
            url = _run(["git", "-C", str(p), "remote", "get-url", "origin"]).strip()
            m = re.search(rf"{OWNER}/([^/]+?)(?:\.git)?$", url)
            origin = m.group(1) if m else None
            last = _run(["git", "-C", str(p), "log", "-1", "--format=%cI"]).strip() or None
        except Exception:  # noqa: BLE001
            pass
    if last is None:
        try:
            last = datetime.fromtimestamp(max((c.stat().st_mtime for c in p.iterdir()), default=p.stat().st_mtime),
                                          tz=timezone.utc).isoformat()
        except OSError:
            pass
    adr_dir = p / "docs" / "adr"
    return {"path": str(p), "name": p.name, "origin": origin, "last_activity": last, "worktree": (p / ".git").is_file(),
            "docs": {"context": (p / "CONTEXT.md").exists(), "readme": (p / "README.md").exists(),
                     "adrCount": len(list(adr_dir.glob("*.md"))) if adr_dir.is_dir() else 0}}


def discover_local(roots=None, extra=None) -> list[dict]:
    out = []
    for root in (LOCAL_ROOTS if roots is None else roots):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            if child.name == "experiments":  # a folder of projects, not a project
                for sub in sorted(child.iterdir()):
                    if sub.is_dir() and not sub.name.startswith("."):
                        out.append(_local_record(sub))
            else:
                out.append(_local_record(child))
    for p in (EXTRA_LOCAL if extra is None else extra):
        if p.is_dir():
            out.append(_local_record(p))
    return out


def discover_manifest(path: Path | None = None) -> list[dict]:
    if path is None:
        path = portfolio_repo_path() / "deploy" / "other-projects" / "manifest.json"
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def discover_memory(directory: Path = MEMORY_DIR) -> list[dict]:
    out = []
    try:
        for f in sorted(directory.glob("*.md")):
            if f.name != "MEMORY.md":
                out.append({"file": f.name, "text": f.read_text()[:1500]})
    except OSError:
        pass
    return out


def discover_boards() -> set[str]:
    import board_registry
    return {b["repo"] for b in board_registry.list_boards()}


def real_refresh(path: Path | None = None, now=None) -> dict:
    import job_events
    with job_events.job_run("project-catalog", "Project catalog") as run:
        res = refresh(path or catalog_path(), discover_github, discover_local, discover_manifest, discover_memory,
                      load_overrides, discover_boards, now=now, docs_probe=github_docs_probe, report=run.step)
        run.summary(f"{res['count']} projects" if res["ok"] else f"failed, kept last good: {res['error']}")
        if not res["ok"]:
            run.fail(res["error"])
        return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--if-older-than", type=float, default=0, help="seconds; skip when the catalog is fresher")
    sub.add_parser("render")
    s = sub.add_parser("show")
    s.add_argument("id", nargs="?")
    a = ap.parse_args()
    path = catalog_path()
    if a.cmd == "refresh":
        if a.if_older_than and not is_stale(path, a.if_older_than):
            print("catalog is fresh")
            return 0
        res = real_refresh(path)
        print(f"catalog: {res['count']} projects" if res["ok"] else f"catalog refresh failed (kept last good): {res['error']}")
        return 0 if res["ok"] else 1
    cat = read_catalog(path) or (real_refresh(path) and read_catalog(path))
    if not cat:
        print("no catalog available", file=sys.stderr)
        return 1
    if a.cmd == "render":
        print(render_master(cat))
    else:
        for p in cat["projects"]:
            if not a.id or p["id"] == a.id:
                print(p["summary_md"] if a.id else f"{p['id']:<40} {p['status']:<9} {p['kind']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
