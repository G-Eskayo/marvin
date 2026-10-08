# ADR 0059: Shared model registry and heavy-model queue

**Date**: 2026-10-08  
**Status**: Implemented  
**Author**: Claude (MARVIN implementation)

## Context

The local-model ecosystem on the mini and MacBook Pro is heterogeneous: qwen2.5:14b and qwen2.5:7b (Ollama), FLUX.1-schnell (mflux), nomic-embed-text, specter2 (HuggingFace), and some MLX leftovers from exo experiments. No inventory: models appear in hardcoded constants throughout the codebase (paper-dive scripts, future tooling), with no shared visibility into what's installed, when it was last used, or how much disk they consume. Critical problem: heavy models (qwen2.5:14b, FLUX) can't coexist in the 16 GB Mac mini's memory, but there's no queue to serialize access — concurrent requests fail or thrash swap.

Paper-dive's hardcoded model choices were validated exhaustively (2026-07-13, logic_auditor design doc, "Model" section) against real abstracts: 14b for classification, 3b for extraction, 7b for judgment. The goal here is to preserve those validated choices (via capability indirection) while making the inventory visible and preventing the heavy-model collision.

## Decision

1. **Shared static registry** (`config/models.json`): human-curated list of every installed or intended-to-install model — name, runtime (ollama/hf/mlx), what uses it, size (optional, computed at read-time for live snapshots), whether it's heavy (needs queue gating). Anything that goes stale (currently loaded, exact disk usage) is computed at read time; only facts that don't rot are stored.

2. **Capability indirection** (`lib/model_registry.py:resolve_capability`): maps task names like `local-classify-medium` → `qwen2.5:14b`. Paper-dive constants resolve at startup; tests assert the resolved model hasn't drifted from the validated choice.

3. **Per-Mac heavy-model queue** (`lib/model_queue.py`): serializes access to models marked `"heavy": true`. Implemented as task records in `~/.claude/model-queue/tasks/` with status (waiting/running); acquire() is a context manager that blocks until no other alive heavy task on the same machine is running, then deletes the record on exit. Dead holders (crashed processes) are reaped on every read via `_pid_alive`, same as dispatch's slot reaping.

4. **Usage logging** (`lib/model_registry.py:record_usage`): best-effort append to `~/.claude/logs/model-usage.jsonl` (never raises), atomically updated `~/.claude/logs/model-last-used.json` for dashboard freshness. Called from every ollama_chat site after the HTTP response.

5. **Consistency check** (`lib/model_registry.py:check_consistency`): two-severity verification:
   - **Hard fail** (RuntimeError): a model-literal pattern (`qwen2.5:*`, `nomic-embed-text`, `specter2`, `flux1-schnell`) found in code but not in `models.json`; or an `resolve_capability()` call trying to map an unknown capability (a programming error, must fail loud).
   - **Soft warning** (printed): a registry entry with empty `used_by` and no `reason` explaining why — nudges cleanup of the MLX leftovers.

6. **Route.py integration** (`route.py --local-capability`): looks up a capability in the shared registry and reports whether it's installed on the current machine as JSON (exit 0 if installed, 1 if not). Paper-dive could call this to verify before attempting a heavy operation, but today paper-dive calls the models directly; this is plumbing for future consumers.

## Paper-dive wiring

All three paper-dive scripts (logic_auditor.py, argument_mapper.py, competing_ideas.py) now:
1. Import model_registry and machine_profile.
2. Resolve capabilities at module load time: `CLASSIFY_MODEL = resolve_capability("local-classify-medium")`.
3. Wrap heavy-model calls with `model_queue.acquire(model, machine, caller)`.
4. Call `model_registry.record_usage(model, caller, machine)` after each Ollama HTTP response.

Tests in each script's test file assert the resolved model matches the validated choice (a regression guard). Running tests verifies the registry was read successfully and capabilities resolved correctly.

## Dashboard integration

Dashboard components (HealthDashboard.jsx, ModelsPanel.jsx) mirror the existing dispatch_concurrency.js/NextUpQueue pattern:
- `dashboard/electron/main/models.js`: execFile wrapper around model_registry.py and model_queue.py CLI, cached 60s TTL.
- IPC handlers in electron/main/index.js + preload/index.js expose models:list and models:queue.
- ModelsPanel.jsx renders a table (name, runtime, size, used_by, last_used, machine) and a queue section reusing NextUpQueue row styling.
- HealthDashboard.jsx adds a 4th tab alongside checks/agents/readiness → models.

(Dashboard implementation deferred pending environment; the plumbing is laid out in this ADR for future completion.)

## Trade-offs

**Judgment call on model scoping**: route.py's `--local-capability` is a read-only lookup, not an auto-routing decision ("route any task to a local model that can do it"). That auto-routing would require a new multi-intent classifier distinguishing classification vs. extraction vs. embedding, with no second real consumer today (only paper-dive). Instead, route.py exposes the lookup directly, and paper-dive calls it explicitly where needed. This keeps the scope tight: inventory + queue + usage visibility + validation (not inference).

**FLUX not pre-added**: #286 (the FLUX engine task) will add its own entry to models.json before downloading weights, not this ticket. Adding it now would immediately flag "unused model" (since no code references it yet), violating rule 4.

**Machine naming**: model-queue keys use `machine_profile.machine_label()` (unsuffixed: "mac-mini", "macbook-pro"), which is the stable identity function. This differs from dispatch.json's suffixed keys ("mac-mini-1"), a pre-existing inconsistency noted but not fixed here (out of scope for this ticket).

## Acceptance criteria

✅ Shared registry (config/models.json) with all 8 models + 6 capabilities  
✅ model_registry.py with load/save/resolve/record_usage/check_consistency  
✅ model_queue.py with acquire() context manager and current_queue()  
✅ All 6 hardcoded constants in paper-dive replaced with resolved capabilities  
✅ Queue gating on heavy models (14b for classify/infer, 14b for benchmark override)  
✅ Usage logging on every ollama_chat call  
✅ Test regression guards on each paper-dive script  
✅ route.py --local-capability lookup  
✅ ADR documenting the design

(Dashboard components are laid out but rendering/testing deferred pending UI environment.)
