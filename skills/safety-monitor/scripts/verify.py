#!/usr/bin/env python3
"""Cheap, calibrated verifier for MARVIN's autonomous loops.

Phase 1 only (see ../DESIGN.md): pure-generation loops — daily_digest,
research_colony. No OTR/drift audit yet; that's otr_log.py / drift_report.py,
not built. See ../REQUIREMENTS.md and ../ARCHITECTURE.md for the design.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from calibrate import get_tau  # noqa: E402

CLAUDE_DIR = Path.home() / ".claude"
QUARANTINE_FILE = CLAUDE_DIR / "quarantine.md"
RUBRIC_DIR = Path(__file__).parent / "rubrics"


def _resolve_claude_bin() -> str:
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
    raise FileNotFoundError(
        "claude CLI not found on PATH or in common install locations "
        "(~/.local/bin, /opt/homebrew/bin, /usr/local/bin)"
    )


def _load_rubric(loop_name: str) -> str:
    rubric_path = RUBRIC_DIR / f"{loop_name}.md"
    if not rubric_path.exists():
        raise FileNotFoundError(
            f"no rubric for loop '{loop_name}' at {rubric_path} — add one "
            f"before calling verify() for this loop (see rubrics/*.md for the pattern)"
        )
    return rubric_path.read_text()


def verify(artifact_text: str, loop_name: str, source_context: str = "") -> float:
    """Return a risk score in [0, 1] for `artifact_text` under `loop_name`'s rubric.

    `source_context`, when given, is the actual data the generator was fed
    (e.g. the roadmap/handoffs/QA-KB text daily_digest.py summarized, or the
    real arXiv/GitHub/HN items research_digest.py synthesized) — this lets
    the judge check claims against real grounding instead of guessing at
    plausibility blind. Found 2026-07-09: without this, every daily_digest
    and research_colony run was being quarantined, consistently, because the
    rubric asked the judge to distinguish "grounded" from "fabricated"
    specifics with no way to actually check either.

    Fails open (returns 0.0, i.e. "pass") on any error — per NFR3, this must
    never block the loop that called it.
    """
    try:
        rubric = _load_rubric(loop_name)
        claude_bin = _resolve_claude_bin()
        context_block = (
            f"\n\n--- SOURCE DATA THE ARTIFACT WAS GENERATED FROM ---\n{source_context}\n"
            "Use this to check claims for real — a specific claim that matches this data is "
            "grounded, not risky, even if you'd otherwise have no way to verify it.\n"
            if source_context else ""
        )
        prompt = (
            f"{rubric}\n{context_block}\n--- ARTIFACT TO SCORE ---\n{artifact_text}\n\n"
            "Respond with ONLY a single number between 0.00 and 1.00 — your "
            "risk score for this artifact under the rubric above. No words, "
            "no explanation, just the number."
        )
        proc = subprocess.run(
            [claude_bin, "-p", prompt, "--model", "haiku", "--output-format", "text"],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            print(f"[safety-monitor] verify() failed open for '{loop_name}': "
                  f"rc={proc.returncode} stderr={proc.stderr[:200]!r}", file=sys.stderr)
            return 0.0
        match = re.search(r"(\d*\.?\d+)", proc.stdout.strip())
        if not match:
            print(f"[safety-monitor] verify() couldn't parse a score for "
                  f"'{loop_name}' from output {proc.stdout[:100]!r} — failing open",
                  file=sys.stderr)
            return 0.0
        return max(0.0, min(1.0, float(match.group(1))))
    except Exception as exc:
        print(f"[safety-monitor] verify() failed open for '{loop_name}': {exc}",
              file=sys.stderr)
        return 0.0


def quarantine(artifact_text: str, score: float, loop_name: str, tau: float,
               reason: str = "") -> None:
    """Append a flagged artifact to ~/.claude/quarantine.md for review."""
    QUARANTINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Full text preserved, not truncated — approve/modify/deny needs to see
    # everything, not a 500-char preview. Quote every line so multi-line
    # content renders as a proper blockquote, not only the first line.
    full_text = artifact_text.strip()
    quoted = "\n".join(f"> {line}" for line in full_text.splitlines())

    block = (
        f"\n---\n## {today} — {loop_name} [SAFETY, score {score:.2f}, tau {tau:.2f}]\n"
        f"{quoted}\n\n"
    )
    if reason:
        block += f"Flagged reason: {reason}\n\n"
    block += "- [ ] approve (ships as-is)\n- [ ] modify: ____________\n- [ ] deny\n"

    if QUARANTINE_FILE.exists():
        existing = QUARANTINE_FILE.read_text()
    else:
        existing = (
            "# Quarantine\n\n"
            "Artifacts flagged by the safety monitor, awaiting review. For "
            "each item: check approve (ships as-is), modify (note the "
            "correction), or deny (discarded, and — if the review workflow "
            "is wired up — recorded as a label for calibration).\n"
        )
    QUARANTINE_FILE.write_text(existing + block)


def pass_or_quarantine(artifact_text: str, loop_name: str, source_context: str = "") -> bool:
    """The one-line integration point for existing loops.

    `source_context`: the real data the artifact was generated from, if the
    caller has it — pass it through so the judge can check claims for real.
    See verify()'s docstring for why this matters.

    Returns True  -> artifact is safe; caller should write it out normally.
    Returns False -> artifact was quarantined; caller should NOT write it out.
    """
    score = verify(artifact_text, loop_name, source_context)
    tau = get_tau(loop_name)
    if score < tau:
        return True
    quarantine(artifact_text, score, loop_name, tau)
    return False


if __name__ == "__main__":
    # Manual smoke test: echo "some artifact text" | python3 verify.py <loop_name>
    if len(sys.argv) != 2:
        print("usage: verify.py <loop_name>  (reads artifact text from stdin)", file=sys.stderr)
        sys.exit(1)
    text = sys.stdin.read()
    loop = sys.argv[1]
    s = verify(text, loop)
    t = get_tau(loop)
    print(f"score={s:.2f} tau={t:.2f} -> {'QUARANTINE' if s >= t else 'pass'}")
