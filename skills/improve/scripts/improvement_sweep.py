#!/usr/bin/env python3
"""PostToolUse hook: when a handoff doc is written, scan the project it describes
and append the top code-quality issues to ~/.claude/improvement-queue.md.

Runs after qa_session_capture so both hooks fire on the same handoff event.
Never blocks or errors the originating tool — any failure exits silently.
"""
from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
HANDOFF_DIR   = Path.home() / ".claude" / "handoffs"
QUEUE_FILE    = Path.home() / ".claude" / "improvement-queue.md"
QA_SCRIPTS    = Path.home() / ".agents" / "skills" / "qa-agent" / "scripts"

sys.path.insert(0, str(QA_SCRIPTS))


# ── project path resolution ────────────────────────────────────────────────────

KNOWN_PROJECTS: dict[str, Path] = {
    "marvin":        Path.home() / ".agents",
    "marvin-bench":  Path.home() / "marvin-bench",
    "resume-tailor": Path.home() / "resume-tailor",
    "hermes-agent":  Path.home() / "hermes-agent",
    "charter":       Path.home() / "charter",
    "portfolio":     Path.home() / "gileskayo.me",
}


def find_project_path(project_name: str) -> Path | None:
    low = project_name.lower()
    for key, path in KNOWN_PROJECTS.items():
        if key in low and path.exists():
            return path
    candidate = Path.home() / project_name
    if candidate.exists():
        return candidate
    return None


def extract_project(text: str) -> str:
    m = re.search(r"##\s*What we were working on\s*\n(.*?)(?=\n##|\Z)",
                  text, re.DOTALL | re.IGNORECASE)
    if not m:
        return "session"
    snippet = m.group(1).strip()[:200].lower()
    for name in KNOWN_PROJECTS:
        if name in snippet:
            return name
    return "session"


# ── issue prioritisation ───────────────────────────────────────────────────────

KIND_PRIORITY = ["logic", "naming", "verbosity", "style", "kiss", "oop",
                 "complexity", "comment"]


def top_issues(entries: list[dict], limit: int = 5) -> list[dict]:
    anti = [e for e in entries if e["metadata"]["category"] == "anti-pattern"]

    def sort_key(e):
        doc = e["document"]
        for i, kind in enumerate(KIND_PRIORITY):
            if f"[{kind.upper()}]" in doc:
                return i
        return len(KIND_PRIORITY)

    anti.sort(key=sort_key)
    # deduplicate by first 80 chars of document
    seen: set[str] = set()
    result = []
    for e in anti:
        key = e["document"][:80]
        if key not in seen:
            seen.add(key)
            result.append(e)
        if len(result) >= limit:
            break
    return result


def format_issue(entry: dict) -> str:
    doc = entry["document"]
    # pull out the [KIND] prefix, message, and file
    m = re.match(r"\[(\w+)\]\s*(.*?)\s*\(file:\s*([^)]+)\)", doc)
    if m:
        kind, msg, filepath = m.group(1), m.group(2), m.group(3).strip()
        # trim trailing "Suggestion: ..." from msg
        msg = re.sub(r"\s*Suggestion:.*$", "", msg).strip()
        return f"- **[{kind}]** {msg} (`{filepath}`)"
    return f"- {doc[:120]}"


# ── queue writer ───────────────────────────────────────────────────────────────

def append_to_queue(project_name: str, issues: list[dict]) -> None:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"\n---\n## {date_str} — {project_name}\n"]
    for issue in issues:
        lines.append(format_issue(issue))
    lines.append(
        f"\n*{len(issues)} item(s). "
        f"Run `qa_scan.py <project> --dry-run` for the full list.*\n"
    )
    block = "\n".join(lines)

    if not QUEUE_FILE.exists():
        QUEUE_FILE.write_text("# Improvement Queue\n\n" + block)
    else:
        existing = QUEUE_FILE.read_text()
        QUEUE_FILE.write_text(existing + block)


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return

    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return

    p = Path(fp)
    try:
        in_handoffs = HANDOFF_DIR.resolve() in [d.resolve() for d in p.parents]
    except Exception:
        return
    if not in_handoffs or p.suffix.lower() != ".md":
        return

    try:
        text = p.read_text(errors="ignore")
    except Exception:
        return

    project_name = extract_project(text)
    project_path = find_project_path(project_name)
    if project_path is None:
        project_path = Path.home() / ".agents"
        project_name = "marvin"

    try:
        from qa_scan import scan
        entries = scan(project_path)
    except Exception:
        return

    issues = top_issues(entries, limit=5)
    if not issues:
        return

    try:
        append_to_queue(project_name, issues)
        print(
            f"\n[improve] {len(issues)} improvement(s) queued for '{project_name}' "
            f"→ ~/.claude/improvement-queue.md",
            flush=True,
        )
    except Exception:
        return


if __name__ == "__main__":
    main()
