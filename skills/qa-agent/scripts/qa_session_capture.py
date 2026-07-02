#!/usr/bin/env python3
"""PostToolUse hook: when a handoff doc is written to ~/.claude/handoffs/,
extract key decisions/learnings and store them in qa-knowledge.

Wired in settings.local.json alongside emit-resume-prompt.py.
Never errors the originating tool — any failure exits silently.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from qa_capture import build_entry, store_entry, infer_pattern_type

HANDOFF_DIR = Path.home() / ".claude" / "handoffs"

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "bench-harness":  ["bench", "benchmark", "profile", "lean", "marvin profile",
                        "clean profile", "recall", "token", "scoring", "grading",
                        "task-00", "run 1", "run 2", "run 3", "run 4", "run 5"],
    "aws-cloud":      ["aws", "lambda", "s3", "eventbridge", "neptune", "gremlin",
                        "bedrock", "ecs", "aurora", "cloudtrail", "cloudwatch",
                        "iam", "cost explorer", "sns", "sqs", "fargate", "charter"],
    "python-agents":  ["chromadb", "claude code", "skill", "hook", "venv",
                        "agent", "memory", "retrieval", "embedding", "weasyprint",
                        "markdown-it", "pdfminer", "marvin", "resume-tailor"],
    "devtools":       ["git", "github", "keychain", "gitignore", "settings.json",
                        "setup.sh", "launchd", "plist", "zshrc", "alias"],
    "data-pipeline":  ["pipeline", "etl", "ingestion", "idempotent", "batch",
                        "dedup", "jsonl", "hash", "deduplication"],
    "web-backend":    ["fastapi", "flask", "api", "rest", "endpoint", "pydantic",
                        "openapi", "http", "router", "middleware"],
    "ml-ops":         ["llm", "fine-tun", "training", "inference", "classification",
                        "embedding model", "ollama", "nomic"],
}

FAILED_SIGNALS = {"failed", "doesn't work", "wrong", "broken", "bug", "dropped",
                   "removed", "avoid", "anti-pattern", "not worth", "inherently",
                   "backfired", "anti-correlated", "poisoning", "silently degrades"}
WORKED_SIGNALS = {"works", "fixed", "solved", "confirmed", "shipped", "correct",
                   "successful", "done", "complete", "green", "confirmed", "live",
                   "wired", "validated"}


def infer_domain(text: str) -> str:
    low = text.lower()
    scores = {d: sum(1 for kw in kws if kw in low)
              for d, kws in DOMAIN_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""


def infer_category(text: str) -> str:
    low = text.lower()
    if any(s in low for s in FAILED_SIGNALS):
        return "failed"
    if any(s in low for s in WORKED_SIGNALS):
        return "worked"
    return "pattern"


def extract_project(text: str) -> str:
    """Best-effort: find a project name in 'What we were working on' section."""
    m = re.search(r"##\s*What we were working on\s*\n(.*?)(?=\n##|\Z)", text,
                  re.DOTALL | re.IGNORECASE)
    if not m:
        return "session"
    snippet = m.group(1).strip()[:200]
    # look for known project patterns
    for proj in ("marvin-bench", "marvin", "resume-tailor", "charter", "hermes-agent"):
        if proj.lower() in snippet.lower():
            return proj
    return "session"


def extract_outcome(decision: str) -> str:
    """Best-effort: handoff decision bullets commonly follow a
    'decision — consequence' shape (em-dash separator), e.g. 'X is
    inherently necessary — not worth touching'. Only trust that
    unambiguous separator — an empty outcome beats a wrong guess."""
    for sep in (" — ", " -- "):
        if sep in decision:
            return decision.split(sep, 1)[1].strip()
    return ""


def extract_decisions(text: str) -> list[str]:
    """Extract bullet points from ## Key decisions made section."""
    m = re.search(r"##\s*Key decisions made\s*\n(.*?)(?=\n##|\Z)", text,
                  re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    block = m.group(1)
    bullets = []
    for line in block.splitlines():
        line = line.strip()
        # match "- ...", "* ...", "• ..." bullet lines with enough content
        if re.match(r"^[-*•]\s+.{20,}", line):
            content = re.sub(r"^[-*•]\s+", "", line).strip()
            if content:
                bullets.append(content)
    return bullets


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    if payload.get("tool_name", "") not in ("Write", "Edit", "MultiEdit"):
        return
    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return

    p = Path(fp)
    try:
        in_handoffs = HANDOFF_DIR.resolve() in [d.resolve() for d in p.parents]
    except Exception:
        in_handoffs = False
    if not in_handoffs or p.suffix.lower() != ".md":
        return

    try:
        text = p.read_text(errors="ignore")
    except Exception:
        return

    decisions = extract_decisions(text)
    if not decisions:
        return

    project = extract_project(text)
    stored = 0
    for decision in decisions:
        category = infer_category(decision)
        tags     = f"handoff,auto-capture,{project}"
        entry = build_entry(
            content=decision,
            category=category,
            domain=infer_domain(decision),
            pattern_type=infer_pattern_type(decision, tags, category),
            project=project,
            source="session",
            confidence="medium",
            tags=tags,
            outcome=extract_outcome(decision),
        )
        if store_entry(entry):
            stored += 1

    if stored:
        print(f"\n[qa-agent] auto-captured {stored} decision(s) from handoff → qa-knowledge", flush=True)


if __name__ == "__main__":
    main()
