# Local models review: what MARVIN can run on its own machines (2026-11-11)

Feeds marvin#46 (model-adaptive harness), marvin#594 (the $20 plan plus local models, M3 on 2026-11-27), marvin#563 (finish the local model investigation) and marvin#674 (local coding-assistant spike). Sources are numbered [S1]… and listed at the end with URLs and dates. Confidence tiers come from `skills/research/epistemic-framework.md`: **Established**, **Contested**, **Speculative**, **Unknown**.

## Bottom line

1. **One local generalist on the Mini: Qwen3.5-9B** (Apache-2.0, Feb 2026, 6.6 GB). It covers the front desk, classify, summarize and ground-truth judging. Fall back to **Qwen3.5-4B** (3.3 GB) if measurement 1 says it's too slow. It replaces qwen2.5:3b, matching #563's "one model" direction.
2. **The front desk works as a brief-filler, not a decider.** Code decides when to escalate. The model fills a JSON-schema brief.
3. **Coding stays on Claude**: about 47–51% SWE-bench Verified locally against 77.2% for Sonnet 4.5. A local small-ticket lane is worth the #674 spike, with a real test gate, and no more.
4. **Embeddings and voice stay as they are** (nomic-embed-text, FluidAudio) until a swap is measured.
5. **Tune the harness before the weights** (OpenJarvis [S28]). Then QLoRA on a 4B model, which fits on 16 GB.

## The machines, measured

| Machine | Facts (checked 2026-11-11) | What it means |
|---|---|---|
| Mac mini M4, 16 GB | macOS 26.5.1, Ollama 0.40.13, **15 GB free disk**, models: qwen2.5:3b, nomic-embed-text | It can hold one roughly 7 GB model plus embeddings. No `fm` CLI (that needs macOS 27). |
| MacBook Pro M1, 16 GB | macOS 27.0.1, `/usr/bin/fm` present (licence not yet accepted), work network blocks huggingface.co | Use the Mini as the download relay (memory: exo attempt). The laptop is a client of the Mini, a fine-tuning box when plugged in, and the voice host. |
| mac-mini-2012 | i7-3615QM, AVX without AVX2, 16 GB, DDR3-1600 = **25.6 GB/s** peak [S30], no Ollama installed | CPU batch work only. |

**Speed, measured by others.** llama.cpp's Apple Silicon table gives Llama-7B Q4_0 (~3.6 GB) at **14.2 tok/s on the M1 and 24.1 tok/s on the M4** for generation, and about 118 and 221 tok/s for prompt processing [S19]. Generation is bandwidth-bound, so the same table lets us estimate (an inference, not a measurement):
- Qwen3.5-9B Q4: about 8–9 tok/s on the M1 and 14–16 tok/s on the M4.
- Qwen3.5-4B Q4: about 15–18 tok/s on the M1 and 26–30 tok/s on the M4.

Community reports on a 16 GB M4 are 50 tok/s for Mellum2.1 (2.5B active parameters) and 26.6 tok/s for Nemotron 3.5 Bolt E4B. These come from single runs [S21]. Ollama added an MLX backend in March 2026 and claimed about 2× gains, but those were measured on M5-class machines [S20]. **Contested** for the M1 and M4.

**Memory.** macOS lets the GPU wire roughly 65–75% of RAM by default, about 10.5–12 GB on 16 GB. This comes from community documentation, not Apple [S35]. gpt-oss-20b needs about 13–14 GB [S10], so it doesn't fit next to normal work. Qwen3.6-35B-A3B (20 GB MLX 4-bit) [S8], Qwen3.8-27B (27.8B params) and Devstral Small 2 (24B) [S9] are out for the same reason.

## Candidates that fit 16 GB with headroom

Vendor numbers come from each model card. The third-party columns are other vendors re-measuring the same model in their own harness. That second number is the one to trust more.

| Model (released) | Licence | Ollama size | Vendor-published | Re-measured by others |
|---|---|---|---|---|
| **Qwen3.5-9B** (2026-02-27) [S1] | Apache-2.0 | 6.6 GB | IFEval 91.5, IFBench 64.5, BFCL-V4 66.1, TAU2 79.1, MMLU-Pro 82.5 | JetBrains: BFCL-V4 58.5, IFEval 92.4, SWE-V 50.0 [S3]. Liquid: BFCL-V4 62.8, τ³ 67.1, SWE-V 51.2 (OpenCode) [S4] |
| **Qwen3.5-4B** (2026-02-27) [S2] | Apache-2.0 | 3.3 GB | IFEval 89.8, BFCL-V4 50.3, TAU2 79.9, MMLU-Pro 79.1 | NVIDIA: TAU2 **75.1 at BF16 → 61.7 at Q4_K_M**, BFCL-v3 71.0 → 70.6 [S5]. Liquid: SWE-V 41.2 [S4] |
| Granite 4.2 8B (2026-08-07) [S6] | Apache-2.0 | 5.3 GB | SWE-V 47.7, BFCL-v4 52.4, IFBench 79.3, MMLU-Pro 74.0, RULER-128K 71.4 | none found |
| Mellum2.1-12B-A2.5B (2026-09-20) [S3] | Apache-2.0 | 7.0–8.1 GB GGUF | SWE-V 47.0, BFCL-v4 62.3, IFEval 90.6; a coding-focused MoE | none found |
| Gemma 4 12B (2026-05-23) [S7] | Apache-2.0 | 6.6 GB | MMLU-Pro 77.2, Tau2 69.0, LiveCodeBench 72.0 | none found |
| Gemma 4 E4B (2026-03) [S7] | Apache-2.0 | ~4.5 GB | MMLU-Pro 69.4, Tau2 42.2 | SWE-V 23.0 (JetBrains), 0.5 (Liquid). Weak agent |
| Nemotron 3.5 Bolt E4B 4GB (2026-10-05) [S5] | OpenMDW-1.1 (card: "ready for commercial use") | ~4 GB | BFCL-v3 67.3, IFBench 64.0 (Q4) | none found |
| LFM3-1.7B (2026-10-23) [S4] | **LFM Open License: commercial use only below $10M annual revenue** | 1.1–1.7 GB | BFCL-V4 71.4, IFEval 96.7, SWE-V 43.4 | none found. Single source |
| Apple on-device model, about 3B [S17] | Apple OS terms | 0 extra disk | 4,096-token context shared by prompt, tools and output [S15]. New model in OS 27 [S14] | n/a |

**Finding:** Qwen3.5-9B is the strongest general model that fits. Three vendors (Qwen, JetBrains, Liquid) agree that IFEval is about 92. They disagree on BFCL-V4: 58.5, 62.8 and 66.1. **Established** that it leads its size class on instruction-following. **Contested** on the exact tool-use margin.

**Finding:** Q4 quantization can cost a lot on multi-turn agent tasks. NVIDIA measured a 13.4-point TAU2 drop for Qwen3.5-4B at Q4_K_M, while BFCL barely moved [S5]. That is one source, so **Speculative**, but it decides whether a 4-bit front desk is good enough. Measure it ourselves.

Two models are out:
- **LFM3** is not NC, but it stops being licensed above a $10M revenue threshold [S4]. Keep it out of anything shipped.
- **Voxtral-4B-TTS** is CC-BY-NC-4.0, so it is out.

## Job by job

### 1. Front desk chat (Gil's new idea)

**What it needs:** multi-turn talk, following a policy, calling a few read-only tools (memory search, ticket lookup, grep) and producing a structured brief. τ²-bench (a conversational agent with tools and a simulated user) is the closest public proxy. Qwen3.5-4B and 9B report about 79 there [S1], better than models ten times their size from 2025.

**What makes it feasible:**
- Ollama constrains output to a JSON schema through its `format` parameter [S22]. That makes the brief's shape reliable even when the content isn't.
- The brief can stay small: task, context pointers (paths, ticket numbers, memory slugs), acceptance check, open questions and the suggested tier. That keeps paid-model input short, which is the token lever #594 asks for.
- Qwen3.5 runs in thinking mode by default [S1]. Turn it off (`enable_thinking: false`) for the front desk, or latency doubles.

**What works against it (the steelman):**
- On the M4, a 9B model writes a 300-token reply in about 20 s, plus prefill. That is slow for chat.
- A bad brief costs more than no brief, because the paid model re-asks or builds the wrong thing.
- OpenJarvis found that putting a 9B model into a harness built for Claude cost 25–39 points. A spec tuned to the model won back 56–77% of that [S28]. That is exactly marvin#46's question: the front desk's harness must be written for the local model, not copied from Claude's.

**Apple Foundation Models can't be the front desk:**
- The 4,096-token session budget includes tool definitions [S15].
- One hands-on report says `fm serve` ignores tool calling [S15].
- Apple's model is fine for one-shot tagging on the laptop, at zero disk cost.

**Verdict:** feasible for gathering context and writing the brief. Code decides when to escalate, using rule-based triggers plus the embedding classifier's confidence. The model's own judgment does not decide. **Speculative** until measurement 4.

### 2. Coding/builder and code review

- **Published numbers:** 47–51% SWE-bench Verified for Qwen3.5-9B, Granite 4.2 8B and Mellum2.1 in third-party harnesses [S3][S4][S6], against 77.2% for Claude Sonnet 4.5 [S31].
- **Past runs:** MARVIN's own July runs had local 7b/14b lose both select_model tasks (RESULTS.md Run 15). #674 was parked because its gate was a keyword check.
- **Suitable local work:** docs fixes, test scaffolds, a first-pass review for obvious defects, and commit and PR text. All of it is checked by tests and the merge gate (#594's "quality from the system").
- **Mellum2.1** is the speed alternative for this lane: about 3× faster on the M4 [S21], with SWE-bench Verified within 3 points of Qwen3.5-9B in JetBrains' own harness [S3].
- **Established:** the gap to Claude on multi-file agentic coding is about 25 points.

### 3. Classify, triage, route, summarize, judge

- **Route:** keep the embedding classifier as stage one. It needs no model call and validated at 87.5% (ADR 0023). Call the LLM only when its confidence is low.
- **Classify and extract:** Qwen3.5 in non-thinking mode with a JSON schema. Fine-tuned small models beat zero-shot frontier models on narrow classification once there is moderate labelled data [S25][S24]. **Established.**
- **Summarize and digest:** local overnight batch. Escalate to Haiku when the result is user-facing.
- **Judge:** local only for judging against ground truth (does the content match the expected answer). Run 15 showed that even Claude judges flip-flop without ground truth, so open-ended judging stays on Claude.

### 4. Embeddings and reranking

| Model | Size | MTEB eng v2 | Licence |
|---|---|---|---|
| nomic-embed-text v1.5 (2024-02) [S11] | 137M, 0.27 GB | 62.28 (**MTEB v1**, not comparable) | Apache-2.0 |
| Qwen3-Embedding-0.6B (2025-06) [S11] | 0.6B | 70.70; 32K context; instruction-aware | Apache-2.0 |
| EmbeddingGemma 2 (2026-09-14) [S11] | 740M (270M text) | 68.46; code v1 78.68; 8K context; also embeds images and audio | Apache-2.0 |
| bitnet-embedding-0.6b (2026-07-15) [S11] | 1.58-bit, 0.6B | 67.49 (v2 mean) | MIT |

A swap means re-embedding every stored vector and re-calibrating the router's thresholds. Do it only if `bench/retrieval_eval.py` and the route fixture improve. A reranker (Qwen3-Reranker-0.6B, Apache) is only worth adding if top-5 misses show up in that eval. **Unknown** for MARVIN's data.

### 5. Speech for marvin-voice

**Keep FluidAudio (Apache-2.0, CoreML on the Neural Engine).**
- **Measured:** 6 s of speech transcribed in 0.06 s (memory: marvin-voice).
- **Its model menu:** Parakeet TDT v3 and Parakeet Ultra (25 European languages), Nemotron streaming ASR, Cohere Transcribe, and TTS through Kokoro ANE, PocketTTS (Kyutai small models) and Supertonic-3 (31 languages) [S12].
- **Alternatives:** Qwen3-ASR-1.7B (Apache, 30 languages) [S13].
- **Hebrew:** no open model checked here lists Hebrew as ready. Nemotron 3.5 ASR calls it "adaptation-ready" only [S13].

### 6. Phones and the 2012 box

- **Phones:** ADR 0045 stands.
  - OS 27 shipped a new on-device model and a `LanguageModel` protocol, so MLX or other models can sit behind the same API [S14].
  - Apps in the Small Business Program with under 2M downloads get Apple's Private Cloud Compute model at no API cost [S16]. That is relevant to Seal Speak.
- **2012 box:** at 25.6 GB/s, a 2 GB Q4 model can't beat about 12 tok/s even in theory. Expect a few tok/s. Use it for overnight embedding re-index and non-urgent digests. Build llama.cpp with AVX2 off, since Ollama's AVX-only support is unconfirmed. **Unknown** until measured.
- **exo pooling:** works with two nodes and a 1B model (memory). It is untested at larger sizes and uses an archived fork. Not for production.

## Fine-tuning our local agents

**What runs here:**
- mlx-lm LoRA, plus QLoRA when the base model is already 4-bit. Batch size, the number of layers and gradient checkpointing all cut memory [S23].
- QLoRA on a 4B model fits on 16 GB. A 7–9B model is tight: use batch 1, 4–8 layers and checkpointing. Community reports put a 7B QLoRA at 5–8 GB [S23 and the guides it cites].
- mlx-lm's docs report about 250 tok/s for a 7B model on an M1 Max with 32 GB [S23].
- **Estimate:** 1,000 examples of about 1k tokens over 3 epochs is about 3M tokens, roughly 3–4 h on the M1. Electricity is negligible.
- Run it on the laptop, plugged in under `caffeinate`, so the Mini keeps serving.

**What doesn't run here:**
- Full fine-tuning above about 1B parameters, and RL fine-tuning (GRPO) at useful scale. Both need an NVIDIA GPU or rented time.
- Official Unsloth is CUDA-only. `mlx-tune` copies its API but is a community project, not Unsloth [S32].
- Apple's Foundation Models adapter toolkit needs a 32 GB Mac or a Linux GPU, and every OS model update needs a new toolkit and a retrained adapter [S18].
- **Unknown:** mlx-lm's LoRA support for Qwen3.5's hybrid (Gated DeltaNet) layers. Test it before planning around it.

**Data MARVIN already has:**

| Data | Use | Caveat |
|---|---|---|
| Review verdicts, send-backs, gate pass/fail, merged-or-not | Labels for the judge and router: what passed on which tier | Cleanest data: our own outcomes |
| Ticket → PR pairs | Learn the shape of the brief: what a good task, context and acceptance check looks like | Small n (hundreds) |
| The ~177k embedding/routing calls | Inputs only. Valuable once joined to outcomes (which tier actually succeeded) | Without outcomes, training on them only teaches the router its own output |
| Pipeline transcripts (Claude output) | Distillation | **Anthropic's Consumer Terms forbid using the Services "to develop or train any artificial intelligence or machine learning algorithms or models" that compete [S29].** Whether a private MARVIN agent "competes" is a question for Gil, not an agent |

**Realistic gains (literature):**

| Source | Result | Caveat |
|---|---|---|
| LoRA Land [S24] | 4-bit LoRA beat the base models by 34 points on average, and GPT-4 by 10 | Narrow tasks only. GPT-4 still won on coding and MMLU |
| TinyAgent [S26] | Tuned 1.1B and 7B models beat GPT-4-Turbo at calling one app's functions | Used about 80k synthetic examples (a secondary count) |
| LoRA Learns Less and Forgets Less [S27] | LoRA trails full fine-tuning most on code | Not a coding fix |

**Conclusion:** tune for routing, triage labels and the brief's format. Don't tune for coding. **Established** for narrow classification. **Speculative** for the front desk.

## (a) Recommended layered configuration

| Job | Machine | Model | Runtime | Fallback / escalation |
|---|---|---|---|---|
| Front desk chat + brief | Mini (laptop as client over Tailscale) | Qwen3.5-9B Q4, non-thinking, JSON-schema brief | Ollama | Qwen3.5-4B if too slow. Code-side rules escalate to Sonnet (the $20 plan) with the brief |
| Route | Mini | nomic-embed-text classifier | Ollama embeddings | Low confidence → Qwen3.5-9B → Claude orchestrator |
| Classify, triage, extract | Mini | Qwen3.5-9B | Ollama | Haiku when gates fail. Later a QLoRA adapter |
| Summarize, digest | Mini overnight (2012 box if measured OK) | Qwen3.5-9B (llama.cpp CPU on the box) | Ollama / llama.cpp | Haiku when user-facing |
| Judge with ground truth | Mini | Qwen3.5-9B | Ollama | Open-ended judging → Sonnet |
| Coding, build | Claude | Sonnet (Opus for hard design) | Claude Code | Local small-ticket lane only if #674 passes: Qwen3.5-9B or Mellum2.1 in opencode |
| Code review | Claude, plus local pre-pass | Qwen3.5-9B first pass | Ollama | Claude always gives the final verdict |
| Embeddings | Mini | nomic-embed-text (candidates: Qwen3-Embedding-0.6B, EmbeddingGemma 2) | Ollama | 2012 box for batch re-index |
| STT / TTS | Laptop (audio rule), Mini | Parakeet v3/Ultra; Kokoro ANE / PocketTTS | FluidAudio (CoreML/ANE) | Qwen3-ASR-1.7B for other languages |
| One-shot tagging, laptop | Laptop | Apple on-device model | `fm` CLI / FoundationModels | Mini's Qwen |
| Phone offline | iPhone, iPad | Apple Foundation Models | FoundationModels | MLX fallback (ADR 0045) |
| Fine-tuning | Laptop, plugged in | QLoRA on Qwen3.5-4B | mlx-lm | Rented NVIDIA GPU for anything bigger |

Free disk on the Mini first: delete qwen2.5:3b (1.9 GB) after the swap, and check `config/models.json` (it still lists 14b/7b, see #563).

## (b) Measurements to run, smallest first

1. **Fit and speed on the Mini (about 15 min, no API cost).**
   - Pull qwen3.5:9b and qwen3.5:4b, plus their `-mlx` tags [S33].
   - Record generation tok/s, prefill time for a 4K prompt, time to first token when warm and cold, and memory pressure under the Mini's normal load.
   - Pass: at least 12 tok/s and no swapping.
2. **Embedding A/B (about 1 h, no API cost).** Run `bench/retrieval_eval.py` (30 questions) and the route fixture with nomic, Qwen3-Embedding-0.6B and EmbeddingGemma 2. Swap only on a clear win in top-5 hits.
3. **Finish #563 with `select_model.py`.**
   - Candidates: qwen3.5:4b, qwen3.5:9b and granite4.2:8b, at Q4.
   - Tasks: classify, extract, digest and ground-truth judge, N≥3, cheapest first.
   - This also tests the Q4 tool-use drop [S5] on our own tasks.
4. **Front-desk replay.**
   - Take 20 real past requests from Gil, with outcomes known. Have the local model produce the JSON brief, then hand it to Sonnet.
   - Score: did the work pass without a clarifying turn, paid tokens against the direct path, and Gil's rating on 5 of them.
   - Pass: the same pass rate with fewer paid tokens.
5. **#674 with a real gate.** Five merged small tickets, with Qwen3.5-9B and then Mellum2.1 in opencode. The ticket's own tests must pass in the worktree (this fixes the keyword-gate must-fix). Measure energy with powermetrics (with `stop_sampling` in `finally`).

Then, only if measurement 3 shows a gap: a QLoRA pilot on routing and triage labels.

## (c) Open risks

- **Benchmark harness spread:** Qwen3.5-9B's SWE-bench Verified ranges from 50.0 to 51.2 across vendors, and Gemma 4 E4B's ranges from 0.5 to 23.0 [S3][S4]. Only our own runs count.
- **Quantization loss on agent tasks** [S5]. It is single-source but large.
- **The Mini has 16 GB and 15 GB of free disk** and is the host for everything else. A resident 6.6 GB model competes with builds, the dashboard and Claude sessions.
- **The front desk can cost more than it saves** if its briefs make the paid model re-ask. The channel (dashboard chat, voice, terminal) is undecided.
- **Licence traps:** LFM's $10M threshold, NC TTS models, NVIDIA OpenMDW (the card says commercial use is fine, but read it before shipping) and Anthropic's training clause [S29].
- **Apple's model changes with every OS update** [S14]. Prompts and adapters need re-testing each time.
- **Churn and noise:** several 2026 "best model" sites list hardware and models I couldn't verify, such as a "Mac mini M6" [S21]. Every pick here was checked against its Hugging Face card. Re-check quarterly through the research colony, and pick by measurement, not by leaderboard.
- **Ollama's Mac backend has changed twice in 2026** [S20]. Speed numbers go stale.

## Sources (accessed 2026-11-11 unless noted)

- [S1] Qwen3.5-9B model card, 2026-02-27. https://huggingface.co/Qwen/Qwen3.5-9B
- [S2] Qwen3.5-4B model card, 2026-02-27. https://huggingface.co/Qwen/Qwen3.5-4B
- [S3] JetBrains Mellum2.1-12B-A2.5B-Thinking card, 2026-09-20 (Pi agent harness). https://huggingface.co/JetBrains/Mellum2.1-12B-A2.5B-Thinking
- [S4] LiquidAI LFM3-1.7B card and LICENSE, 2026-10-23. https://huggingface.co/LiquidAI/LFM3-1.7B
- [S5] NVIDIA Nemotron-3.5-Bolt-E4B-4GB card, 2026-10-05. https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB
- [S6] IBM granite-4.2-8b card, 2026-08-07. https://huggingface.co/ibm-granite/granite-4.2-8b
- [S7] Gemma 4 12B-it card, 2026-05-23. https://huggingface.co/google/gemma-4-12B-it ; Google, "Gemma 4", 2026-04-02. https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/
- [S8] Qwen3.6-35B-A3B card, 2026-04-15. https://huggingface.co/Qwen/Qwen3.6-35B-A3B ; Qwen3.8-27B card, 2026-08-05. https://huggingface.co/Qwen/Qwen3.8-27B
- [S9] Devstral-Small-2-24B card, 2025-11-28. https://huggingface.co/mistralai/Devstral-Small-2-24B-Instruct-2512
- [S10] OpenAI gpt-oss model card, arXiv 2508.10925, 2025-08-05. https://arxiv.org/abs/2508.10925
- [S11] Embedding cards: Qwen3-Embedding-0.6B, 2025-06-03, https://huggingface.co/Qwen/Qwen3-Embedding-0.6B ; EmbeddingGemma 2, 2026-09-14, https://huggingface.co/google/embeddinggemma-2 ; nomic-embed-text-v1.5, 2024-02-10, https://huggingface.co/nomic-ai/nomic-embed-text-v1.5 ; bitnet-embedding-0.6b, 2026-07-15, https://huggingface.co/microsoft/bitnet-embedding-0.6b
- [S12] FluidAudio Documentation/Models.md. https://github.com/FluidInference/FluidAudio/blob/main/Documentation/Models.md
- [S13] Qwen3-ASR-0.6B/1.7B card, 2026-01-28, https://huggingface.co/Qwen/Qwen3-ASR-1.7B ; nemotron-3.5-asr-streaming-0.6b card, 2026-05-15, https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b ; Voxtral-4B-TTS-2603 (cc-by-nc-4.0), https://huggingface.co/mistralai/Voxtral-4B-TTS-2603
- [S14] Apple, "Foundation Models updates" (Feb, Mar, Jun 2026). https://developer.apple.com/documentation/updates/foundationmodels
- [S15] ModelFit, "macOS 27 fm CLI", about 2026-09-28 (quotes Apple's 4,096-token limit; secondary source). https://modelfit.io/blog/macos-27-fm-cli-local-model-terminal/
- [S16] Apple, WWDC26 Apple Intelligence guide, June 2026. https://developer.apple.com/wwdc26/guides/apple-intelligence/
- [S17] Apple Intelligence Foundation Language Models Tech Report 2025, arXiv 2507.13575. https://arxiv.org/abs/2507.13575
- [S18] Apple, Foundation Models adapter training. https://developer.apple.com/apple-intelligence/foundation-models-adapter/ (the 32 GB requirement is from secondary sources, e.g. https://charleswiltgen.github.io/Axiom/reference/foundation-models-adapters-ref)
- [S19] llama.cpp, "Performance of llama.cpp on Apple Silicon", discussion #4167 (running since 2023-11). https://github.com/ggml-org/llama.cpp/discussions/4167
- [S20] Ollama, "Ollama is now powered by MLX on Apple Silicon in preview", 2026-03-30. https://ollama.com/blog/mlx
- [S21] LLMCheck, "Best Local LLM for a 16GB Mac", updated 2026-10-24 (community and estimated speeds; low tier). https://llmcheck.net/blog/best-local-llm-16gb-mac/
- [S22] Ollama, "Structured outputs", 2024-12-06. https://ollama.com/blog/structured-outputs
- [S23] mlx-lm LORA.md. https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md ; community 16 GB report: https://towardsdatascience.com/local-llm-fine-tuning-on-mac-m1-16gb-f59f4f598be7
- [S24] Zhao et al., "LoRA Land", arXiv 2405.00732, 2024-04-29. https://arxiv.org/abs/2405.00732
- [S25] Bucher & Martini, "Fine-Tuned 'Small' LLMs (Still) Significantly Outperform Zero-Shot…", arXiv 2406.08660, 2024-06-12. https://arxiv.org/abs/2406.08660
- [S26] Erdogan et al., "TinyAgent: Function Calling at the Edge", arXiv 2409.00608, 2024-09. https://arxiv.org/abs/2409.00608
- [S27] Biderman et al., "LoRA Learns Less and Forgets Less", arXiv 2405.09673, 2024-05-15. https://arxiv.org/abs/2405.09673
- [S28] "OpenJarvis: Personal AI, On Personal Devices", arXiv 2605.17172, 2026-05. https://arxiv.org/abs/2605.17172
- [S29] Anthropic Consumer Terms, §3, effective 2025-10-08. https://www.anthropic.com/legal/consumer-terms
- [S30] Intel ARK, Core i7-3615QM. https://www.intel.com/content/www/us/en/products/sku/64900.html
- [S31] Anthropic, "Introducing Claude Sonnet 4.5", 2025-09-29. https://www.anthropic.com/news/claude-sonnet-4-5
- [S32] mlx-tune (formerly unsloth-mlx, community project, not affiliated with Unsloth). https://pypi.org/project/mlx-tune/
- [S33] Ollama library, qwen3.5 tags. https://ollama.com/library/qwen3.5/tags
- [S35] Community notes on the macOS GPU wired-memory limit (`iogpu.wired_limit_mb`). https://github.com/ivanopcode/devnote-override-macos-metal-vram-cap
- Internal: marvin#46, #563, #594, #674 (read 2026-11-11); `bench/RESULTS.md` Run 15; ADR 0045; memory `project-exo-distributed-inference-attempt`, `project-marvin-voice`.
