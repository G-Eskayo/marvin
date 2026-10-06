#!/usr/bin/env python3
"""Audit a repository's README against the criteria in docs/readme-criteria.md.

A README has six jobs; every check below belongs to one of them:

  ORIENT    say what it is and why it matters, in the first screen
  PROVE     show it, don't only tell (a screenshot, a diagram, real output)
  START     the shortest path to a first success, and it must work
  NAVIGATE  every link resolves, and the deeper docs are reachable from here
  TRUST     state the status; claims match the repository; not stale
  SCOPE     a front door, not the whole manual

The checks are mechanical on purpose: they find what a program can know (a link that 404s, a path that does not exist, a
command that names a script the repo lacks, a README untouched while the code moved on). What only a reader can judge
(is the one-liner good? is the diagram clear?) is left to the readme skill's review step.

Pure functions take the README text and the repository's file list; a thin layer fetches both with `gh`. Nothing here writes.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath

GOALS = ("ORIENT", "PROVE", "START", "NAVIGATE", "TRUST", "SCOPE")
STALE_COMMITS = 25        # code commits since the README last changed before it is suspect
STALE_DAYS = 120


@dataclass
class Finding:
    goal: str
    check: str
    status: str                      # pass | warn | fail | info
    message: str
    evidence: list[str] = field(default_factory=list)


# ── parsing ─────────────────────────────────────────────────────────────────

_FENCE = re.compile(r"^(```|~~~)\s*([\w+-]*)", re.M)
_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.I)
_HTML_LINK = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"']", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
_BADGE = re.compile(r"img\.shields\.io|badge|\.svg(\?|\))|github\.com/[^/]+/[^/]+/(actions|workflows)", re.I)


def strip_code(text: str) -> str:
    """The README without fenced code blocks, so a command or a sample link inside one is not mistaken for prose."""
    return re.sub(r"(```|~~~).*?\1", "", text, flags=re.S)


def parse(text: str) -> dict:
    prose = strip_code(text)
    blocks = []
    for m in re.finditer(r"(```|~~~)([\w+-]*)\n(.*?)\1", text, flags=re.S):
        blocks.append({"lang": m.group(2), "body": m.group(3)})
    images = [{"alt": a, "url": u} for a, u in _IMAGE.findall(prose)]
    for tag in _HTML_IMG.findall(prose):
        src = re.search(r"src=[\"']([^\"']+)", tag, re.I)
        alt = re.search(r"alt=[\"']([^\"']*)", tag, re.I)
        images.append({"alt": alt.group(1) if alt else "", "url": src.group(1) if src else ""})
    links = [{"text": t, "url": u} for t, u in _LINK.findall(prose)] + [{"text": "", "url": u} for u in _HTML_LINK.findall(prose)]
    headings = [(len(h), t) for h, t in _HEADING.findall(prose)]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", prose) if p.strip() and not p.lstrip().startswith(("#", "|", "-", "*", "<", "!", "["))]
    return {"headings": headings, "links": links, "images": images, "blocks": blocks, "paragraphs": paragraphs,
            "lines": text.count("\n") + 1, "words": len(re.findall(r"\w+", prose)), "mermaid": sum(1 for b in blocks if b["lang"] == "mermaid")}


def anchor_of(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces to hyphens."""
    h = re.sub(r"[^\w\s-]", "", heading.lower().strip())
    return h.replace(" ", "-")            # one hyphen per space, so "install & run" becomes "install--run", as on GitHub


# ── the checks ──────────────────────────────────────────────────────────────

def _head_text(parsed: dict) -> str:
    return " ".join(t.lower() for _, t in parsed["headings"])


def check_orient(parsed: dict, text: str) -> list[Finding]:
    out = []
    h1 = next((t for lvl, t in parsed["headings"] if lvl == 1), None)
    out.append(Finding("ORIENT", "title", "pass" if h1 else "warn", f"title: {h1}" if h1 else "no top-level title (an H1) naming the project"))
    intro = next((p for p in parsed["paragraphs"] if not _BADGE.search(p) and len(p) > 20), None)
    first_lines = "\n".join(text.splitlines()[:25])
    if not intro:
        out.append(Finding("ORIENT", "one-liner", "fail", "no introductory sentence saying what this is"))
    else:
        first = re.split(r"(?<=[.!?])\s", intro)[0]
        in_view = first.strip()[:40] in first_lines
        ok = len(first) <= 220 and in_view
        out.append(Finding("ORIENT", "one-liner", "pass" if ok else "warn",
                           "the first sentence says what it is, near the top" if ok else "the opening sentence is long or sits far down the page (aim: what it is, in one line, in the first screen)",
                           [first[:200]]))
    why = re.search(r"\b(because|so that|so you can|lets you|let you|helps?|enables?|problem|instead of|without|why)\b", " ".join(parsed["paragraphs"][:3]), re.I)
    out.append(Finding("ORIENT", "why", "pass" if why else "warn",
                       "the intro says why it matters" if why else "the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)"))
    return out


def check_prove(parsed: dict, tree: set[str]) -> list[Finding]:
    out = []
    visuals = len([i for i in parsed["images"] if not _BADGE.search(i["url"])]) + parsed["mermaid"]
    out.append(Finding("PROVE", "visual-evidence", "pass" if visuals else "fail",
                       f"{visuals} screenshot/diagram(s)" if visuals else "no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)"))
    missing_alt = [i["url"] for i in parsed["images"] if not i["alt"].strip() and not _BADGE.search(i["url"])]
    out.append(Finding("PROVE", "alt-text", "warn" if missing_alt else "pass",
                       f"{len(missing_alt)} image(s) without alt text" if missing_alt else "images have alt text", missing_alt[:5]))
    broken = []
    for i in parsed["images"]:
        u = i["url"]
        if u and not re.match(r"^(https?:|data:|//)", u):
            path = str(PurePosixPath(urllib.parse.unquote(u.lstrip("/").split("#")[0].split("?")[0])))
            if path.startswith("./"):
                path = path[2:]
            if tree and path not in tree:
                broken.append(u)
    out.append(Finding("PROVE", "images-exist", "fail" if broken else "pass",
                       f"{len(broken)} image path(s) not in the repository" if broken else "every local image exists", broken[:5]))
    tagged = [b for b in parsed["blocks"] if b["lang"]]
    out.append(Finding("PROVE", "worked-example", "pass" if tagged else "warn",
                       f"{len(tagged)} code example(s)" if tagged else "no code example (usage with the output it produces is the quickest proof)"))
    return out


def check_start(parsed: dict, tree: set[str], package_scripts: set[str] | None) -> list[Finding]:
    out = []
    heads = _head_text(parsed)
    has = re.search(r"install|quick ?start|getting started|usage|how to run|run it|setup|set up", heads)
    out.append(Finding("START", "path-to-first-success", "pass" if has else "warn",
                       "has an install / usage / getting-started section" if has else "no section for getting started (what do I type first?)"))
    bad = []
    for b in parsed["blocks"]:
        if b["lang"] not in ("", "bash", "sh", "shell", "zsh", "console"):
            continue
        for line in b["body"].splitlines():
            line = line.strip().lstrip("$ ").strip()
            m = re.match(r"npm (?:run )?([\w:-]+)", line)
            if m and package_scripts is not None and m.group(1) not in package_scripts and m.group(1) not in ("install", "i", "test", "start", "ci", "init"):
                bad.append(f"npm run {m.group(1)} (no such script in package.json)")
            for path in re.findall(r"(?:python3?|bash|sh|node|\./)\s*([\w./-]+\.(?:py|sh|js|mjs))", line):
                clean = path.lstrip("./")
                if tree and clean not in tree and not any(p.endswith("/" + clean) or p == clean for p in tree):
                    bad.append(f"{path} (not in the repository)")
    out.append(Finding("START", "commands-resolve", "fail" if bad else "pass",
                       f"{len(bad)} command(s) name something the repository does not have" if bad else "commands name files and scripts that exist", bad[:8]))
    return out


def check_navigate(parsed: dict, tree: set[str], status_of=None) -> list[Finding]:
    out = []
    anchors = {anchor_of(t) for _, t in parsed["headings"]}
    rel_bad, ext_bad, ext_unchecked, ext_n = [], [], [], 0
    for link in parsed["links"]:
        u = link["url"].strip()
        if not u or u.startswith(("mailto:", "tel:")):
            continue
        if u.startswith("#"):
            if u[1:] not in anchors:
                rel_bad.append(u + " (no such heading)")
        elif re.match(r"^https?://", u):
            ext_n += 1
            if status_of:
                code = status_of(u)
                if code is None:
                    ext_unchecked.append(u)
                elif code >= 400:
                    ext_bad.append(f"{u} -> {code}")
        else:
            path = urllib.parse.unquote(u.split("#")[0].split("?")[0]).lstrip("/")
            path = path[2:] if path.startswith("./") else path
            if path and tree and path.rstrip("/") not in tree and not any(p.startswith(path.rstrip("/") + "/") for p in tree):
                rel_bad.append(u)
    out.append(Finding("NAVIGATE", "relative-links", "fail" if rel_bad else "pass",
                       f"{len(rel_bad)} link(s) to files or headings that do not exist" if rel_bad else "every relative link resolves", rel_bad[:8]))
    out.append(Finding("NAVIGATE", "external-links", "fail" if ext_bad else ("info" if ext_unchecked and not ext_n else "pass"),
                       f"{len(ext_bad)} external link(s) dead" if ext_bad else f"{ext_n - len(ext_unchecked)} external link(s) alive" + (f", {len(ext_unchecked)} not checked" if ext_unchecked else ""),
                       ext_bad[:8]))
    linked = " ".join(l["url"].lower() for l in parsed["links"])
    docs = [("docs/", "docs"), ("contributing.md", "CONTRIBUTING"), ("license", "LICENSE"), ("changelog.md", "CHANGELOG")]
    unlinked = []
    for needle, label in docs:
        present = any(p.lower().startswith(needle) or p.lower() == needle.rstrip("/") or p.lower().startswith(needle) for p in tree)
        mentioned = needle.strip("/") in linked or label.lower() in " ".join(t.lower() for _, t in parsed["headings"]) or re.search(label, " ".join(parsed["paragraphs"]), re.I)
        if present and not mentioned:
            unlinked.append(label)
    out.append(Finding("NAVIGATE", "deeper-docs-reachable", "warn" if unlinked else "pass",
                       f"the repository has {', '.join(unlinked)} but the README never points to it" if unlinked else "the repository's other docs are reachable from the README"))
    return out


def check_trust(parsed: dict, text: str, tree: set[str], meta: dict) -> list[Finding]:
    out = []
    status = re.search(r"\b(status|stable|alpha|beta|work in progress|wip|experimental|production|maintained|roadmap|deprecated|archived)\b", text, re.I)
    out.append(Finding("TRUST", "status", "pass" if status else "warn",
                       "says what state the project is in" if status else "never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit"))
    paths = []
    for tick in re.findall(r"`([^`\n]+)`", strip_code(text)):
        t = tick.strip()
        if re.fullmatch(r"[\w./-]+\.[A-Za-z0-9]{1,6}", t) and "/" in t and not t.startswith(("http", "~", "/")):
            if tree and t not in tree and not any(p.endswith(t) for p in tree):
                paths.append(t)
    out.append(Finding("TRUST", "paths-exist", "fail" if paths else "pass",
                       f"{len(paths)} file path(s) in the text that the repository does not contain" if paths else "file paths named in the text exist", sorted(set(paths))[:8]))
    claims = sorted({m.group(0) for m in re.finditer(r"\b\d[\d,]*\+?\s+(?:tests?|skills?|commands?|pages?|files?|repos?|projects?|checks?|stars?|users?)\b", strip_code(text), re.I)})
    out.append(Finding("TRUST", "numbers-to-verify", "info" if claims else "pass",
                       "counts the text states: confirm each is still true" if claims else "no counts that can go stale", claims[:10]))
    if meta.get("readme_commit_at") and meta.get("repo_commit_at"):
        gap = (_dt(meta["repo_commit_at"]) - _dt(meta["readme_commit_at"])).days
        since = meta.get("commits_since_readme", 0)
        stale = since >= STALE_COMMITS and gap >= STALE_DAYS // 4 or gap >= STALE_DAYS
        out.append(Finding("TRUST", "freshness", "warn" if stale else "pass",
                           f"the README last changed {gap} days before the latest commit, with {since} commit(s) since" + (": likely out of date" if stale else ""),
                           [f"README last touched {meta['readme_commit_at'][:10]}; repo last touched {meta['repo_commit_at'][:10]}"]))
    out.append(Finding("TRUST", "about-metadata", "pass" if meta.get("description") else "warn",
                       "the GitHub description is set" if meta.get("description") else "no GitHub description (it is what search and link previews show)"))
    return out


def check_scope(parsed: dict) -> list[Finding]:
    lines = parsed["lines"]
    heads = _head_text(parsed)
    has_toc = bool(re.search(r"table of contents|contents", heads)) or sum(1 for l in parsed["links"] if l["url"].startswith("#")) >= 4
    if lines > 100 and not has_toc:
        toc = Finding("SCOPE", "navigation-aid", "warn", f"{lines} lines with no table of contents (GitHub's outline menu helps, a contents list helps more)")
    else:
        toc = Finding("SCOPE", "navigation-aid", "pass", "short enough, or has a table of contents")
    big = Finding("SCOPE", "front-door-not-manual", "warn" if lines > 500 else "pass",
                  f"{lines} lines: long reference and design material belongs in docs/, linked from here" if lines > 500 else f"{lines} lines")
    return [toc, big]


def audit(text: str, tree: set[str], meta: dict | None = None, package_scripts: set[str] | None = None, status_of=None) -> dict:
    meta = meta or {}
    parsed = parse(text)
    findings = (check_orient(parsed, text) + check_prove(parsed, tree) + check_start(parsed, tree, package_scripts)
                + check_navigate(parsed, tree, status_of) + check_trust(parsed, text, tree, meta) + check_scope(parsed))
    score = {}
    for g in GOALS:
        fs = [f for f in findings if f.goal == g and f.status != "info"]
        pts = sum({"pass": 1.0, "warn": 0.5, "fail": 0.0}[f.status] for f in fs)
        score[g] = round(pts / len(fs), 2) if fs else None
    return {"findings": [asdict(f) for f in findings], "score": score,
            "summary": {"pass": sum(f.status == "pass" for f in findings), "warn": sum(f.status == "warn" for f in findings),
                        "fail": sum(f.status == "fail" for f in findings)},
            "stats": {"lines": parsed["lines"], "words": parsed["words"], "images": len(parsed["images"]), "mermaid": parsed["mermaid"],
                      "code_blocks": len(parsed["blocks"]), "links": len(parsed["links"])}}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ── fetching (the only part that touches the network) ───────────────────────

def _gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    return r.stdout


_BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def http_status(url: str, timeout: int = 10, opener=urllib.request.urlopen) -> int | None:
    """Status of a link, or None when it cannot be judged (rate limited, blocked, or the network is down).
    A HEAD that says 404/410 is never believed on its own: some sites (Kaggle, 2026-10-05) answer HEAD or a
    script's User-Agent with 404 while the page is fine in a browser, so only a browser-style GET can declare a link dead."""
    for method in ("HEAD", "GET"):
        try:
            ua = "readme-audit/1.0" if method == "HEAD" else _BROWSER_UA
            req = urllib.request.Request(url, method=method, headers={"User-Agent": ua})
            with opener(req, timeout=timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 429, 999) or (method == "HEAD" and e.code in (404, 410)):
                if method == "HEAD":
                    continue
                return None if e.code != 404 else e.code
            return e.code
        except Exception:
            return None
    return None


def fetch(repo: str) -> tuple[str, set[str], dict, set[str] | None]:
    """README text, the repository's file list, metadata, and package.json scripts (when present)."""
    info = json.loads(_gh("api", f"repos/{repo}"))
    readme = json.loads(_gh("api", f"repos/{repo}/readme"))
    text = base64.b64decode(readme["content"]).decode("utf-8", "replace")
    tree = {t["path"] for t in json.loads(_gh("api", f"repos/{repo}/git/trees/{info['default_branch']}?recursive=1"))["tree"]}
    last = json.loads(_gh("api", f"repos/{repo}/commits?per_page=1"))[0]["commit"]["committer"]["date"]
    rc = json.loads(_gh("api", f"repos/{repo}/commits?path={readme['path']}&per_page=1"))
    readme_at = rc[0]["commit"]["committer"]["date"] if rc else None
    since = len(json.loads(_gh("api", f"repos/{repo}/commits?since={readme_at}&per_page=100"))) - 1 if readme_at else 0
    meta = {"description": info.get("description"), "topics": info.get("topics", []), "repo_commit_at": last, "readme_commit_at": readme_at,
            "commits_since_readme": max(since, 0), "readme_path": readme["path"], "default_branch": info["default_branch"], "private": info["private"]}
    scripts = None
    if "package.json" in tree:
        try:
            pkg = json.loads(base64.b64decode(json.loads(_gh("api", f"repos/{repo}/contents/package.json"))["content"]))
            scripts = set((pkg.get("scripts") or {}))
        except Exception:
            scripts = None
    return text, tree, meta, scripts


def fetch_local(path: str) -> tuple[str, set[str], dict, set[str] | None]:
    """The same inputs from a local clone: for checking a README BEFORE it is committed or pushed."""
    from pathlib import Path
    root = Path(path).expanduser()

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60).stdout
    readme = next((f for f in ("README.md", "README.rst", "README") if (root / f).exists()), None)
    if readme is None:
        raise RuntimeError(f"no README in {root}")
    text = (root / readme).read_text()
    tree = {l for l in git("ls-files").splitlines() if l}
    tree |= {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts and "venv" not in p.parts}
    last = git("log", "-1", "--format=%cI").strip() or None
    readme_at = git("log", "-1", "--format=%cI", "--", readme).strip() or None
    since = len([l for l in git("log", f"--since={readme_at}", "--format=%H").splitlines() if l]) - 1 if readme_at else 0
    meta = {"description": "(local)", "repo_commit_at": last, "readme_commit_at": readme_at, "commits_since_readme": max(since, 0)}
    scripts = None
    if (root / "package.json").exists():
        try:
            scripts = set((json.loads((root / "package.json").read_text()).get("scripts") or {}))
        except ValueError:
            scripts = None
    return text, tree, meta, scripts


def render_markdown(repo: str, audit_result: dict) -> str:
    out = [f"## {repo}", "",
           f"{audit_result['summary']['pass']} pass · {audit_result['summary']['warn']} warn · {audit_result['summary']['fail']} fail  ·  "
           f"{audit_result['stats']['lines']} lines, {audit_result['stats']['images']} image(s), {audit_result['stats']['code_blocks']} code block(s)", "",
           "| Goal | Score |", "|---|---|"]
    for g in GOALS:
        s = audit_result["score"][g]
        out.append(f"| {g} | {'n/a' if s is None else f'{int(s * 100)}%'} |")
    out.append("")
    for f in audit_result["findings"]:
        if f["status"] in ("warn", "fail", "info"):
            out.append(f"- **{f['status'].upper()}** [{f['goal']}/{f['check']}] {f['message']}" + (f" — {'; '.join(f['evidence'])}" if f["evidence"] else ""))
    return "\n".join(out) + "\n"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Audit a repository's README.")
    ap.add_argument("repos", nargs="+", help="owner/name, one or more (or a local path with --local)")
    ap.add_argument("--local", action="store_true", help="treat each argument as a local clone and audit its working-tree README")
    ap.add_argument("--json", action="store_true", help="JSON instead of markdown")
    ap.add_argument("--no-network-links", action="store_true", help="do not check external links")
    args = ap.parse_args()
    results = {}
    for repo in args.repos:
        try:
            text, tree, meta, scripts = fetch_local(repo) if args.local else fetch(repo)
            results[repo] = audit(text, tree, meta, scripts, None if args.no_network_links else http_status)
        except Exception as exc:
            results[repo] = {"error": str(exc)}
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for repo, r in results.items():
            print(f"## {repo}\n\nerror: {r['error']}\n" if "error" in r else render_markdown(repo, r))


if __name__ == "__main__":
    main()
