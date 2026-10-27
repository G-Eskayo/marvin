#!/usr/bin/env python3
"""
judgment_benchmark.py — benchmark for optimizing paper-dive judgment extraction specifications.

Implements a spec-search loop to find better prompt templates and model parameters for the
judge_extraction task, evaluated against real gold-standard reliability levels from marvin_launcher
(the "teacher" that provides the ground truth).

This is a manual/optional tier tool, not part of the merge-gate pipeline. Results inform
decisions about which judgment specs to ship in logic_auditor.py's defaults.
"""
from __future__ import annotations
import json
import sys
import urllib.request
from pathlib import Path

# Add lib directory to path for model_registry, etc.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
# Add current directory to path for logic_auditor in the same directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

import chromadb
from logic_auditor import (
    judge_extraction,
    extract_structure,
    compute_reliability_signal,
    check_inference_validity,
    EXTRACTION_FIELDS,
)
import model_registry
import model_queue
import marvin_launcher
import metrics_registry

CHROMA_PATH = Path.home() / ".claude" / "chroma"
COLLECTION_NAME = "paper-knowledge"
OLLAMA_URL = "http://localhost:11434/api/chat"

# Model for student (local small model for extraction)
_extraction_model_list = model_registry.resolve_capability("local-extract-small")
EXTRACTION_MODEL = _extraction_model_list[0]

# Model for student judgment
_judgment_model_list = model_registry.resolve_capability("local-judge-medium")
JUDGMENT_MODEL = _judgment_model_list[0]


def ollama_chat(model: str, messages: list[dict], timeout: int = 60, options: dict | None = None) -> str:
    """Call Ollama with optional parameters like temperature."""
    payload_dict = {"model": model, "messages": messages, "stream": False}
    if options:
        payload_dict["options"] = options
    payload = json.dumps(payload_dict).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]


def build_benchmark_samples(
    n: int,
    collection=None,
    teacher_fn=None,
    cache_path: Path | None = None,
) -> list[dict]:
    """Build a benchmark dataset of empirical abstracts with gold-standard reliability levels.

    Args:
        n: number of samples to pull
        collection: ChromaDB collection (defaults to paper-knowledge)
        teacher_fn: function to get gold standard (defaults to marvin_launcher)
        cache_path: where to save/load cache (defaults to ~/.cache/judgment_benchmark.jsonl)

    Returns:
        List of dicts: {id, title, abstract, extraction, gold_level}
    """
    if cache_path is None:
        cache_path = Path.home() / ".cache" / "judgment_benchmark.jsonl"

    if collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection = client.get_or_create_collection(COLLECTION_NAME)

    if teacher_fn is None:
        teacher_fn = lambda abstracts, paper_type: marvin_launcher.launch(
            kind="utility-call",
            request={
                "task": "judge_extraction",
                "abstracts": abstracts,
                "paper_type": paper_type,
            },
        )

    # Try to load from cache first
    cached = {}
    if cache_path.exists():
        for line in cache_path.read_text().strip().split("\n"):
            if line:
                entry = json.loads(line)
                cached[entry["id"]] = entry
        if len(cached) >= n:
            return list(cached.values())[:n]

    # Query collection for empirical papers
    results = collection.query(
        query_texts=["empirical study with real experiments and measurements"],
        n_results=n * 2,  # Fetch more than needed to account for filtering
    )

    samples = []
    ids_list = results.get("ids", [[]])[0] if results.get("ids") else []
    docs_list = results.get("documents", [[]])[0] if results.get("documents") else []

    for doi, abstract in zip(ids_list, docs_list):
        if doi in cached:
            samples.append(cached[doi])
            continue

        if len(samples) >= n:
            break

        # Get title from metadata
        meta_data = collection.get(ids=[doi], include=["metadatas"])
        title = (
            meta_data.get("metadatas", [{}])[0].get("title", doi)
            if meta_data.get("metadatas")
            else doi
        )

        # Extract structure using the standard extraction
        extraction = extract_structure(title, abstract, "empirical")

        # Get gold standard from teacher (call teacher to judge the extraction)
        gold_response = teacher_fn([{"title": title, "abstract": abstract}], "empirical")
        try:
            gold_data = json.loads(gold_response) if isinstance(gold_response, str) else gold_response
            gold_level = gold_data.get("reliability_level", "unknown")
        except (json.JSONDecodeError, TypeError):
            gold_level = "unknown"

        sample = {
            "id": doi,
            "title": title,
            "abstract": abstract,
            "extraction": extraction,
            "gold": gold_level,
        }
        samples.append(sample)

        # Append to cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "a") as f:
            f.write(json.dumps(sample) + "\n")

    return samples


def student_fn(extraction: dict, spec: dict) -> str:
    """Apply a specification (prompt template, model params) to judge an extraction.

    Args:
        extraction: the extracted fields from logic_auditor
        spec: dict with keys like temperature, prompt_template

    Returns:
        The reliability level string from judge_extraction
    """
    paper_type = "empirical"  # benchmark is scoped to empirical for now

    # Get options (like temperature) from spec
    options = {}
    if "temperature" in spec:
        options["temperature"] = spec["temperature"]

    # Define a chat function that uses the specified temperature
    def spec_chat(messages):
        return ollama_chat(JUDGMENT_MODEL, messages, options=options if options else None)

    # Use the prompt_template override if provided
    prompt_template = spec.get("prompt_template")

    # Call judge_extraction with the spec's prompt_template override
    findings = judge_extraction(
        extraction,
        paper_type,
        chat_fn=spec_chat,
        prompt_template=prompt_template,
    )

    # Convert findings list to reliability level
    # (reuse the same logic as logic_auditor.py)
    from logic_auditor import compute_reliability_signal
    signal = compute_reliability_signal(findings, {})
    return signal["level"]


def score_fn(prediction: str, sample: dict) -> bool:
    """Score a prediction: binary match on reliability level category.

    Args:
        prediction: predicted reliability level
        sample: sample with "gold" key containing true level

    Returns:
        True if prediction matches gold standard
    """
    gold = sample.get("gold", "unknown")
    return prediction == gold


def teacher_fn(failing_samples: list[dict], current_spec: dict) -> str:
    """Ask marvin_launcher for suggested spec edits based on failing samples.

    Args:
        failing_samples: samples where student_fn failed
        current_spec: current specification dict

    Returns:
        JSON string with suggested spec edits
    """
    # Prepare the failing cases for the teacher
    cases = [
        {
            "title": s.get("title", s.get("id")),
            "abstract": s.get("abstract", ""),
            "extraction": s.get("extraction", {}),
            "current_prediction": student_fn(s.get("extraction", {}), current_spec),
            "gold_level": s.get("gold", "unknown"),
        }
        for s in failing_samples[:5]  # Limit to top 5 failures
    ]

    # Call marvin_launcher to get a spec suggestion
    response = marvin_launcher.launch(
        kind="utility-call",
        request={
            "task": "suggest_judgment_spec",
            "failing_cases": cases,
            "current_spec": current_spec,
            "num_failures": len(failing_samples),
        },
    )

    try:
        if isinstance(response, str):
            return response
        return json.dumps(response)
    except (TypeError, json.JSONDecodeError):
        return ""


def main():
    """Run the full benchmark: build samples, search for better specs, record metrics."""
    # Build or load cached benchmark samples (small scope for testing: ~8-10 samples)
    print("Building benchmark samples...")
    samples = build_benchmark_samples(n=8)
    print(f"Loaded {len(samples)} benchmark samples")

    # Baseline: run current default spec
    baseline_spec = {
        "temperature": 0.7,
        "prompt_template": None,  # Use defaults
    }

    print("Evaluating baseline spec...")
    from spec_search import evaluate
    baseline_accuracy = evaluate(baseline_spec, samples, student_fn, score_fn)
    print(f"Baseline accuracy: {baseline_accuracy:.2%}")

    # Run spec search
    print("Running spec search (max 4 iterations)...")
    from spec_search import search
    result = search(
        baseline_spec,
        samples,
        student_fn,
        teacher_fn,
        score_fn,
        max_iterations=4,
    )

    final_spec = result["spec"]
    final_accuracy = result["accuracy"]
    iterations = result["iterations"]

    print(f"Final accuracy: {final_accuracy:.2%} (after {iterations} iterations)")
    if final_accuracy > baseline_accuracy:
        print(f"  Improvement: +{(final_accuracy - baseline_accuracy):.2%}")

    # Record metrics
    metrics_registry.record(
        "paper-dive-judgment",
        {
            "baseline_accuracy": baseline_accuracy,
            "final_accuracy": final_accuracy,
            "improvement": final_accuracy - baseline_accuracy,
            "iterations": iterations,
            "num_samples": len(samples),
            "final_spec": final_spec,
        },
    )

    print(f"\nFinal spec:")
    print(json.dumps(final_spec, indent=2))


if __name__ == "__main__":
    main()
