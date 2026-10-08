# ADR 0061: Model Registry, Queue, and Local Routing

**Status:** Implemented  
**Date:** 2026-10-08  
**Deciders:** G-Eskayo  
**Implementation Date:** 2026-10-08  

## Context

MARVIN has grown to manage multiple local models (qwen2.5 in three sizes, FLUX, embeddings, etc.) and needs to solve three problems:

1. **No registry:** Models are referenced ad-hoc in code (hardcoded in paper-dive, nascent in route.py). A model can be pulled without being declared, and stale models accumulate with no visibility.
2. **Heavy-model contention:** FLUX and qwen2.5:14b don't fit together on 16GB Macs. Only one can run at a time. Without a queue, concurrent job requests fail unpredictably or crash.
3. **Model swapping:** If we want to upgrade qwen2.5:7b → qwen2.5:8b, it requires edits in three files (logic_auditor, competing_ideas, argument_mapper). Capability-based routing decouples implementation from names.

## Decision

### 1. Central Registry: `config/models.json`

A single source of truth for all models MARVIN manages locally or knows about:

```json
{
  "qwen2.5-14b": {
    "size_gb": 9.0,
    "location": "~/.ollama/models",
    "reason": "logic auditing, competing ideas, argument mapper",
    "used_by": "paper-dive",
    "last_used": "2026-10-08T...",
    "capability": "local-classify-large",
    "heavy": true
  },
  ...
}
```

**Fields:**
- `size_gb`, `location`: Where it lives and how big.
- `reason`: Why we have this model (required for download gating).
- `used_by`: Which feature or skill depends on it.
- `last_used`: ISO timestamp of last execution (updated by health checks and job logs).
- `capability`: What it can do (e.g., `local-classify-large`, `local-embed`, `image-gen`). Replaces hardcoded model names in code.
- `heavy`: Whether it needs exclusive resource access (FLUX, qwen2.5:14b only).

**File Locking:** Mirrored from ADR 0056 (disk-ledger). Atomic writes via temp-file-and-rename.

### 2. Per-Machine Queue: `~/.claude/logs/model-queue.json`

Local, non-synced state (mirrors `jobs.js` pattern, not disk-ledger's committed-ledger):

```json
{
  "locks": {
    "FLUX.1-schnell-4bit": {
      "job_id": "portfolio-flux:job-1234",
      "acquired_at": "2026-10-08T..."
    }
  },
  "waiters": {
    "qwen2.5-14b::paper-dive:job-5678": {
      "queued_at": "2026-10-08T..."
    }
  }
}
```

**API:** `model_queue.py`
- `acquire(model, job_id, is_heavy=True, timeout=None)`: Blocks if another heavy model holds the lock. Returns `True` on acquire, `False` on timeout. Non-heavy models return `True` immediately (no queue).
- `release(model, job_id)`: Free the lock and wake the next waiter.
- `status()`: Current locks and waiters (for dashboard, health checks).

**Call Sites:** Wrap Ollama job runners and paper-dive's qwen2.5:14b calls with acquire/release guards.

### 3. Download Gate: `lib/model_download_gate.py`

No model is downloaded without being in the registry with a non-empty reason field.

```python
gate = ModelDownloadGate()
gate.can_download("unknown-model")  # Raises UnregisteredModelError
gate.can_download("qwen2.5-7b")     # OK if in registry with reason
```

This prevents silent introduction of undeclared models and makes the registry the single point of governance.

### 4. Capability-Based Routing

`lib/model_registry.py` adds:
- `by_capability(capability)`: Returns models tagged with that capability, sorted by size (largest first, for quality).
- `heavy_models()`: Returns all heavy models.

**Paper-dive adoption:**
- `logic_auditor.py`: Replace `CLASSIFY_MODEL = "qwen2.5:14b"` with `_get_classify_model()` that calls `registry.by_capability("local-classify-large")`, falls back to hardcoded if registry unavailable.
- `competing_ideas.py`: Similar, uses `local-classify-medium`.
- `argument_mapper.py`: Similar, uses `local-classify-small`.

Swapping the model is now a one-line change to `config/models.json`.

### 5. Audit and Health Checks

**`lib/model_audit.py`:** Detect:
- Stale models: `last_used` is null or older than a threshold (default 365 days). Reported, not auto-deleted.
- Unregistered references: Grep for model identifiers in code not in the registry (e.g., someone hardcodes `ollama.pull("new-model")`). Prevents accidental model refs.
- Invalid `used_by`: Entries that claim a feature uses them but the feature no longer exists.

Wired as a pytest-collected test and/or pre-commit hook (deferred to follow-up ticket).

**Health checks:** Extended `lib/health_checks.py`'s per-machine SSH probe:
- Added `models_queue` field to `_MACHINE_STATE_SCRIPT` (reads `~/.claude/logs/model-queue.json`).
- Parse into `parse_machine_state()`.
- Evaluate in `evaluate_machine_state()`: report current lock holder and waiter count.
- Dashboard will surface as a new "Model lock/queue state" health item alongside disk/jobs.

### 6. Dashboard Integration (Out of Scope for This Ticket)

A follow-up PR will add:
- `dashboard/electron/main/models.js`: Reads registry from repo, merges in per-machine queue state from health checks. Exposes `ipcMain.handle('models:list', ...)`.
- `dashboard/src/components/ModelsPanel.jsx`: Table of models, sizes, used-by, last-used, with per-machine lock status. Mounted in `HealthDashboard.jsx` (models are per-Mac infrastructure state, like disk).

## Rationale

- **Registry in repo, queue local:** Models are declared up-front (repo-synced), but live lock state is per-machine (no commit storms, no cross-machine conflicts).
- **Capability over names:** Intents (extract, classify, embed) are stable; implementations (qwen2.5:3b → 3.1b) change. Decouples code from model updates.
- **Download gate:** Catches undeclared models early. Every model in the wild must have a reason.
- **Health-check integration:** Per-machine queue state is surfaced the same way disk usage is — no new dashboard mechanism, reuses existing SSH probe pattern.

## Consequences

- New models require a registry entry (one-time, documented).
- Heavy-model jobs must acquire/release the queue lock (thin wrapper, ~5 LOC per site).
- Paper-dive code is now decoupled from model names (cleaner refactors, testable via DI).
- Model staleness is visible (health dashboard), but cleanup is manual (safe, prevents accidental deletions).

## Implementation Status

### Completed (Iteration 1 - 2026-10-08)

1. **Registry Schema** ✅
   - Fixed model naming: Ollama tags use colons (`qwen2.5:14b`, not `qwen2.5-14b`)
   - Extended schema with `runtime`, `machine`, `capability`, `heavy` fields
   - `used_by` changed from single string to list
   - Updated `config/models.json` with full schema

2. **Registry API** ✅
   - `ModelRegistry.resolve_capability(capability)`: Get best model for a capability (sorted by size)
   - `ModelRegistry.is_heavy(name)`: Check if model requires exclusive access
   - `ModelRegistry.by_machine(machine)`: Get models available on a specific machine
   - Updated `register()` to accept new fields

3. **Model Queue** ✅
   - Fixed `acquire()` bug: now properly blocks and retries instead of returning False immediately
   - Fixed default-argument isolation bug: accept `state_path` parameter, not module-level default
   - All 9 model_queue tests pass (acquire, release, blocking, timeout, waiter notification)

4. **Consistency Checks** ✅
   - `test_model_consistency.py`: Exact-literal scan of paper-dive model references
   - Hard-fail if a model reference isn't in registry
   - Soft-warning for unused entries
   - Validates qwen models use colon separator (Ollama format)
   - Wired as pytest tests in normal suite

5. **Download Gate** ✅
   - `ModelDownloadGate.can_download()` raises on unregistered models or missing reason
   - Ready to wire into portfolio_flux.py FLUX download path (future work)

### Pending (Deferred to Follow-up)

- **Route.py integration:** `--local-capability` flag not yet implemented (scope amendment, optional)
- **Queue status visualization:** Live lock/waiter display in Models tab (currently shows registry only)
- **Health checks integration:** Model queue state surface in health probe output
- **Download gate wiring:** portfolio_flux.py FLUX fetch not yet gated
- **Pre-commit hook:** Consistency checks not yet on pre-commit (pytest only)

### Test Results

- 58 model-related tests pass (registry, queue, consistency, audit, download gate)
- Fixes validated on original issue scenarios:
  - `acquire()` now properly blocks when another model holds lock
  - Default-argument isolation fixed; tests no longer leak state
  - Registry key names match actual Ollama tags

## Related

- ADR 0056: Disk ledger (file-locking, per-machine local state pattern).
- ADR 0023: Intent routing (keyword + embedding classification; local models augment this).
