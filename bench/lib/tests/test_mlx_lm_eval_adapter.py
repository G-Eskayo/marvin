"""Tests for the in-process MLX loglikelihood adapter. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_mlx_lm_eval_adapter.py -v

Uses a real, already-cached small model (Llama-3.2-3B-Instruct-4bit) for every test — this
module's whole purpose is catching real tokenization/logit-slicing bugs, which a mocked model
can't exercise (see tdd/mocking.md: mock at the true external boundary, and a real instance is
preferable to a mock when it's fast and reproducible — a cached 4-bit local model is both).
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import pytest
pytest.importorskip("lm_eval")
pytest.importorskip("mlx_lm")   # Apple silicon only: lm_eval alone is on mac-mini-2012 too, mlx_lm isn't (#932)
from mlx_lm_eval_adapter import score_continuation


MODEL = "mlx-community/Llama-3.2-3B-Instruct-4bit"


def model_is_cached(repo_id: str = MODEL) -> bool:
    """True only when the model is already on this disk. These tests must never download it: on the Mac mini every
    full test run (merge gate, pipeline checks) fetched 1.7 GB back after it was parked in the cold store, pushing free
    disk under the dispatch floor twice (2026-11-11 and 2026-11-12)."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    return isinstance(try_to_load_from_cache(repo_id, "config.json"), str)


@pytest.fixture(scope="module")
def model_and_tokenizer():
    if not model_is_cached():
        pytest.skip(f"{MODEL} isn't on this disk (parked or never fetched); these tests never download it")
    import os
    from mlx_lm import load
    before = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"   # a partial cache still can't trigger a fetch
    try:
        loaded = load(MODEL)
    finally:
        if before is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = before
    return loaded


def test_plausible_continuation_scores_higher_than_implausible(model_and_tokenizer):
    model, tokenizer = model_and_tokenizer
    context = "The capital of France is"

    plausible_logprob, _ = score_continuation(model, tokenizer, context, " Paris")
    implausible_logprob, _ = score_continuation(model, tokenizer, context, " Banana")

    assert plausible_logprob > implausible_logprob


def test_is_greedy_true_for_actual_argmax_continuation_false_otherwise(model_and_tokenizer):
    model, tokenizer = model_and_tokenizer
    context = "2 + 2 ="

    _, greedy_for_likely = score_continuation(model, tokenizer, context, " 4")
    _, greedy_for_unlikely = score_continuation(model, tokenizer, context, " purple")

    assert greedy_for_likely is True
    assert greedy_for_unlikely is False


def test_logit_slicing_matches_independent_step_by_step_computation(model_and_tokenizer):
    """Cross-checks score_continuation's single batched forward pass against a completely
    different computational path: one incremental forward pass per continuation token. If both
    agree, the batched version's position offset (logits[i-1] predicts token[i]) is correct —
    this is exactly the kind of off-by-one a single self-consistent implementation can't catch
    on its own (see tdd/mocking.md: prefer a real, independent check over trusting one code path)."""
    import mlx.core as mx
    import mlx.nn as nn

    model, tokenizer = model_and_tokenizer
    context = "The first three prime numbers are 2, 3, and"
    continuation = " 5"  # two tokens, expands the slicing window beyond a single position

    batched_logprob, _ = score_continuation(model, tokenizer, context, continuation)

    # independent reference: score one continuation token at a time via separate forward passes
    context_tokens = tokenizer.encode(context)
    full_tokens = tokenizer.encode(context + continuation)
    running_tokens = list(context_tokens)
    stepwise_logprob = 0.0
    for i in range(len(context_tokens), len(full_tokens)):
        logits = model(mx.array([running_tokens]))
        logprobs = nn.log_softmax(logits[0, -1], axis=-1)
        stepwise_logprob += logprobs[full_tokens[i]].item()
        running_tokens.append(full_tokens[i])

    assert batched_logprob == pytest.approx(stepwise_logprob, abs=1e-3)


def test_a_model_missing_from_the_cache_counts_as_not_cached(monkeypatch):
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lambda repo, name: None)
    assert model_is_cached() is False
