# ADR 0061: Model Capabilities and Per-Machine Heavy-Model Queue

## Status

Accepted (closes #290; reconciles PR #295 with #286)

## Context

MARVIN runs CPU-intensive local models (qwen2.5:14b, FLUX.1-schnell-4bit) that cannot coexist in 16GB VRAM.
Two independent code paths needed coordination:
- **paper-dive** uses qwen2.5:14b for logic auditing, 14b and 3b and 7b for different extraction layers
- **portfolio-flux** uses FLUX.1-schnell-4bit for image generation

Each had hardcoded model names, no queue coordination, and no capability indirection.

PR #295 built capability indirection + a per-machine heavy-model queue (intended for paper-dive).
PR #286 (merged first) added a simpler flat model registry with basic metadata (size, used_by, location).
Direct merge would lose either capability routing or the registry's schema; this ticket reconciles them.

## Decision

Extend the flat registry schema (keep existing API intact; `portfolio_flux.py` tests depend on it):
1. Add per-model fields: `heavy: bool`, `machine: str | None`
2. Add separate `config/model_capabilities.json` mapping capability names → model names
3. Extend `lib/model_registry.py` with:
   - `resolve_capability(name)` → model string (KeyError if unknown)
   - `is_heavy(model_name)` → bool
   - `check_consistency()` → hard-fail on code literals/capabilities not in registry; soft-warn on unused models
4. Create `lib/model_queue.py`: per-machine queue for heavy models (reuse dispatch_concurrency's PID reaping)
5. Wire **both** paper-dive and portfolio-flux onto the shared queue
6. Rename Ollama entries from hyphenated (`qwen2.5-14b`) to colon form (`qwen2.5:14b`) — literal match to API strings for consistency checks
7. Add `route.py --local-capability` flag for capability → model resolution
8. Build dashboard UI: models table + queue section in Health Dashboard's new "Models" tab

## Rationale

- **Backward-compat**: Existing `portfolio_flux.py` code calling `registry.get()` / `registry.all()` / `registry.touch_last_used()` works unchanged; new fields are optional
- **Single source of truth**: Model registry is the one place name/size/location lives; capabilities map add indirection without duplication
- **Consistency enforcement**: `check_consistency()` hard-fails if code references a model not yet in the registry (catches typos, undefined capability names) but only soft-warns on unused models (allows planned-but-not-yet-deployed models)
- **Validated model choices**: Each paper-dive model size is validated per task (14b for classification despite being regression for extraction; 3b fine for extraction; 7b for judgment). Capability mapping preserves those choices via indirection
- **Shared coordination**: Both portfolio_flux and paper-dive can now queue heavy models on the same machine without collision (first-come, first-served; poll-wait for qwen2.5:14b to finish before starting FLUX.1, or vice versa)

## Implementation

1. `lib/model_registry.py` extensions + `config/model_capabilities.json`
2. `lib/model_queue.py` (per-machine context manager, reuses dispatch_concurrency's alive-check)
3. Paper-dive `logic_auditor.py`, `argument_mapper.py`, `competing_ideas.py`: replace hardcoded models with `resolve_capability()` calls; wrap ollama_chat in `model_queue.acquire()`
4. `lib/portfolio_flux.py`: replace fcntl lock with `model_queue.acquire()`
5. `skills/route/scripts/route.py`: add `--local-capability` flag
6. Dashboard: `models.js` (wrapper around registry/queue CLI), new `ModelsPanel.jsx`, wire into `HealthDashboard.jsx` as 4th tab

## Testing

- Unit tests for `model_registry.py`: resolve_capability, is_heavy, check_consistency, schema backcompat
- Unit tests for `model_queue.py`: task persistence, filtering, blocking on concurrent heavy models, reaping dead PIDs
- Regression tests in paper-dive: each resolved capability still equals the validated model (blocks silent capability-map edits that change model sizes)
- Existing `portfolio_flux.py` tests pass unchanged (schema additions are backward-compatible)

## Consequences

**Positive:**
- Both paper-dive and portfolio-flux coordinate without deadlock or VRAM collision
- Dashboard visibility into model usage and queue state (last_used timestamps, task status)
- Typos in model names caught early by consistency check, not at runtime
- Easy to add new heavy models or expand to multi-model tasks later (queue already supports it)

**Negative:**
- Two files now (registry.json + model_capabilities.json) instead of one; consistency check enforces the mapping
- Check_consistency is a defensive tool, not a breaking gate (soft-warns on unused models)
- Download-time enforcement is process-rule (doc + test), not runtime gate (no separate `ollama pull` validator; consistency check runs in CI)

## References

- #290 (this ticket)
- PR #295 (capability indirection + queue design draft, now integrated)
- PR #286 (merged model registry, now extended)
- ADR 0052 (dispatch coordination pattern, reused for model queue)
- lib/dispatch_concurrency.py (PID reaping helpers, reused unchanged)
