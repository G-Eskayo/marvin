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

    memory_lint.py [memory-dir] [--json]
"""
from __future__ import annotations

import json
import re
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
              "unindexed": [], "index_missing": [], "edges": [], "meta": {}}
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
    issues = len(r["conflicts"]) + len(r["dangling"]) + len(r["frontmatter"]) + len(r["unindexed"]) + len(r["index_missing"])
    head = f"{r['notes']} notes, {r['links']} links"
    tail = f"{len(r['orphans'])} with no inbound link"
    if not parts:
        return result("green", f"{head}, all resolve; {tail}", 0)
    return result("red" if r["conflicts"] else "yellow", f"{head}. " + "; ".join(parts) + f". {tail}", issues)


def _cli(argv: list[str]) -> int:
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
