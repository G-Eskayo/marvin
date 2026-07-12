#!/usr/bin/env python3
"""Generates a fresh handoff doc from a live (possibly still-open) Claude
Code session transcript. The cold, detached counterpart to the `handoff`
skill's normal path (the live model writing it with full context already
in its head) — used when there's no live model to ask, specifically the
arrival-triggered on-demand design for cross-machine session continuity.

Deliberately does NOT hand the raw .jsonl to the detached claude -p call
via the Read tool — a long session's transcript can run to thousands of
lines, and most of it (tool_result blobs, thinking blocks) isn't handoff
material anyway. Instead extracts just the human-relevant thread (user
text, assistant text, a one-line note for each tool call) directly in
Python, capped to the most recent N messages, and embeds that excerpt in
the prompt — bounded cost regardless of session length, matching
daily_digest.py's "assemble real context, don't make the model discover
it" pattern.

Usage: generate_handoff_from_transcript.py <transcript-path>
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _resolve_claude_bin() -> str:
    """Dispatched here via task_dispatch.py's plain-bash wrapper script over
    SSH — a non-interactive, non-login shell that doesn't source
    .zshrc/.zprofile, so PATH may not include wherever `claude` is actually
    installed. Same gotcha as daily_digest.py and find_freshest_session.py."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("claude CLI not found on PATH or in common install locations")

MAX_MESSAGES = 60
MAX_BLOCK_CHARS = 800
HANDOFF_DIR = Path.home() / ".claude" / "handoffs"
SKILL_PATH = Path.home() / ".agents" / "skills" / "handoff" / "SKILL.md"


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_use":
            name = block.get("name", "?")
            parts.append(f"[used tool: {name}]")
        elif btype == "tool_result":
            raw = block.get("content", "")
            text = raw if isinstance(raw, str) else json.dumps(raw)
            if len(text) > MAX_BLOCK_CHARS:
                text = text[:MAX_BLOCK_CHARS] + "…[truncated]"
            parts.append(f"[tool result: {text}]")
        # "thinking" blocks deliberately skipped — internal, often empty/redacted
    return "\n".join(p for p in parts if p.strip())


def extract_recent_excerpt(transcript_path: Path, max_messages: int = MAX_MESSAGES) -> str:
    messages = []
    with transcript_path.open(errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") not in ("user", "assistant"):
                continue
            text = _extract_text(d.get("message", {}).get("content"))
            if not text.strip():
                continue
            messages.append((d["type"], text))

    recent = messages[-max_messages:]
    lines = []
    for role, text in recent:
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {text}")
    return "\n\n".join(lines)


PROMPT_TEMPLATE = """You are generating a handoff document for Gil's MARVIN system, from a
still-open (or just-finished) Claude Code session's transcript — you were dispatched because Gil
switched to a different machine and there's no live model with this conversation's context to ask
directly. This is a cold, best-effort reconstruction, not a live summary — say so is not needed,
just do your best with what's below.

Read {skill_path} in full and follow its "Document Structure" section EXACTLY — same headers, same
Resume prompt block format. This is the same document format the `handoff` skill always produces,
just generated differently.

Here is the most recent portion of the conversation (oldest first), reconstructed from the raw
transcript — tool calls are noted but not shown in full, tool results are truncated:

---
{excerpt}
---

Save the handoff to {handoff_dir}/handoff-{timestamp}.md — use the Write tool, nothing else needs
touching. Do not print the resume prompt to stdout; just write the file.
"""


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: generate_handoff_from_transcript.py <transcript-path>", file=sys.stderr)
        sys.exit(1)

    transcript_path = Path(sys.argv[1])
    if not transcript_path.is_file():
        print(f"transcript not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)

    excerpt = extract_recent_excerpt(transcript_path)
    if not excerpt.strip():
        print("no extractable content in transcript — nothing to summarize", file=sys.stderr)
        sys.exit(0)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M")
    prompt = PROMPT_TEMPLATE.format(
        skill_path=SKILL_PATH, excerpt=excerpt, handoff_dir=HANDOFF_DIR, timestamp=timestamp,
    )

    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    try:
        claude_bin = _resolve_claude_bin()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    proc = subprocess.run(
        [claude_bin, "-p", prompt, "--tools", "Read,Write", "--permission-mode", "bypassPermissions", "--output-format", "text"],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        print(f"handoff generation failed: {proc.stderr[:500]}", file=sys.stderr)
        sys.exit(1)
    print(f"handoff generated for {timestamp}")


if __name__ == "__main__":
    main()
