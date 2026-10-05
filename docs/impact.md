> Moved out of the README on 2026-10-05 to keep the front page short. Content unchanged apart from this heading.

# Real-world impact

Not "MARVIN exists" — concrete before/after evidence from real sessions. Every claim here links to something you can go verify yourself: a commit, an ADR, a live external contribution.

### Built a citation-graph knowledge base for [`paper-dive`](https://github.com/G-Eskayo/paper-dive), end to end

Since extracted into [its own repo](https://github.com/G-Eskayo/paper-dive) — a complete, independently useful capability that doesn't need MARVIN's other infrastructure, verified standalone before extraction (all 23 tests pass with zero MARVIN dependency).

Went from a one-line roadmap idea ("follow a paper's bibliography recursively") to a working, tested, deployed `/paper-graph` command — via 12 architecture-decision records ([`docs/adr/0007`–`0012`](docs/adr/)), strict TDD (23 tests, zero mocking of the actual scoring logic), and real verification against an unpublished paper, not just a synthetic test fixture.

Along the way, MARVIN caught and fixed three real bugs that would have shipped silently otherwise:
- A version conflict between `mlx-lm` and `transformers` that broke model loading — root-caused and patched, verified empirically rather than guessed at.
- A misdiagnosed "adapter not activated" warning in a widely-used ML library (`adapters`) that looked like a real functional bug — a direct embedding comparison proved the warning was a false positive, saving a costly fallback to a lower-quality model that wasn't actually needed.
- A Semantic Scholar rate-limit gap discovered only by running the real thing against real data, not caught by any unit test — fixed with exponential backoff per the API's own published policy.

### Found and reported a real bug in an external, widely-used open-source library

That misdiagnosed adapter warning turned out to be a genuine, confirmed, previously-unresolved bug in `adapter-hub/adapters` (open since June 2025). MARVIN reproduced it precisely, isolated the root cause via a controlled before/after comparison, and reported it upstream: [adapter-hub/adapters#815](https://github.com/adapter-hub/adapters/issues/815#issuecomment-4909089359) — a real contribution to a project MARVIN doesn't own, verifiable by anyone, not a claim made about MARVIN's own repo.

### Ran a real, evidence-based model comparison instead of picking by vibes

Compared Qwen2.5-3B vs Llama-3.2-3B on `leaderboard_mmlu_pro` (N=200) for MARVIN's own voice-interface offline-mode decision — not by vibes, and not by trusting either vendor's self-reported numbers. `mlx_lm.server`'s OpenAI-compatible API doesn't support the `echo` parameter loglikelihood-based tasks need, so this required building a custom in-process `lm-eval` adapter (`bench/lib/mlx_lm_eval_adapter.py`, `bench/run_mlx_model_comparison.py`) that computes log-probabilities directly from MLX model logits — cross-checked against an independent step-by-step computation before trusting it.

**Qwen2.5-3B: 32.5% accuracy** — matching, almost exactly, HuggingFace's own independently-measured Open LLM Leaderboard number for the same model, a strong signal the custom adapter is measuring correctly. **Llama-3.2-3B: 23.5% accuracy** — a clear, decisive 9-point gap on the same real 200-question test, resolving MARVIN's voice-interface offline-mode model choice with actual evidence instead of a guess.

