# 0006 — MLX for the offline-mode on-device model, over llama.cpp/GGUF

## Status

Accepted (2026-07-06)

## Context

Offline mode ([[0003]]) needs a quantized local model running on-device (iPhone only — see
[[0002]]). This is also the first concrete home for `marvin-roadmap.md` section A's parked
"self-hosted track" research item, "Quantization + GPU orchestration: FP8, Int4" — previously
pure research with no self-hosted model to apply it to.

Researched MLX vs llama.cpp/GGUF for 4-bit quantized inference. Findings:

- On Apple Silicon generally, a comparative study (Mac Studio M2 Ultra) found MLX beats
  llama.cpp by 21–87% sustained throughput, attributed to zero-copy unified-memory design and
  lazy-evaluation kernel fusion vs. llama.cpp's Metal-backend memory-transfer overhead.
- No direct MLX-vs-llama.cpp benchmark exists specifically on iPhone hardware. The one
  concrete mobile data point found (iPhone 13 Pro Max, ~5.7 tok/s, 7B model at 3-bit) isn't
  attributed to either framework.
- llama.cpp/GGUF has substantially more real-world iOS field deployment (it underlies most
  existing on-device sideload chat apps today). MLX's iOS path (MLX Swift) is Apple's own
  framework but comparatively less proven in the wild on-device.

The Mac-desktop throughput advantage is a reasoned bet to transfer directionally to iPhone
(same unified-memory architecture), not a measured fact.

## Decision

Use MLX (via MLX Swift) for on-device quantized inference in offline mode, accepting the
higher execution-risk / less-proven-on-iOS trade for the better architectural fit and
likely-better throughput.

## Consequences

- Activates the previously-parked `marvin-roadmap.md` §A "Int4/quantization" research item —
  no longer purely theoretical.
- Real risk: MLX Swift's iOS maturity is unverified in practice; if it proves unreliable or
  underperforms llama.cpp on-device once actually built and measured, llama.cpp/GGUF is the
  fallback (well-trodden path, same model can likely be re-quantized to GGUF Q4).
- Specific model choice (which base model to quantize to 4-bit and run) is still open.
