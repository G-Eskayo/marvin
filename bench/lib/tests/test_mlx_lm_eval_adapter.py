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
from mlx_lm_eval_adapter import score_continuation


@pytest.fixture(scope="module")
def model_and_tokenizer():
    from mlx_lm import load
    return load("mlx-community/Llama-3.2-3B-Instruct-4bit")


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
