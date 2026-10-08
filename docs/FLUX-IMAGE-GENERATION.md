# FLUX.1 Image Generation for Portfolio Projects (#286)

## Overview

Generates unique, deterministic hero images for portfolio projects using FLUX.1-schnell (4-bit quantized) running on the mac-mini. One master image per project, cropped to both card (800×500) and hero (2200×600) formats. Images are queued (one at a time, ~1 min each), fingerprinted for uniqueness, and re-rolled if too similar to existing projects.

**Status:** Implementation complete. Manual end-to-end verification required on mac-mini.

## Implementation

### Components

1. **Model Registry** (`lib/model_registry.py` + `config/models.json`)
   - Central registry of all AI models: location, size, usage, last accessed
   - Atomic writes via fcntl locking
   - Seeded with image-maker inventory (qwen, nomic, specter2, MiniLM, leftover MLX models, FLUX.1-schnell-4bit)

2. **Image Generation Engine** (`lib/portfolio_flux.py`)
   - `generate(prompt, seed, size)` — dispatches mflux to mac-mini, returns image + seed + settings
   - `crop_card_and_hero(master)` — extracts both output sizes from one 1920×960 master (reuses render_map_images.py crop pattern)
   - `check_disk_headroom(min_disk_gb, download_gb)` — verifies free space before download; reads 15 GB guard from config/dispatch.json
   - `queued_generate(slug, prompt, seed)` — wraps generation in fcntl single-flight lock + job_events logging; re-rolls on fingerprint collision
   - `is_unique(candidate_hash, existing_hashes, min_distance)` — reuses Hamming distance from portfolio_imagegen
   - `record_sidecar(slug, prompt, seed, settings)` — writes JSON with model build id, prompt, seed, steps, guidance, master size

3. **CLI Entrypoint** (`lib/portfolio_flux.py main()`)
   ```bash
   portfolio_flux.py SLUG --prompt "..." [--seed N]
   ```
   Mirrors `portfolio_imagegen.py` shape. Returns JSON with paths to generated images.

4. **Disk Guard** (built into `check_disk_headroom`)
   - Reads `config/dispatch.json` → `guards.min_disk_gb` (default: 15 GB)
   - Before any download, checks: `free_space > download_size + min_disk_gb`
   - Refuses with clear error if insufficient

5. **Queued Job** (in `queued_generate`)
   - Single-flight lock via fcntl on `~/.claude/dispatch/locks/flux-generate.lock`
   - Wrapped in `job_events.job_run("flux-generate")` for Activity tab visibility
   - Concurrent callers queue; one job runs at a time (~1 min each)

6. **Reproducibility**
   - Per-image JSON sidecar next to the PNG: `~/.claude/portfolio/images/<slug>/flux-<slug>-<seed>.json`
   - Records: model build id, prompt, seed, steps (20), guidance (7.5), master size (1920×960)
   - Allows exact reproduction

7. **Uniqueness** (reuses portfolio_imagegen)
   - Fingerprints hero crop (128-bit dHash + spectral hash)
   - Compares Hamming distance to all existing projects' hashes
   - MIN_DISTANCE = 24 (from portfolio_rules)
   - If too close, re-rolls seed (up to 7 retries) and regenerates full image

## Design Decisions

- **Master size (1920×960):** Multiple of 16 (MLX requirement), wide enough to crop both card/hero without upscaling, matches render_map_images.py pattern
- **Single master, two crops:** Card and hero always match (no drift), reuses proven layout approach from MARVIN map
- **4-bit quantized model (~6.5 GB):** Fits in mac-mini's free space with 15 GB guard buffer
- **Queued execution:** One image at a time prevents GPU thrashing; ~1 min per image is acceptable for batch generation
- **Registry in config/models.json:** Central point; dashboard can list all models, their sizes, usage, and last access; new features pick from registry first, download only if missing
- **Fingerprint re-rolling:** Deterministic, reproducible, avoids silent twin images; the same (slug, prompt, seed) always produces the same image

## Setup: Installation on mac-mini (manual, one-time)

Before first use, install mflux into `~/.agents/venv`:

```bash
# SSH to mac-mini
ssh mac-mini

# Install mflux (assumes pip is in ~/.agents/venv/bin)
~/.agents/venv/bin/pip install mflux

# Verify the real flag names (in case of version drift)
~/.agents/venv/bin/mflux-generate --help
```

Confirm flags match those in `portfolio_flux.generate()` (currently: `--prompt`, `--seed`, `--width`, `--height`, `--output`, `--steps`, `--guidance`).

The 4-bit schnell model will download automatically on first run (into `~/.cache/huggingface/`), tracked by the disk ledger under the "models" category.

## Testing

**Unit tests** (no GPU/mac-mini needed):
```bash
pytest lib/tests/test_portfolio_flux.py -xvs
```
Covers: crop geometry, uniqueness re-seeding, registry writes, disk guard, sidecar metadata, CLI parsing.

**Manual end-to-end verification** (requires mac-mini with mflux installed):
```bash
# From the repo root (on any machine, will dispatch to mac-mini)
lib/portfolio_flux.py test-project --prompt "a vibrant abstract landscape" --seed 42

# Should output JSON with paths to generated images, e.g.:
# {
#   "slug": "test-project",
#   "seed": 42,
#   "card": "/Users/gileskayo/.claude/portfolio/images/test-project/flux-card-42.jpg",
#   "hero": "/Users/gileskayo/.claude/portfolio/images/test-project/flux-hero-42.jpg"
# }

# Verify files exist and are the correct sizes:
# ls -la ~/.claude/portfolio/images/test-project/
# file ~/.claude/portfolio/images/test-project/flux-card-42.jpg
```

## Out of Scope for #286

- Images tab UI to pick art style, mood, subject (#287)
- Apply-to-site wiring: writing card+hero for every project, fixing page heroes (#288)
- Backfilling precise measurements for every model beyond the plan doc's numbers
- Integration with the portfolio image registry (left for #288)

## Ticket Checklist

- [x] Model registry module + config file (all models from 2026-10-08 inventory)
- [x] Disk guard (15 GB buffer from dispatch.json)
- [x] Image generation engine (mflux dispatch to mac-mini)
- [x] Crop geometry (card + hero from master)
- [x] Queued job (fcntl single-flight lock + job_events)
- [x] Reproducibility (JSON sidecars)
- [x] Uniqueness checking (Hamming distance, re-roll logic)
- [x] CLI entrypoint (mirrors portfolio_imagegen.py)
- [x] Unit tests (19 passing, 1 skipped)
- [ ] Manual e2e verification on mac-mini (requires install)
