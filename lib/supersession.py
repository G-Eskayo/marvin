#!/usr/bin/env python3
"""Decision supersession (marvin#1226, extending ticket 652; data-freshness plan incident 7).

A decision restated in several docs went stale in all but one: the Workshop plan's answer put machine controls in
Vitals, and a later answered Decision put the throttle in Workshop ▸ Now. Nothing flagged the earlier copies. When the
owner answers Decisions, the follow-up that owner_decisions already files now lists every earlier answer to the same
question, so the PR that acts on them amends each one (an "Amendment (date)" note) or keeps it, explicitly.

Found two ways, both with the existing parsers (decisions.js through decisions_cli, relations.js through refs_cli):

  by id        a doc with a Decisions block that asks the same question id. Its ticked options are compared:
               "agrees", "differs", or "same id, different question" (the id was reused for something else).
               Under a History heading, or next to "superseded" / "amendment": "history (kept)".
  by relation  a doc that cites the ticket the PR closes or is part of (the capability), when it has no id hit.

Searched: CONTEXT.md, docs/ (ADRs, design, plans), instance/docs/plans and memory, never the PR's own files.
Contradictions in meaning still need judgment, so this only lists; it never edits a doc.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOME = Path.home()
_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_HISTORY = re.compile(r"\b(history|historical|superseded|amendment|no longer stands)\b", re.I)
_LINKING = re.compile(r"\b(closes|closed|fixes|resolves|part of)\b", re.I)


def default_roots() -> list[Path]:
    agents = HOME / ".agents"
    out = [agents / "CONTEXT.md", agents / "docs", agents / "instance" / "docs"]
    try:
        import host_os
        out.append(host_os.memory_dir())
    except Exception:  # noqa: BLE001
        pass
    return out


def _files(roots) -> list[Path]:
    seen, out = set(), []
    for r in roots:
        r = Path(r)
        for f in ([r] if r.is_file() else sorted(r.rglob("*.md")) if r.is_dir() else []):
            if f.suffix == ".md" and str(f) not in seen:
                seen.add(str(f))
                out.append(f)
    return out


def _words(q: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (q or "").lower()) if len(w) > 2}


def _same_question(a: str, b: str) -> bool:
    x, y = _words(a), _words(b)
    return bool(x and y) and len(x & y) / len(x | y) >= 0.5


def _history_near(lines: list[str], at: int) -> bool:
    heading = next((ln for ln in reversed(lines[:at]) if ln.startswith("## ")), "")
    return bool(_HISTORY.search(heading) or _HISTORY.search("\n".join(lines[max(0, at - 8):at])))


def earlier_answers(pr_body: str, *, roots=None, repo: str, exclude=frozenset(), node=True) -> list[dict] | None:
    """Earlier answers to the PR's answered questions, or None when the parsers can't run (say so, don't guess)."""
    import decisions_check
    import resume_check as rc
    node = decisions_check.find_node() if node is True else node
    if not node:
        return None
    now = decisions_check.parse(pr_body or "", node=node)
    if now is None:
        return None
    answered = {q["id"]: q for q in now.get("questions") or [] if q.get("chosen") or q.get("answer")}
    linking = "\n".join(ln for ln in (pr_body or "").splitlines() if _LINKING.search(ln))
    try:
        refs = set(rc.extract_refs([linking], repos=rc.default_repos(), default_repo=repo, node=node)[0]) if linking else set()
    except (RuntimeError, OSError, ValueError, KeyError):
        refs = set()
    if not answered and not refs:
        return []
    hits, id_docs, candidates = [], set(), []
    for f in _files(roots if roots is not None else default_roots()):
        if str(f) in exclude:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        plain = _FENCE.sub(" ", text)
        for qid, q in answered.items():
            m = re.search(rf"^###\s+{re.escape(qid)}\s*:", plain, re.M)
            if not m:
                continue
            doc = decisions_check.parse(text, node=node) or {}
            old = next((x for x in doc.get("questions") or [] if x.get("id") == qid and (x.get("chosen") or x.get("answer"))), None)
            if not old:
                continue
            lines = text.splitlines()
            at = text[:text.find(m.group(0))].count("\n") if m.group(0) in text else 0
            if _history_near(lines, at):
                verdict = "history (kept)"
            elif not _same_question(old["question"], q["question"]):
                verdict = "same id, different question"
            else:
                verdict = "agrees" if (old.get("chosen") or [old.get("answer")]) == (q.get("chosen") or [q.get("answer")]) else "differs"
            hits.append({"kind": "id", "id": qid, "path": str(f), "line": at + 1, "verdict": verdict,
                         "earlier": old.get("chosen") or [old.get("answer")], "now": q.get("chosen") or [q.get("answer")],
                         "question": old["question"]})
            id_docs.add(str(f))
        if refs and str(f) not in id_docs and any(re.search(rf"\b{k.rsplit('#', 1)[1]}\b", plain) for k in refs):
            candidates.append((f, text))
    if candidates:
        try:
            per = rc.extract_refs([t for _f, t in candidates], repos=rc.default_repos(), default_repo=repo, node=node)
        except (RuntimeError, OSError, ValueError, KeyError):
            per = []
        for (f, _t), doc_refs in zip(candidates, per):
            shared = sorted(refs & set(doc_refs))
            if shared:
                hits.append({"kind": "relation", "path": str(f), "line": 1, "verdict": "cites the same ticket",
                             "why": f"cites {', '.join(shared)}"})
    return hits


def section(hits: list[dict] | None, home: Path = HOME / ".agents", today: str | None = None) -> str:
    """The follow-up's "Earlier answers" section: one checkbox per hit, amend or keep."""
    title = "## Earlier answers to the same question"
    if hits is None:
        return (f"{title}\n\nCouldn't look for them (the decisions parser didn't run here). Check the plans, ADRs, CONTEXT "
                f"and memory for earlier answers by hand (marvin#1226).\n")
    if not hits:
        return ""
    from datetime import date
    day = today or date.today().isoformat()
    rows = []
    for h in hits:
        try:
            where = str(Path(h["path"]).relative_to(home))
        except ValueError:
            where = str(h["path"]).replace(str(HOME), "~", 1)
        if h["kind"] == "id":
            what = (f"`{h['id']}`: earlier \"{', '.join(map(str, h['earlier']))}\", now \"{', '.join(map(str, h['now']))}\" "
                    f"({h['verdict']})")
        else:
            what = f"{h['why']}: check it doesn't restate an older answer"
        rows.append(f"- [ ] `{where}`:{h['line']} {what}")
    return (f"{title}\n\nFound by decision id and by the docs that cite the same ticket (lib/supersession.py, marvin#1226). "
            f"For each, either amend it in this PR with an \"Amendment ({day})\" note naming the new answer, or keep it and "
            f"say why (history, or a different question).\n\n" + "\n".join(rows) + "\n")
