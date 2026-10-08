# A general image maker: themes, moods and art styles for any project — 2026-10-08

Gil: "All the styles available are based on the current projects and I want it to be fully generalized for every
project… if I get to choose from styles it should be different themes, moods, or art styles." Decided the same day:
a **local AI art model** draws them (free, on the Mac mini), and MARVIN keeps its map picture until the new maker can
replace every project's image at once.

## Where it stands (2026-10-08)

- `lib/portfolio_imagegen.py` + `lib/portfolio_motifs.py`: deterministic, free, unique per project (128-bit fingerprint,
  re-rolled if two images look alike), with the Images tab (variants, choose, apply to dev).
- The choices are **17 motifs drawn for particular projects** (a mancala board, a sudoku grid, MARVIN's network, an
  ATT&CK matrix…) plus 5 abstract patterns. A new project gets no motif that means anything for it.
- **Apply updates the card, not always the hero.** It saves `<slug>-600w.jpg` and `<slug>-hero.jpg`, then points only
  the project list (cards) at the new image. 15 of 18 pages already use `uploads/generated/<slug>-hero.jpg`, so their
  hero follows; **MARVIN** (custom `figures/marvin/marvin-map-hero.jpg`), **Resume Tailor** and **Paper Dive** (no hero
  at all) don't.

## Design

**Three general axes, chosen per project, none tied to a project:**

| Axis | What it controls | Examples |
|---|---|---|
| Art style | how it's drawn | blueprint line art, watercolor, ink brush, low-poly, isometric, risograph print, paper cut-out, minimal vector |
| Mood | colour and light | calm, energetic, nocturnal, warm, cool, monochrome, sunrise, neon |
| Subject | what it shows | drafted from the project's own description (catalog + portfolio card), editable |

The catalog of art styles and moods is a data file, so adding one is a line, not code.

**Engine:** FLUX.1-schnell (Apache-2.0) via mflux on the Mac mini, 4-bit (about 6-7 GB; the mini has ~24 GB free and a
15 GB disk guard, so the disk ledger tracks it). About a minute per image, one at a time, queued. No API cost. Each
image records its prompt, seed and settings, so it can be reproduced exactly.

**One picture, both crops.** Each image is generated once, wide enough for both shapes; the card (800x500) and the
hero (2200x600) are cut from that same picture (the approach `render_map_images.py` uses for the map). Card and hero
can't drift apart.

**Uniqueness stays:** the existing fingerprint check runs on every new image; one too close to another project's is
re-seeded.

**Apply keeps card and hero together for every project:** it points each page's hero at the generated hero (fixing
MARVIN, Resume Tailor, Paper Dive) and the Images tab flags any page whose hero and card differ.

**Privacy:** prompts use only public text (the card description); a private project gets no prompt from its private
docs.

## Tasks (tickets)

1. #285 Style catalog (art styles x moods) as data + a prompt builder from a project's public description.
2. #286 FLUX engine on the mini: install mflux + 4-bit schnell, a queued generate job, prompt/seed/settings recorded,
   one master image -> card + hero crops, fingerprint uniqueness.
3. #287 Images tab: pick art style and mood (and edit the subject line), see variants, choose; the generator stays as an
   instant fallback for abstract looks.
4. #288 Apply writes card and hero from the same image for every project and fixes page heroes; flags mismatches.
5. Then: every project (MARVIN included) gets its new image on dev, for Gil to review and promote.

## Models: reuse first, download only when nothing we have can do it (Gil, 2026-10-08)

Inventory 2026-10-08 (the mini holds almost all of it; 24 GB free):

| Model | Size | Used by |
|---|---|---|
| qwen2.5 14b / 7b / 3b (Ollama) | 9.0 / 4.7 / 1.9 GB | paper-dive only (logic auditor, competing ideas, argument mapper) |
| nomic-embed-text (Ollama, both Macs) | 0.27 GB | core: memory search, routing, embeddings |
| specter2 (HF) | 0.84 GB | paper-dive citation graph |
| MiniLM (Chroma default) | 0.17 GB | core vector search |
| Llama-3.2-3B / Qwen2.5-3B / Llama-3.2-1B, MLX 4-bit (HF) | 1.9 / 1.6 / 0.02 GB | nothing: exo test leftovers |
| FLUX.1-schnell | gone | the Seal icon run's weights were removed; only the mflux tool is left on the laptop |

Rules:
- **A shared model list** (`config/models.json`): every model, where it lives, its size, what uses it, when it was last used.
  A new feature picks from it first; adding a model means a list entry with its reason, and a download only after that.
- **One heavy model at a time per Mac**, through a queue: Ollama already queues its own requests, but FLUX and the 14b
  model can't both be loaded on a 16 GB Mac. Jobs wait their turn instead of failing or swapping.
- **Visible:** the dashboard shows the list, sizes, what uses each, last use, and the queue (what's running, what's waiting).
- **For the image maker:** FLUX is the only image model, so it is a justified download, but the pre-quantized 4-bit
  build (~6-10 GB), not the full weights (~30 GB, more than the mini's free space).
