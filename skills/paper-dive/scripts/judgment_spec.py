#!/usr/bin/env python3
"""judgment_spec.py — capture and score judgment specs for paper-dive logic auditor.

DEFAULT_SPEC holds today's real prompts/models/engine-settings from logic_auditor.
score_spec() compares a student run against gold labels:
- Type/inference labels: exact match only
- Findings: zero-tool Claude judge for equivalence
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logic_auditor  # noqa: E402


# Default spec captures current state from logic_auditor.py
DEFAULT_SPEC = {
    "classify_model": logic_auditor.CLASSIFY_MODEL,
    "extraction_model": logic_auditor.EXTRACTION_MODEL,
    "judgment_model": logic_auditor.JUDGMENT_MODEL,
    "inference_model": logic_auditor.INFERENCE_MODEL,
    "classify_prompt": logic_auditor.CLASSIFY_PROMPT,
    "extraction_prompts": logic_auditor._EXTRACTION_PROMPTS,
    "judgment_prompts": logic_auditor._JUDGMENT_PROMPTS,
    "inference_prompt": logic_auditor.INFERENCE_PROMPT,
}


def _judge_findings_equivalence(gold_findings: list[str], student_findings: list[str]) -> dict:
    """Use zero-tool Claude judge to assess whether student findings are equivalent to gold.
    Returns {"equivalent": bool, "rationale": str}."""
    bench_dir = Path(__file__).resolve().parents[2] / "bench"
    clean_profile = bench_dir / "profiles" / "clean"

    judge_env = dict(os.environ)
    if clean_profile.exists():
        judge_env["CLAUDE_CONFIG_DIR"] = str(clean_profile)
    for k in list(judge_env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_EFFORT"):
            judge_env.pop(k, None)

    prompt = f"""You are grading whether a logic audit tool produced equivalent findings to gold labels.

GOLD FINDINGS:
{json.dumps(gold_findings, indent=2)}

STUDENT FINDINGS:
{json.dumps(student_findings, indent=2)}

Judge whether the student findings capture the same logical issues and validity concerns as the gold, even if phrased differently. Order does not matter. Missing findings are failures, but finding the same issues with different wording is success.

Reply with exactly:
EQUIVALENT: yes
RATIONALE: one sentence

or

EQUIVALENT: no
RATIONALE: one sentence explaining the specific gap"""

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text", "--tools", ""],
            capture_output=True, text=True, timeout=90, env=judge_env
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude judge failed with code {proc.returncode}: {proc.stderr}")
        text = proc.stdout.strip()
    except Exception as exc:
        raise RuntimeError(f"judge call failed: {exc}") from exc

    equiv_line = next((l for l in text.splitlines() if "EQUIVALENT" in l.upper()), "")
    is_equivalent = "yes" in equiv_line.lower()
    rationale_m = __import__("re").search(r"RATIONALE\s*:\s*(.+)", text, __import__("re").IGNORECASE)
    rationale = rationale_m.group(1).strip() if rationale_m else text[:300]

    return {"equivalent": is_equivalent, "rationale": rationale}


def score_spec(spec: dict, benchmark: dict[str, dict]) -> dict:
    """Score a student spec against gold benchmark.

    Args:
        spec: Student spec dict (like DEFAULT_SPEC)
        benchmark: Gold benchmark dict (output of judgment_benchmark.py)

    Returns:
        {
            "accuracy": float (0-1),
            "type_accuracy": float,
            "inference_accuracy": float,
            "findings_accuracy": float,
            "details": {slug: {"type_match": bool, "inference_match": bool, "findings_equivalent": {...}}},
        }
    """

    details = {}
    type_matches = 0
    inference_matches = 0
    findings_equiv_count = 0

    for slug, gold in benchmark.items():
        title = gold["title"]
        abstract = gold.get("abstract", "")

        # Create a student chat function that uses the spec's models via ollama_chat
        def make_student_chat(spec_dict):
            def student_chat(messages):
                from ollama_chat import ollama_chat
                # Extract the prompt to infer which model to use based on the prompt content
                prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
                # Heuristic: guess model from prompt keywords or use extraction by default
                if "classify" in prompt.lower() or "kind of argument" in prompt.lower():
                    model = spec_dict.get("classify_model")
                elif "deductive" in prompt.lower() or "inductive" in prompt.lower() or "inferential" in prompt.lower():
                    model = spec_dict.get("inference_model")
                elif "MEASURES:" in prompt or "CONSTRUCT_VALIDITY" in prompt or "benchmark" in prompt.lower():
                    # For benchmark-type judgments, check override
                    if spec_dict.get("judgment_model"):
                        model = spec_dict.get("judgment_model")
                    else:
                        model = spec_dict.get("inference_model")
                elif "CLAIM:" in prompt or "TAXONOMY:" in prompt or "STRUCTURAL_CLAIMS:" in prompt:
                    # Type-adaptive judgment prompts
                    model = spec_dict.get("judgment_model")
                else:
                    # Default to extraction model for other structural prompts
                    model = spec_dict.get("extraction_model")

                if not model:
                    raise ValueError(f"No model found in spec for prompt: {prompt[:100]}")
                return ollama_chat(model, messages)
            return student_chat

        student_chat = make_student_chat(spec)

        # Run student spec on this paper
        try:
            student_type = logic_auditor.classify_paper_type(
                title, abstract, chat_fn=student_chat
            )
            student_inference = logic_auditor.check_inference_validity(
                title, abstract, chat_fn=student_chat
            )
            # For findings, we need the extraction first
            student_extraction = logic_auditor.extract_structure(
                title, abstract, student_type, chat_fn=student_chat
            )
            student_findings = logic_auditor.judge_extraction(
                student_extraction, student_type, chat_fn=student_chat
            )
        except Exception:
            # If student run fails, mark all as mismatches
            student_type = None
            student_inference = None
            student_findings = []

        # Score type match (exact)
        type_match = student_type == gold.get("paper_type")
        type_matches += 1 if type_match else 0

        # Score inference match (exact)
        inference_match = (
            student_inference == gold.get("inference")
            if student_inference is not None
            else False
        )
        inference_matches += 1 if inference_match else 0

        # Score findings equivalence (zero-tool judge)
        findings_equiv = _judge_findings_equivalence(
            gold.get("findings", []),
            student_findings if isinstance(student_findings, list) else [],
        )
        if findings_equiv.get("equivalent"):
            findings_equiv_count += 1

        details[slug] = {
            "type_match": type_match,
            "inference_match": inference_match,
            "findings_equivalent": findings_equiv,
        }

    total = len(benchmark)
    return {
        "accuracy": (type_matches + inference_matches + findings_equiv_count) / (3 * total) if total > 0 else 0.0,
        "type_accuracy": type_matches / total if total > 0 else 0.0,
        "inference_accuracy": inference_matches / total if total > 0 else 0.0,
        "findings_accuracy": findings_equiv_count / total if total > 0 else 0.0,
        "details": details,
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Judgment spec capture and scoring.")
    ap.add_argument("--show-spec", action="store_true", help="Print DEFAULT_SPEC and exit")
    ap.add_argument("--benchmark", help="Path to benchmark JSON (from judgment_benchmark.py)")
    args = ap.parse_args()

    if args.show_spec:
        # Print a summary of DEFAULT_SPEC
        print("DEFAULT_SPEC models:")
        print(f"  classify_model: {DEFAULT_SPEC['classify_model']}")
        print(f"  extraction_model: {DEFAULT_SPEC['extraction_model']}")
        print(f"  judgment_model: {DEFAULT_SPEC['judgment_model']}")
        print(f"  inference_model: {DEFAULT_SPEC['inference_model']}")
        sys.exit(0)

    if args.benchmark:
        benchmark_path = Path(args.benchmark)
        if not benchmark_path.exists():
            sys.exit(f"Benchmark file not found: {args.benchmark}")

        benchmark = json.loads(benchmark_path.read_text())
        print(f"Scoring spec against {len(benchmark)} benchmarks...")
        result = score_spec(DEFAULT_SPEC, benchmark)
        print(json.dumps(result, indent=2))
