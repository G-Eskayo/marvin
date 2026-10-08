#!/usr/bin/env python3
"""The MARVIN launcher: the one way a model run starts (ADR 0059, marvin#302).

The caller names a launch kind (glossary: CONTEXT.md, "MARVIN context and launch kinds"). The launcher
gives the run exactly the layers of MARVIN context that kind declares, sets the kind marker and the
permission leash, runs the caller's preflight before any tokens are spent, and records the run so
Metrics and Health can see every launch with its kind and token counts.

Which layers reach a run is decided by the KINDS table below, never by the folder a run starts in.
Rules and Skills come from Claude Code itself (global CLAUDE.md and skills load everywhere); Hooks
arrive with marvin#291. The layers this module injects into the prompt are the ones Claude Code
can't deliver outside the home folder: North stars, the Memory index, the Lexicon and the
work-rules slice.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import north_stars

MEMORY_DIR = Path.home() / ".claude" / "projects" / str(Path.home()).replace("/", "-") / "memory"
LEXICON = Path.home() / ".claude" / "lexicon.md"
LAUNCH_LOG = Path.home() / ".claude" / "logs" / "launches.jsonl"
KIND_ENV = "MARVIN_LAUNCH_KIND"


@dataclass(frozen=True)
class LaunchKind:
    title: str  # as written in the glossary
    layers: frozenset[str]


def _layers(*names: str) -> frozenset[str]:
    return frozenset(names)


_FULL = ("rules", "north-stars", "memory", "lexicon", "skills", "hooks")

KINDS: dict[str, LaunchKind] = {
    "interactive": LaunchKind("Interactive", _layers(*_FULL, "session-report")),
    "ticket-planner": LaunchKind("Ticket planner", _layers(*_FULL)),
    # North stars reach the executor only through the plan's north-star fit.
    "ticket-executor": LaunchKind("Ticket executor", _layers("rules", "work-rules", "lexicon", "skills", "hooks")),
    "background-analyst": LaunchKind("Background analyst", _layers(*_FULL)),
    "utility-call": LaunchKind("Utility call", _layers("output-rules", "telemetry-hooks")),
    # A checker must not share the context of what it checks. Known gap: Claude Code still loads the global
    # CLAUDE.md (only --bare skips it, and --bare needs an API key, which MARVIN deliberately doesn't use).
    "judge": LaunchKind("Judge", _layers("telemetry-hooks")),
}

_OUTPUT_RULES = "Never show a ticket or PR number on its own: always pair it with its title."


def _body(note: Path) -> str:
    parts = note.read_text().split("---", 2)
    return parts[2].strip() if len(parts) == 3 and parts[0] == "" else note.read_text().strip()


def work_rule_notes(memory_dir: Path | None = None) -> list[Path]:
    """Memory notes tagged `work-rule` in their frontmatter: derived, never hand-picked."""
    found = []
    for note in sorted((memory_dir or MEMORY_DIR).glob("*.md")):
        head = note.read_text().split("---", 2)
        if len(head) == 3 and re.search(r"^\s*tags:.*\bwork-rule\b", head[1], re.M):
            found.append(note)
    return found


def assemble_context(kind: str) -> str:
    """The prompt preamble carrying the layers of `kind` that Claude Code can't deliver by itself."""
    layers = KINDS[kind].layers
    sections = []
    if "north-stars" in layers:
        sections.append(("North stars (docs/north-stars.md)", north_stars.load()))
    if "memory" in layers:
        sections.append(("MARVIN memory index (open a note with Read when it matters: "
                         f"{MEMORY_DIR})", (MEMORY_DIR / "MEMORY.md").read_text().strip()))
    if "work-rules" in layers:
        rules = "\n\n".join(f"### {n.stem}\n{_body(n)}" for n in work_rule_notes())
        sections.append(("Work rules (how work gets done here)", rules))
    if "lexicon" in layers:
        sections.append(("Lexicon (apply these terms without explanation)", LEXICON.read_text().strip()))
    if "output-rules" in layers:
        sections.append(("Output rules", _OUTPUT_RULES))
    return "".join(f"=== {title} ===\n{text}\n\n" for title, text in sections)


@dataclass
class LaunchResult:
    text: str
    cost_usd: float
    exit_code: int
    stderr: str = ""


def _record(log_path: Path, record: dict) -> None:
    # Best-effort: a broken log must never break the run it observes.
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def launch(kind: str, prompt: str, *, cwd: Path | None = None, model: str | None = None,
           allowed_tools: str | None = None, disallowed_tools: str | None = None, tools: str | None = None,
           permission_mode: str | None = "dontAsk", timeout: float | None = None, env: dict | None = None,
           ticket: str | None = None, preflight: Callable[[], None] | None = None,
           log_path: Path | None = None, runner: Callable | None = None) -> LaunchResult:
    """Start one headless run of `kind`. Raises before spending tokens if the preflight fails.

    Flags left as None aren't passed, so the caller's leash is exactly what it asks for. A Judge with no
    folder given runs in a fresh empty one, so it can't see the workspace of what it judges."""
    context = assemble_context(kind)
    if preflight is not None:
        preflight()
    from claude_bin import resolve_claude_bin
    cmd = [resolve_claude_bin(), "-p", context + prompt]
    for flag, value in (("--model", model), ("--permission-mode", permission_mode), ("--tools", tools),
                        ("--allowedTools", allowed_tools or None), ("--disallowedTools", disallowed_tools or None)):
        if value is not None:
            cmd += [flag, value]
    cmd += ["--output-format", "json"]
    run_env = {**(env if env is not None else os.environ), KIND_ENV: kind}
    scratch = tempfile.TemporaryDirectory(prefix="marvin-judge-") if kind == "judge" and cwd is None else None
    run_cwd = scratch.name if scratch else cwd
    started = time.monotonic()
    try:
        proc = (runner or subprocess.run)(cmd, cwd=run_cwd, timeout=timeout, env=run_env,
                                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    finally:
        if scratch:
            scratch.cleanup()
    try:
        parsed = json.loads(getattr(proc, "stdout", None))
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if not isinstance(parsed, dict):
        parsed = None
    usage = (parsed or {}).get("usage") or {}
    text = parsed.get("result", "") if parsed else (getattr(proc, "stdout", None) or "")
    cost = (parsed or {}).get("total_cost_usd", 0.0) or 0.0
    exit_code = proc.returncode or (1 if parsed and parsed.get("is_error") else 0)
    _record(log_path or LAUNCH_LOG, {
        "at": datetime.now(timezone.utc).isoformat(), "kind": kind, "model": model, "ticket": ticket,
        "cwd": str(run_cwd) if run_cwd else None, "exit_code": exit_code, "duration_s": round(time.monotonic() - started, 1),
        "cost_usd": cost, "context_chars": len(context),
        "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
    })
    return LaunchResult(text, cost, exit_code, getattr(proc, "stderr", "") or "")
