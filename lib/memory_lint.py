#!/usr/bin/env python3
"""Memory lint (marvin#695): checks the memory folder's [[links]], its MEMORY.md index and each note's frontmatter.
It reports and suggests; it never edits a note.

Why: the memory notes are linked like a wiki, but nothing read the links. On 2026-10-26 there were dangling links, one
link broken across a line, 50-odd notes nothing linked to, and unresolved git conflict markers in MEMORY.md
(docs/research/knowledge-graphs-2026-10-26.md §4). This is the "lint" step of an LLM-maintained wiki.

A link resolves by a note's file stem or its `name:` (they differ for a few notes), case-insensitively, ignoring an
alias (`[[slug|label]]`) or heading (`[[slug#Why]]`). Links inside code (fenced or inline) are not links. MEMORY.md is
the index, not a note: its entries don't count as inbound links, or no note could ever be an orphan.

Cost: O(notes + links), one read per file.

Claims (marvin#1225): once a day, a project or reference note that asserts open state ("OPEN", "QUEUED", "URGENT",
"awaiting", outside code) has the ticket and PR refs on those lines checked with the resume check's reference checker
(lib/resume_check.py: relations.js through node, one GitHub call). When every ref it names is closed or merged, the
note is flagged with an `invalid_at` suggestion and its MEMORY.md index line gains "(closed <date>)". A feedback or
user note is a rule, still valid after its ticket closes, so it is never flagged on that alone. A note is never
edited; the index is the only thing written. A ref GitHub can't read leaves the note unflagged and is listed.

    memory_lint.py [memory-dir] [--json]
    memory_lint.py claims [memory-dir]     # the claims check now (ignores the day's saved result)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CHECK_ID, CHECK_LABEL = "memory:lint", "Memory links and index are sound"
INDEX = "MEMORY.md"
TYPES = ("user", "feedback", "project", "reference")
# Read from the metadata block alongside `type` (marvin#698): when a fact held, and what replaced it. Optional.
VALIDITY = ("valid_from", "invalid_at", "superseded_by")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"\[\[(.{1,200}?)\]\]", re.DOTALL)
_INDEX_LINK = re.compile(r"\]\(([^)\s]+\.md)\)")
# A choice parked on the owner in a note (marvin#1222) needs a home: front matter open_question (its ticket) + review_by.
_UNHOMED = re.compile(r"\bask gil\b|\bunresolved conflict\b|\buntil gil decides\b", re.I)


def _blank(m: re.Match) -> str:
    # keep newlines so line numbers still point at the right line
    return re.sub(r"[^\n]", " ", m.group(0))


def _strip_code(text: str) -> str:
    return _INLINE.sub(_blank, _FENCE.sub(_blank, text))


def _frontmatter(text: str) -> tuple[dict, str | None]:
    """(fields, problem). Reads top-level `key: value` and the `metadata:` block's `type:`; no YAML dependency."""
    if not text.startswith("---\n"):
        return {}, "no frontmatter"
    end = text.find("\n---", 4)
    if end < 0:
        return {}, "frontmatter is never closed"
    fields: dict = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^(\s*)([A-Za-z_]+):\s*(.*)$", line)
        if not m:
            continue
        indent, key, value = m.groups()
        if not indent or key == "type" or key in VALIDITY:
            v = value.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]  # a quoted YAML scalar
            fields.setdefault(key, v)
    for key in ("name", "description"):
        if not fields.get(key):
            return fields, f"missing {key}"
    t = fields.get("type")
    if not t:
        return fields, "missing type"
    if t not in TYPES:
        return fields, f"type '{t}' is not {'/'.join(TYPES)}"
    return fields, None


def _conflicts(text: str) -> list[int]:
    """Line numbers where a git conflict starts: a <<<<<<< line followed by ======= and >>>>>>> lines."""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if line.startswith("<<<<<<< ") or line == "<<<<<<<":
            rest = lines[i + 1:]
            mid = next((j for j, x in enumerate(rest) if x == "======="), None)
            if mid is not None and any(x.startswith(">>>>>>>") for x in rest[mid + 1:]):
                out.append(i + 1)
    return out


def _distance(a: str, b: str) -> int:
    """Edit distance counting a swap of two neighbours as one edit (optimal string alignment). O(len(a) * len(b))."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if prev2 and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _suggest(target: str, keys: dict[str, str]) -> str | None:
    """A real note this broken link most likely meant, or None. Only a typo (at most 2 edits) or a name with its type
    prefix left off (catch-x for feedback-catch-x). A similarity ratio is not enough: names share long prefixes
    (project-demo-deploy is not project-demo-app)."""
    by_prefix = [k for k in keys if k.endswith("-" + target) or k.endswith("_" + target)]
    if len(by_prefix) == 1:
        return keys[by_prefix[0]]
    best = min(keys, key=lambda k: _distance(target, k), default=None)
    if best is not None and _distance(target, best) <= (1 if len(target) < 6 else 2):
        return keys[best]
    return None


def lint(memory_dir: Path) -> dict:
    d = Path(memory_dir)
    files = sorted(p for p in d.glob("*.md") if p.is_file())
    texts: dict[str, str | None] = {}
    report = {"notes": 0, "links": 0, "dangling": [], "orphans": [], "conflicts": [], "frontmatter": [],
              "unindexed": [], "index_missing": [], "edges": [], "meta": {}, "unhomed": []}
    for p in files:
        try:
            texts[p.name] = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            texts[p.name] = None

    notes = [p for p in files if p.name != INDEX]
    report["notes"] = len(notes)
    keys: dict[str, str] = {}
    for p in notes:
        keys[p.stem.lower()] = p.stem
        text = texts[p.name]
        if text is None:
            report["frontmatter"].append({"file": p.name, "problem": "unreadable (not UTF-8)"})
            continue
        fields, problem = _frontmatter(text)
        report["meta"][p.stem] = {k: fields.get(k, "") for k in ("name", "description", "type", *VALIDITY)}
        for k in ("valid_from", "invalid_at"):
            if fields.get(k) and not _DATE.match(fields[k]):
                report["frontmatter"].append({"file": p.name, "problem": f"{k} '{fields[k]}' is not YYYY-MM-DD"})
        if fields.get("name"):
            keys.setdefault(fields["name"].lower(), p.stem)
        if problem:
            report["frontmatter"].append({"file": p.name, "problem": problem})
        m = _UNHOMED.search(_strip_code(text))
        if m and not fields.get("open_question"):
            report["unhomed"].append({"file": p.name, "phrase": m.group(0)})

    for name, text in texts.items():
        if text:
            report["conflicts"] += [{"file": name, "line": n} for n in _conflicts(text)]

    inbound: dict[str, set[str]] = {p.stem: set() for p in notes}
    edges: set[tuple[str, str]] = set()
    for p in notes:
        text = texts[p.name]
        if not text:
            continue
        body = _strip_code(text)
        for m in _LINK.finditer(body):
            report["links"] += 1
            raw = re.split(r"[|#]", m.group(1), maxsplit=1)[0]
            split = bool(re.search(r"\S\s*\n\s*\S", raw))
            target = re.sub(r"\s*\n\s*", "", raw).strip() if split else raw.strip()
            line = body.count("\n", 0, m.start()) + 1
            stem = keys.get(target.lower())
            if stem and not split:
                if stem != p.stem:
                    inbound[stem].add(p.stem)
                    edges.add((p.stem, stem))
                continue
            report["dangling"].append({"file": p.name, "line": line, "target": target, "split": split,
                                       "suggestion": stem or _suggest(target.lower(), keys)})
    # superseded_by is a link too: the replacement must exist, and a pair can't replace each other
    replaced: dict[str, str] = {}
    for stem, meta in report["meta"].items():
        ref = meta.get("superseded_by")
        if not ref:
            continue
        new = keys.get(ref.lower())
        if new is None:
            report["frontmatter"].append({"file": f"{stem}.md", "problem": f"superseded_by '{ref}' is not a note"})
            continue
        replaced[stem] = new
        if new != stem:
            inbound[new].add(stem)
            edges.add((stem, new))
    for old, new in replaced.items():
        if replaced.get(new) == old and old < new:
            report["frontmatter"].append({"file": f"{old}.md", "problem": f"{old} and {new} replace each other"})
    report["orphans"] = sorted(s for s, srcs in inbound.items() if not srcs)
    report["edges"] = sorted(edges)  # resolved note -> note links, self-links dropped (memory_graph.py builds on these)

    idx = texts.get(INDEX)
    if idx is not None:
        listed = {t for t in _INDEX_LINK.findall(idx) if "/" not in t}
        names = {p.name for p in notes}
        report["unindexed"] = sorted(p.stem for p in notes if p.name not in listed)
        report["index_missing"] = sorted(t for t in listed if t not in names)
    return report


def is_current(meta: dict, today=None) -> bool:
    """False once a note is superseded, or its invalid_at date has arrived. A replaced fact stays readable (history);
    it just stops being the answer."""
    from datetime import date
    if meta.get("superseded_by"):
        return False
    inv = meta.get("invalid_at") or ""
    return not (_DATE.match(inv) and inv <= (today or date.today()).isoformat())


# ── claims: open-state notes about finished work (marvin#1225) ────────────────────────────────────────────

CLAIMS_ID, CLAIMS_LABEL = "memory:claims", "Memory doesn't call finished work open"
OPEN_STATE = re.compile(r"\b(?:OPEN|QUEUED|URGENT)\b|(?i:\bawaiting\b)")
STALE_TYPES = ("project", "reference")   # feedback and user notes are rules: still valid after a ticket closes
CLAIMS_STATE = Path.home() / ".agents" / "var" / "memory-claims.json"
_CLOSED_MARK = r"(?: \(closed \d{4}-\d{2}-\d{2}\))?"


def _closed_on(node: dict) -> str | None:
    """YYYY-MM-DD the item was closed or merged, "" when closed with no date GitHub gave, None while open."""
    if node.get("state") not in ("CLOSED", "MERGED"):
        return None
    import resume_check as rc
    times = [rc._parse_time(node.get("mergedAt"))]
    times += [rc._parse_time((e or {}).get("createdAt")) for e in (node.get("timelineItems") or {}).get("nodes") or []
              if (e or {}).get("__typename") in ("ClosedEvent", "MergedEvent")]
    times = [t for t in times if t]
    return max(times).strftime("%Y-%m-%d") if times else ""


def claims(memory_dir: Path, *, run=subprocess.run, now: datetime | None = None, repos: dict | None = None,
           node=True) -> dict:
    """{status: checked | unverified, reason, notes, flagged: [{note, refs, closed, suggest}], unreadable, skipped}."""
    import resume_check as rc
    now = now or datetime.now(timezone.utc)
    out = {"status": "checked", "reason": None, "notes": 0, "flagged": [], "unreadable": [], "skipped": 0}
    candidates = []
    for p in sorted(Path(memory_dir).glob("*.md")):
        if p.name == INDEX:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        fields, _problem = _frontmatter(text)
        if fields.get("type") not in STALE_TYPES or not is_current(fields, today=now.date()):
            continue
        # The claim is the line that says it's open: a ref elsewhere (the PR that found a problem, history) isn't.
        lines = [ln for ln in _strip_code(text).splitlines() if OPEN_STATE.search(ln)]
        if lines:
            candidates.append((p.stem, lines))
    out["notes"] = len(candidates)
    if not candidates:
        return out
    node = rc.find_node() if node is True else node
    flat = [ln for _s, lines in candidates for ln in lines]
    try:
        per_line = rc.extract_refs(flat, repos=rc.default_repos() if repos is None else repos, default_repo=None,
                                   node=node)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
        return {**out, "status": "unverified", "reason": str(e) if isinstance(e, RuntimeError) else e.__class__.__name__}
    home = rc._home_repo()
    per_note, i = [], 0
    for _stem, lines in candidates:
        refs = []
        for line_refs in per_line[i:i + len(lines)]:
            # a bare "#3" belongs to the one repo its line names ("marvin-voice#21 then #3"), else the tickets repo
            named = {k.rsplit("#", 1)[0] for k in line_refs if not k.startswith("#")}
            default = next(iter(named)) if len(named) == 1 else home
            refs += [f"{default}{k}" if k.startswith("#") else k for k in line_refs]
        i += len(lines)
        per_note.append(list(dict.fromkeys(refs)))
    keys = list(dict.fromkeys(k for refs in per_note for k in refs))
    if not keys:
        return out
    asked = keys[:rc.MAX_REFS]
    out["skipped"] = len(keys) - len(asked)
    try:
        nodes = rc.fetch(asked, run=run, timeout=rc.BUDGET_S)
    except RuntimeError as e:
        return {**out, "status": "unverified", "reason": str(e)}
    out["unreadable"] = [k for k in asked if not nodes.get(k)]
    for (stem, _text), refs in zip(candidates, per_note):
        if not refs or any(k not in nodes or not nodes[k] for k in refs):
            continue  # nothing to judge by, or a ref we couldn't read: never call it stale on a guess
        dates = [_closed_on(nodes[k]) for k in refs]
        if any(d is None for d in dates):
            continue  # some of it is still open
        closed = max(dates) or now.strftime("%Y-%m-%d")
        out["flagged"].append({"note": stem, "refs": refs, "closed": closed, "suggest": f"invalid_at: {closed}"})
    return out


def annotate_index(index_text: str, closed: dict) -> str:
    """MEMORY.md with "(closed <date>)" right after each flagged note's link; idempotent, a newer date replaces."""
    for stem, day in closed.items():
        pat = re.compile(r"(\]\(" + re.escape(stem) + r"\.md\))" + _CLOSED_MARK)
        index_text = pat.sub(lambda m: f"{m.group(1)} (closed {day})", index_text)
    return index_text


def check_claims(memory_dir: Path | None = None, *, run=subprocess.run, now: datetime | None = None,
                 state_path: Path | None = None, repos: dict | None = None, node=True, force: bool = False) -> dict:
    """The daily claims check as a health row. A day's result is kept and reused that day; a day GitHub couldn't be
    read is never kept (and never green), so the next sweep tries again."""
    if memory_dir is None:
        import host_os
        memory_dir = host_os.memory_dir()
    now = now or datetime.now(timezone.utc)
    state_path = state_path or CLAIMS_STATE
    day = now.strftime("%Y-%m-%d")
    try:
        saved = json.loads(state_path.read_text())
    except (OSError, ValueError):
        saved = {}
    if not force and isinstance(saved, dict) and saved.get("day") == day and isinstance(saved.get("result"), dict):
        return saved["result"]

    def result(sev, detail, value=None):
        return {"id": CLAIMS_ID, "label": CLAIMS_LABEL, "severity": sev, "detail": detail,
                "checked_at": now.isoformat(), "value": value}

    if not Path(memory_dir).is_dir():
        return result("yellow", f"no memory folder at {memory_dir}")
    r = claims(Path(memory_dir), run=run, now=now, repos=repos, node=node)
    if r["status"] == "unverified":
        return result("yellow", f"couldn't check memory claims today: {r['reason']}")
    extra = []
    if r["unreadable"]:
        extra.append(f"{len(r['unreadable'])} ref(s) couldn't be read: {', '.join(r['unreadable'][:3])}")
    if r["skipped"]:
        extra.append(f"{r['skipped']} more ref(s) not checked")
    tail = ("; " + "; ".join(extra)) if extra else ""
    if r["flagged"]:
        index = Path(memory_dir) / INDEX
        try:
            text = index.read_text(encoding="utf-8")
            new = annotate_index(text, {f["note"]: f["closed"] for f in r["flagged"]})
            if new != text:
                index.write_text(new, encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
        ex = ", ".join(f"{f['note']} (all its refs closed by {f['closed']}; suggest {f['suggest']})"
                       for f in r["flagged"][:4])
        res = result("yellow", f"{_plural(len(r['flagged']), 'note')} still call finished work open: {ex}"
                     + (" …" if len(r["flagged"]) > 4 else "") + tail, len(r["flagged"]))
    else:
        res = result("green", f"{_plural(r['notes'], 'open-state note')} checked, none about finished work{tail}", 0)
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"day": day, "result": res, "flagged": r["flagged"]}))
    except OSError:
        pass
    return res


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def check(memory_dir: Path | None = None, now: datetime | None = None) -> dict:
    if memory_dir is None:
        import host_os
        memory_dir = host_os.memory_dir()
    now = now or datetime.now(timezone.utc)

    def result(sev, detail, value=None):
        return {"id": CHECK_ID, "label": CHECK_LABEL, "severity": sev, "detail": detail,
                "checked_at": now.isoformat(), "value": value}

    if not Path(memory_dir).is_dir():
        return result("yellow", f"no memory folder at {memory_dir}")
    r = lint(memory_dir)
    parts = []
    if r["conflicts"]:
        where = ", ".join(f"{c['file']}:{c['line']}" for c in r["conflicts"][:4])
        parts.append(f"{_plural(len(r['conflicts']), 'unresolved git conflict')} ({where})")
    if r["dangling"]:
        ex = ", ".join(f"[[{x['target']}]] in {x['file']}" + (f" (→ {x['suggestion']})" if x["suggestion"] else "")
                       for x in r["dangling"][:3])
        parts.append(f"{_plural(len(r['dangling']), 'broken link')}: {ex}")
    if r["frontmatter"]:
        ex = ", ".join(f"{x['file']} ({x['problem']})" for x in r["frontmatter"][:3])
        parts.append(f"{_plural(len(r['frontmatter']), 'note')} with bad frontmatter: {ex}")
    if r["unindexed"]:
        parts.append(f"{_plural(len(r['unindexed']), 'note')} missing from {INDEX}: {', '.join(r['unindexed'][:3])}")
    if r["index_missing"]:
        parts.append(f"{INDEX} lists {_plural(len(r['index_missing']), 'missing file')}: {', '.join(r['index_missing'][:3])}")
    if r["unhomed"]:
        parts.append(f"{_plural(len(r['unhomed']), 'note')} park a choice on the owner with no open_question "
                     f"(its ticket) and review_by: {', '.join(x['file'] for x in r['unhomed'][:3])}")
    issues = len(r["unhomed"]) + len(r["conflicts"]) + len(r["dangling"]) + len(r["frontmatter"]) + len(r["unindexed"]) + len(r["index_missing"])
    head = f"{r['notes']} notes, {r['links']} links"
    tail = f"{len(r['orphans'])} with no inbound link"
    if not parts:
        return result("green", f"{head}, all resolve; {tail}", 0)
    return result("red" if r["conflicts"] else "yellow", f"{head}. " + "; ".join(parts) + f". {tail}", issues)


def _cli(argv: list[str]) -> int:
    if argv[:1] == ["claims"]:
        rest = [a for a in argv[1:] if not a.startswith("--")]
        c = check_claims(Path(rest[0]).expanduser() if rest else None, force=True)
        print(f"[{c['severity']}] {c['detail']}")
        return 0
    args = [a for a in argv if not a.startswith("--")]
    d = Path(args[0]).expanduser() if args else None
    if "--json" in argv:
        import host_os
        print(json.dumps(lint(d or host_os.memory_dir()), indent=2))
    else:
        c = check(d)
        print(f"[{c['severity']}] {c['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
