#!/usr/bin/env python3
"""A Jev-style (typesafe.ai "System One") Choice classifier for route.py's
intent routing, built to A/B against the existing keyword/embedding
classifiers on the exact same holdout fixture (see validate_holdout_jev.py).

Why this exists: TypeSafe AI's Jev ships a Choice/Score/Noul primitive --
state + typed criteria -> one typed, confidence-scored answer, no free text.
Their own official system-one-adapter-python repo demonstrates the same
primitive is trivially reproducible on top of any LLM's structured-output
support, not proprietary to their hosted API (see project chat 2026-10-01).
This module reproduces just the Choice primitive on Claude Code's own
`--json-schema` flag -- no new API key, no new billable surface, uses the
existing Claude Code subscription the same way bench.py/select_model.py
already do (per [[feedback-low-cost-experimentation]]: no paid Anthropic API
creds, deliberately).

Deliberately `--tools ""` (zero tool access, same isolation fix as
judge_run() in bench.py -- see marvin-bench-harness memory, Run 15): Jev's
own primitives never touch tools, state+criteria in, one typed answer out.
Each call is a brand-new `claude -p` process (no persistent session), so
the ~10k-token system/schema cache-creation cost is paid on every single
call -- a real cost this comparison is specifically built to surface, not
hide.

Criteria text is pulled from intent_classify.REFERENCE_EXAMPLES (already
hand-curated, already used to seed the embedding classifier) rather than
written fresh -- same four intents, same source of truth, no duplicate
criteria to drift out of sync.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
from intent_classify import REFERENCE_EXAMPLES  # noqa: E402

MODEL = "claude-haiku-4-5-20251001"
INTENTS = list(REFERENCE_EXAMPLES.keys())
SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": INTENTS},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["choice", "confidence"],
})


def _criteria_block() -> str:
    lines = []
    for intent, examples in REFERENCE_EXAMPLES.items():
        shown = examples[:4]
        lines.append(f"- {intent}: " + " | ".join(f'"{e}"' for e in shown))
    return "\n".join(lines)


def _prompt(description: str) -> str:
    return (
        f'State: "{description}"\n\n'
        "Classify which category this request belongs to. Categories, each "
        "with example requests that belong to it:\n"
        f"{_criteria_block()}\n\n"
        "Choose exactly one category and a confidence 0-1 for how sure you are."
    )


def classify_jev(description: str, run=subprocess.run) -> dict:
    """Return {"choice", "confidence", "cost_usd", "latency_s", "error"}.
    error is None on success; on any failure choice/confidence are None and
    error holds a short description -- callers decide how to treat a dead
    classification (not this module's call -- it has no fallback opinion)."""
    cmd = [
        "claude", "-p", _prompt(description),
        "--model", MODEL,
        "--tools", "",
        "--json-schema", SCHEMA,
        "--output-format", "stream-json", "--verbose",
    ]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"choice": None, "confidence": None, "cost_usd": 0.0,
                "latency_s": 60.0, "error": "timeout"}

    result_event = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            result_event = ev

    if result_event is None:
        return {"choice": None, "confidence": None, "cost_usd": 0.0,
                "latency_s": 0.0, "error": f"no result event (rc={proc.returncode}): {proc.stderr[:300]}"}

    structured = result_event.get("structured_output")
    if not structured or "choice" not in structured:
        return {"choice": None, "confidence": None,
                "cost_usd": result_event.get("total_cost_usd", 0.0),
                "latency_s": result_event.get("duration_ms", 0) / 1000,
                "error": f"no structured_output in result: {result_event.get('result')}"}

    return {
        "choice": structured["choice"],
        "confidence": structured.get("confidence"),
        "cost_usd": result_event.get("total_cost_usd", 0.0),
        "latency_s": result_event.get("duration_ms", 0) / 1000,
        "error": None,
    }


if __name__ == "__main__":
    desc = " ".join(sys.argv[1:]) or "fix the bug in utils.py"
    print(json.dumps(classify_jev(desc), indent=2))
