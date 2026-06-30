"""Scoring helpers for the four metrics: token/context cost, turn/tool
efficiency, task correctness, memory/recall quality.

Correctness & recall are graded against a task's rubric.
- v0 (always active): deterministic substring/file checks via score_correctness().
- v1 (opt-in via --judge): LLM semantic grading via judge_run() in bench.py.
  LLM judge supplements substring grading; substring score is always computed.
"""
from __future__ import annotations
import json
from pathlib import Path


def parse_stream(stdout: str) -> dict:
    """Parse `claude --output-format stream-json --verbose` output into the
    signals we score on. Tolerates non-JSON noise lines."""
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    tool_uses = []
    result_event = None
    for ev in events:
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tool_uses.append(block.get("name"))
        elif ev.get("type") == "result":
            result_event = ev

    u = (result_event or {}).get("usage", {}) or {}
    input_tok = u.get("input_tokens", 0) or 0
    output_tok = u.get("output_tokens", 0) or 0
    cache_create = u.get("cache_creation_input_tokens", 0) or 0
    cache_read = u.get("cache_read_input_tokens", 0) or 0

    return {
        "is_error": (result_event or {}).get("is_error"),
        "result_text": (result_event or {}).get("result", ""),
        "num_turns": (result_event or {}).get("num_turns", 0),
        "duration_ms": (result_event or {}).get("duration_ms", 0),
        "cost_usd": (result_event or {}).get("total_cost_usd", 0.0),
        # token/context cost
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "cache_creation_input_tokens": cache_create,
        "cache_read_input_tokens": cache_read,
        "total_tokens": input_tok + output_tok + cache_create + cache_read,
        # turn/tool efficiency
        "tool_calls": len(tool_uses),
        "tools_used": tool_uses,
    }


def score_correctness(task: dict, result_text: str, workdir: Path | None) -> dict:
    """Deterministic v0 grading: every string in `expect` must appear either in
    the final result text or in any file under the workdir. Returns 0..1."""
    expects = task.get("expect", [])
    if not expects:
        return {"score": None, "note": "no expect[] defined; needs llm-judge"}

    haystacks = [result_text or ""]
    if workdir and workdir.exists():
        for p in workdir.rglob("*"):
            if p.is_file() and p.stat().st_size < 200_000:
                try:
                    haystacks.append(p.read_text(errors="ignore"))
                except OSError:
                    pass
    blob = "\n".join(haystacks)
    hits = [e for e in expects if e in blob]
    return {
        "score": round(len(hits) / len(expects), 3),
        "matched": hits,
        "missed": [e for e in expects if e not in blob],
    }
