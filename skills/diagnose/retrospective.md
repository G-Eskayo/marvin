# Diagnose — Retrospective

## 2026-07-07 — MLX on-device model benchmark (Qwen2.5-3B vs Llama-3.2-3B)
**I:** Learned to distrust "OpenAI-compatible" as a binary label. Before wiring an eval harness (or any client) to a local model server over its OpenAI-compatible HTTP API, check which specific params it implements — compatibility is usually partial, not full.
**F:** Built a benchmark around `mlx_lm.server` + `lm-eval`'s `local-completions` backend assuming standard OpenAI-completions compatibility. `leaderboard_mmlu_pro` needs `echo` (echoed prompt log-probs) to score log-likelihood; `mlx_lm.server` doesn't implement `echo` at all, and no pre-built MLX adapter for `lm-eval` exists either. The whole server-based approach was a dead end — confirmed only after building it, not before. Fix was to drop the HTTP server entirely and write a small in-process `lm-eval` `LM` subclass wrapping `mlx-lm` directly.
