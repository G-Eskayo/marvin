#!/usr/bin/env python3
"""
mlx_lm_eval_adapter.py — in-process lm-eval loglikelihood scoring for MLX models.

Why this exists: mlx_lm.server's OpenAI-compatible API doesn't support the `echo` parameter
lm-eval's local-completions/local-chat-completions backends need for loglikelihood-based tasks
(e.g. leaderboard_mmlu_pro). This computes log-probabilities directly from the model's own
logits, in-process, with no server and no `echo` requirement.
"""
from __future__ import annotations


def score_continuation(model, tokenizer, context: str, continuation: str) -> tuple[float, bool]:
    """Returns (summed_logprob, is_greedy) for `continuation` given `context`, using the
    model's own next-token logits — position i-1's logits predict the token at position i."""
    import mlx.core as mx
    import mlx.nn as nn

    context_tokens = tokenizer.encode(context)
    full_tokens = tokenizer.encode(context + continuation)
    ctxlen = len(context_tokens)

    logits = model(mx.array([full_tokens]))
    logprobs = nn.log_softmax(logits[0], axis=-1)

    total_logprob = 0.0
    is_greedy = True
    for i in range(ctxlen, len(full_tokens)):
        token_id = full_tokens[i]
        step_logprobs = logprobs[i - 1]
        total_logprob += step_logprobs[token_id].item()
        if mx.argmax(step_logprobs).item() != token_id:
            is_greedy = False

    return total_logprob, is_greedy


def _register():
    from lm_eval.api.model import LM
    from lm_eval.api.registry import register_model

    @register_model("mlx-inprocess")
    class MLXInProcessLM(LM):
        def __init__(self, pretrained: str, **kwargs):
            super().__init__()
            from mlx_lm import load

            self.model, self.tokenizer = load(pretrained)
            self._pretrained = pretrained

        @property
        def tokenizer_name(self) -> str:
            return self._pretrained

        def loglikelihood(self, requests):
            results = []
            for req in requests:
                context, continuation = req.args
                results.append(score_continuation(self.model, self.tokenizer, context, continuation))
            return results

        def apply_chat_template(self, chat_history, add_generation_prompt=True):
            return self.tokenizer.apply_chat_template(
                chat_history, tokenize=False, add_generation_prompt=add_generation_prompt
            )

        def loglikelihood_rolling(self, requests):
            raise NotImplementedError("not needed for MMLU-Pro-style multiple-choice scoring")

        def generate_until(self, requests):
            raise NotImplementedError("not needed for MMLU-Pro-style multiple-choice scoring")

    return MLXInProcessLM


_register()
