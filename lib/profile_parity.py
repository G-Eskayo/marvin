#!/usr/bin/env python3
"""Do the owner's public profile facts match on every surface? (marvin#1038)

One facts file in the private instance repo (`config/public-profile.json`) holds every decided fact (headline, current
title, counts, names that must never appear) with its source and decision date, plus the rules that test a page against
those facts and the surfaces to read: live web pages, a PDF, a local file, a GitHub profile, a git branch of a site's
source. This module reads every surface it can reach, runs every rule on it and reports mismatches per surface and
field. The engine holds no facts of its own: everything owner-specific is in the facts file.

Honest by construction:
- a surface that can't be read is "couldn't check", never a pass, and a Health row with nothing checkable is unknown;
- a rule that is itself broken (bad pattern, missing fact) is a finding, not a silent skip;
- a value marked private (a phone number) is never printed: its own findings say "redacted", and every snippet shown
  for any finding has private matches blanked out.

Rule kinds (each may narrow itself with `surfaces` and `fields`, fnmatch patterns; `public_only` skips private surfaces):
  forbid      `pattern` must not appear. `private: true` redacts it; `status: "unconfirmed"` makes it a question.
  count       group 1 of `pattern` is a number (digits or a word) that must equal the fact's value (`op: "min"`: at least).
  title_near  any `title` match within `window` characters of `near` must be one of `allowed` (Jr == Junior).
  require     every one of `patterns` must appear in each selected field.

Surface kinds: url (`urls`), pdf (`url`, http(s) or file), file (`path`), github (`user`), git (`repo`, `refs` tried in
order, `paths` globs, optional `fetch`).

Run standalone: ~/.agents/venv/bin/python lib/profile_parity.py [--json] [--no-cache] [--facts PATH]
"""
from __future__ import annotations

import fnmatch
import hashlib
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import instance  # noqa: E402

CHECK_ID, CHECK_LABEL = "profile:parity", "Public profile matches everywhere"
CACHE_PATH = Path.home() / ".claude" / "logs" / "profile-parity.json"
REFRESH_HOURS = 6          # the sweep runs every few minutes; the live pages and GitHub are read at most this often
TIMEOUT_S = 10
# Some hosts' firewalls refuse urllib's default User-Agent ("Python-urllib/…") with 406.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) profile-parity"
GH = str(Path.home() / ".agents" / "bin" / "gh")  # the GitHub gate: every gh call goes through it
FINDING_KINDS = ("mismatch", "question", "rule-error")
REDACTED = "[private value, redacted]"

WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}


class Unreachable(Exception):
    """A surface (or one page of it) couldn't be read."""


def facts_path() -> Path:
    return instance.path("config", "public-profile.json")


_default_facts_path = facts_path


def load_facts(path: Path | None = None) -> dict | None:
    """The facts file, or None when the owner has none (the feature is off). A file that exists but isn't a JSON object
    raises ValueError, so the Health row can say which file is broken instead of going quiet."""
    path = Path(path or facts_path())
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None
    data = json.loads(raw)  # json.JSONDecodeError is a ValueError
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return data


# ── text ────────────────────────────────────────────────────────────────────────────────────────────────────────

_INVISIBLE = re.compile(r"<(script|style|noscript|template)\b.*?</\1\s*>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def html_text(markup: str) -> str:
    """What a visitor reads: no scripts, styles or comments, tags become spaces, entities decoded, whitespace collapsed."""
    t = _COMMENT.sub(" ", _INVISIBLE.sub(" ", markup))
    t = re.sub(r"<[^>]+>", " ", t)
    return _squash(htmllib.unescape(t))


def _squash(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def text_for(name: str, raw: str) -> str:
    suffix = Path(urllib.parse.urlparse(name).path or name).suffix.lower()
    if suffix in (".html", ".htm", ".astro", ".mdx", ".svg") or suffix == "" and "<" in raw[:2000]:
        return html_text(raw)
    if suffix == ".md":
        return _squash(_COMMENT.sub(" ", raw))  # a comment in a markdown resume is a note to self, not copy
    return _squash(raw)


# ── rules ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _number(token: str):
    t = token.strip().lower()
    if t.isdigit():
        return int(t)
    return WORDS.get(t)


def _norm_title(t: str) -> str:
    t = re.sub(r"[.\s]+", " ", t.lower()).strip()
    return re.sub(r"^junior\b", "jr", t)


def _applies(rule: dict, surface: dict, where: str) -> bool:
    if rule.get("public_only") and not surface.get("public", True):
        return False
    if rule.get("surfaces") and not any(fnmatch.fnmatch(surface.get("id", ""), p) for p in rule["surfaces"]):
        return False
    if rule.get("fields") and not any(fnmatch.fnmatch(where, p) for p in rule["fields"]):
        return False
    return True


def _private_patterns(facts: dict) -> list[re.Pattern]:
    out = []
    for r in facts.get("rules", []):
        if r.get("private") and r.get("pattern"):
            try:
                out.append(re.compile(r["pattern"], re.I))
            except re.error:
                pass
    return out


def _redact(s: str, private: list[re.Pattern]) -> str:
    for p in private:
        s = p.sub("[redacted]", s)
    return s


def _context(text: str, start: int, end: int, pad: int = 50) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def evaluate(facts: dict, surface: dict, texts: dict[str, str]) -> list[dict]:
    """Every finding for one surface. `texts` maps where-on-the-surface (a page path, a field, a file) to its text."""
    private = _private_patterns(facts)
    found: list[dict] = []
    seen: set = set()

    def add(rule, where, kind, was, want, ctx=""):
        key = (rule.get("id"), where, kind, str(was).lower(), want)
        if key in seen:
            return
        seen.add(key)
        found.append({"surface": surface.get("id", ""), "label": surface.get("label", surface.get("id", "")),
                      "rule": rule.get("id", ""), "field": rule.get("field") or rule.get("id", "?"), "where": where,
                      "kind": kind, "was": _redact(str(was), private), "want": _redact(str(want), private),
                      "context": _redact(ctx, private)})

    for rule in facts.get("rules", []):
        for where, text in texts.items():
            if not _applies(rule, surface, where):
                continue
            try:
                _apply(rule, facts, where, text, add)
            except (re.error, KeyError, TypeError, ValueError) as exc:
                add(rule, where, "rule-error", f"{type(exc).__name__}: {exc}", "a working rule")
                break
    return found


def _matches(rule: dict, key: str, text: str):
    """finditer for the rule's pattern, case-insensitive unless the rule says otherwise, minus the matches whose
    surroundings (40 characters each side) match the rule's `except` pattern (a dated history line, say)."""
    flags = 0 if rule.get("case_sensitive") else re.I
    rx = re.compile(rule[key], flags)
    skip = re.compile(rule["except"], re.I) if rule.get("except") else None
    for m in rx.finditer(text):
        if skip and skip.search(text[max(0, m.start() - 40): m.end() + 40]):
            continue
        yield m


def _apply(rule: dict, facts: dict, where: str, text: str, add) -> None:
    kind = rule.get("kind")
    if kind == "forbid":
        status = "question" if rule.get("status") == "unconfirmed" else "mismatch"
        want = rule.get("want") or ("ask the owner before stating it" if status == "question" else "not shown")
        for m in _matches(rule, "pattern", text):
            was = REDACTED if rule.get("private") else m.group(0)
            add(rule, where, status, was, want, _context(text, m.start(), m.end()))
    elif kind == "count":
        if "fact" in rule:
            expected = facts["facts"][rule["fact"]]["value"]  # KeyError → rule-error
        else:
            expected = rule["expected"]
        expected = int(expected)
        op = rule.get("op", "eq")
        for m in _matches(rule, "pattern", text):
            n = _number(m.group(1))
            ok = n is not None and (n >= expected if op == "min" else n == expected)
            if not ok:
                add(rule, where, "mismatch", m.group(1) if n is None else str(n), f"{expected} or more" if op == "min" else str(expected),
                    _context(text, m.start(), m.end()))
    elif kind == "title_near":
        # The title paired with an employer is the nearest title on each side of it, within `window` characters: a
        # headline title followed by the real one ("AI ENGINEER Jr AI Engineer at Charter") pairs the real one.
        near = re.compile(rule["near"], re.I)
        titles = list(re.finditer(rule["title"], text, re.I))
        allowed = {_norm_title(a) for a in rule["allowed"]}
        window = int(rule.get("window", 60))
        for e in near.finditer(text):
            before = [t for t in titles if t.end() <= e.start() and e.start() - t.end() <= window]
            after = [t for t in titles if t.start() >= e.end() and t.start() - e.end() <= window]
            for t in ([before[-1]] if before else []) + ([after[0]] if after else []):
                if _norm_title(t.group(0)) not in allowed:
                    add(rule, where, "mismatch", t.group(0), rule["allowed"][0],
                        _context(text, min(t.start(), e.start()), max(t.end(), e.end()), 20))
    elif kind == "require":
        for p in rule["patterns"]:
            if not re.search(p, text, re.I | re.M):
                add(rule, where, "mismatch", "missing", re.sub(r"\(\?\w+\)|[\^$\\]", "", p))
    else:
        raise ValueError(f"unknown rule kind {kind!r}")


# ── surfaces ────────────────────────────────────────────────────────────────────────────────────────────────────

def _get(url: str, timeout: float) -> bytes:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as exc:  # noqa: BLE001 -- any failure to read a page is "couldn't check" with the reason
        raise Unreachable(f"{url}: {type(exc).__name__}: {str(exc)[:120]}") from None


def _where(url: str) -> str:
    u = urllib.parse.urlparse(url)
    return u.path if u.scheme in ("http", "https") and u.path else url


def _read_urls(s: dict, timeout: float, **_) -> tuple[dict, list[str]]:
    texts, errors = {}, []
    for url in s.get("urls", []):
        try:
            texts[_where(url)] = html_text(_get(url, timeout).decode("utf-8", "replace"))
        except Unreachable as exc:
            errors.append(str(exc))
    return texts, errors


def pdf_extractor():
    """A callable bytes -> text, or None when this machine has no PDF text tool (poppler's pdftotext)."""
    exe = shutil.which("pdftotext") or next((p for p in ("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext",
                                                         "/usr/bin/pdftotext") if os.path.exists(p)), None)
    if not exe:
        return None

    def extract(data: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(data)
            f.flush()
            out = subprocess.run([exe, "-q", f.name, "-"], capture_output=True, timeout=30)
        if out.returncode != 0:
            raise Unreachable(f"pdftotext failed ({out.returncode})")
        return out.stdout.decode("utf-8", "replace")
    return extract


def _read_pdf(s: dict, timeout: float, **_) -> tuple[dict, list[str]]:
    data = _get(s["url"], timeout)
    if not data.startswith(b"%PDF"):
        raise Unreachable(f"{s['url']}: not a PDF ({data[:20]!r}…)")
    extract = pdf_extractor()
    if extract is None:
        raise Unreachable("no PDF text extractor on this machine (install poppler for pdftotext)")
    return {"pdf": _squash(extract(data))}, []


def _read_file(s: dict, **_) -> tuple[dict, list[str]]:
    p = Path(os.path.expanduser(s["path"]))
    try:
        raw = p.read_text()
    except OSError as exc:
        raise Unreachable(f"{s['path']}: {type(exc).__name__}") from None
    return {p.name: text_for(p.name, raw)}, []


def _gh_default(args: list[str]):
    out = subprocess.run([GH, *args], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise Unreachable(f"gh {' '.join(args[:2])}: {(out.stderr or out.stdout).strip()[:160]}")
    return json.loads(out.stdout or "null")


PINS_QUERY = "query($login:String!){user(login:$login){pinnedItems(first:6){nodes{... on Repository{name}}}}}"


def _read_github(s: dict, gh=None, **_) -> tuple[dict, list[str]]:
    gh = gh or _gh_default
    user = s["user"]
    try:
        prof = gh(["api", f"users/{user}"]) or {}
        pins = gh(["api", "graphql", "-f", f"query={PINS_QUERY}", "-f", f"login={user}"]) or {}
        repos = gh(["repo", "list", user, "--visibility", "public", "--limit", "200", "--json", "name,description"]) or []
    except Unreachable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise Unreachable(f"GitHub: {type(exc).__name__}: {str(exc)[:160]}") from None
    texts = {"bio": _squash(prof.get("bio") or ""), "company": _squash(prof.get("company") or "")}
    nodes = (((pins.get("data") or {}).get("user") or {}).get("pinnedItems") or {}).get("nodes") or []
    texts["pins"] = "\n".join(n.get("name", "") for n in nodes if n)
    for r in repos:
        texts[f"repo {r.get('name')}"] = _squash(r.get("description") or "")
    return texts, []


def _git(repo: Path, *args, timeout=30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout)


def _read_git(s: dict, **_) -> tuple[dict, list[str]]:
    repo = Path(os.path.expanduser(s["repo"]))
    if not (repo / ".git").exists():
        raise Unreachable(f"{s['repo']}: no git checkout on this machine")
    if s.get("fetch"):
        try:
            _git(repo, "fetch", "-q", "origin", timeout=60)
        except subprocess.TimeoutExpired:
            pass  # read whatever refs are already here
    ref = next((r for r in s.get("refs", ["HEAD"]) if _git(repo, "rev-parse", "--verify", "--quiet", f"{r}^{{commit}}").returncode == 0), None)
    if ref is None:
        raise Unreachable(f"{s['repo']}: none of {', '.join(s.get('refs', []))} exists")
    names = _git(repo, "ls-tree", "-r", "--name-only", ref).stdout.decode().splitlines()
    picked = [n for n in names if any(fnmatch.fnmatch(n, g) for g in s.get("paths", ["*"]))]
    if not picked:
        raise Unreachable(f"{ref}: no files match {', '.join(s.get('paths', []))}")
    texts = {}
    for n in picked:
        raw = _git(repo, "show", f"{ref}:{n}").stdout.decode("utf-8", "replace")
        texts[n] = text_for(n, raw)
    s["_ref"] = ref
    return texts, []


READERS = {"url": _read_urls, "pdf": _read_pdf, "file": _read_file, "github": _read_github, "git": _read_git}


def check_surface(facts: dict, s: dict, timeout: float = TIMEOUT_S, gh=None) -> tuple[dict, list[dict]]:
    head = {"id": s.get("id", "?"), "label": s.get("label", s.get("id", "?"))}
    reader = READERS.get(s.get("kind"))
    if reader is None:
        return {**head, "status": "couldnt_check", "why": f"unknown surface kind {s.get('kind')!r}"}, []
    s = dict(s)
    try:
        texts, errors = reader(s, timeout=timeout, gh=gh)
    except Unreachable as exc:
        return {**head, "status": "couldnt_check", "why": str(exc)}, []
    except Exception as exc:  # noqa: BLE001 -- one broken surface never hides the others
        return {**head, "status": "couldnt_check", "why": f"{type(exc).__name__}: {str(exc)[:160]}"}, []
    findings = evaluate(facts, s, texts)
    row = {**head, "status": "couldnt_check" if errors else "checked", "read": len(texts)}
    if errors:
        row["why"] = "; ".join(errors)
    if s.get("_ref"):
        row["ref"] = s["_ref"]
    return row, findings


def run(facts: dict, timeout: float = TIMEOUT_S, gh=None) -> dict:
    surfaces = facts.get("surfaces", [])
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(surfaces)))) as pool:
        results = list(pool.map(lambda s: check_surface(facts, s, timeout, gh), surfaces))
    rows = [r for r, _ in results]
    findings = [f for _, fs in results for f in fs]
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "surfaces": rows, "findings": findings,
            "mismatches": sum(1 for f in findings if f["kind"] in FINDING_KINDS),
            "unchecked": sum(1 for r in rows if r["status"] != "checked")}


# ── Health ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _row(severity: str, detail: str, value=None, **extra) -> dict:
    return {"id": CHECK_ID, "label": CHECK_LABEL, "severity": severity, "detail": detail,
            "checked_at": datetime.now(timezone.utc).isoformat(), "value": value, **extra}


def _say(f: dict) -> str:
    if f["kind"] == "question":
        return f"{f['label']} · {f['field']} ({f['where']}): \"{f['was']}\" needs the owner's answer"
    return f"{f['label']} · {f['field']} ({f['where']}): was \"{f['was']}\", want \"{f['want']}\""


def health_row(report: dict) -> dict:
    rows, findings = report.get("surfaces", []), report.get("findings", [])
    checked = [r for r in rows if r.get("status") == "checked"]
    unchecked = [r for r in rows if r.get("status") != "checked"]
    if findings:
        shown = "; ".join(_say(f) for f in findings[:3])
        more = f"; and {len(findings) - 3} more" if len(findings) > 3 else ""
        tail = f". Couldn't check: {', '.join(r['label'] for r in unchecked)}" if unchecked else ""
        return _row("yellow", f"{len(findings)} to fix: {shown}{more}{tail}", value=len(findings))
    if rows and not checked:
        return {**_row("unknown", "couldn't check any surface: " + "; ".join(f"{r['label']} ({r.get('why', '?')})" for r in unchecked)[:400]), "measured": False}
    if unchecked:
        return _row("yellow", "couldn't check " + "; ".join(f"{r['label']} ({r.get('why', '?')[:120]})" for r in unchecked)
                    + f". The other {len(checked)} match", value=0)
    return _row("green", f"{len(checked)} surfaces match the facts file", value=0)


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def check(facts_path: Path | None = None, cache_path: Path | None = None, runner=run, now: datetime | None = None,
          force: bool = False) -> dict | None:
    """The Health row. None when the owner keeps no facts file. The surfaces are read at most every REFRESH_HOURS (or
    as soon as the facts file changes); in between the last report is shown."""
    fp = Path(facts_path or _default_facts_path())
    cp = Path(cache_path or CACHE_PATH)
    try:
        facts = load_facts(fp)
    except ValueError as exc:
        return _row("yellow", f"{fp.name} can't be read: {str(exc)[:160]}")
    if facts is None:
        return None
    digest = _digest(fp)
    now = now or datetime.now(timezone.utc)
    try:
        cached = json.loads(cp.read_text())
        age = (now - datetime.fromisoformat(cached["report"]["generated_at"])).total_seconds()
        if not force and cached.get("digest") == digest and 0 <= age < REFRESH_HOURS * 3600:
            return health_row(cached["report"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    report = runner(facts)
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_suffix(".tmp")
        tmp.write_text(json.dumps({"digest": digest, "report": report}, indent=1))
        tmp.replace(cp)
    except OSError:
        pass
    return health_row(report)


def _print(report: dict) -> None:
    for r in report["surfaces"]:
        extra = f" @ {r['ref']}" if r.get("ref") else ""
        print(f"[{'checked' if r['status'] == 'checked' else 'COULDN T CHECK'}] {r['label']}{extra}"
              + (f": {r['why']}" if r.get("why") else ""))
    print()
    for f in report["findings"]:
        print(f"  {f['kind']:>10}  {_say(f)}")
    print(f"\n{report['mismatches']} findings, {report['unchecked']} surfaces couldn't be checked")


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--facts", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-cache", action="store_true", help="read every surface now, and don't touch the cache")
    a = ap.parse_args(argv)
    fp = a.facts or facts_path()
    facts = load_facts(fp)
    if facts is None:
        print(f"no facts file at {fp}", file=sys.stderr)
        return 2
    if a.no_cache:
        report = run(facts)
    else:
        check(facts_path=fp, cache_path=CACHE_PATH, runner=run, force=True)
        report = json.loads(CACHE_PATH.read_text())["report"]
    print(json.dumps(report, indent=1)) if a.json else _print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
