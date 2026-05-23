# MARVIN

> *"I have a brain the size of a planet and they ask me to take them to the bridge."*
> — Marvin, The Hitchhiker's Guide to the Galaxy

**MARVIN** is an open-source configuration layer for [Claude Code](https://claude.ai/code) that turns it into a persistent, learning AI partner. Where Claude starts each session cold, MARVIN gives it structured memory, domain skills, and semantic retrieval — so it finds exactly the right knowledge at the right moment, nothing more.

Named after the Hitchhiker's Guide's brilliant, underutilised android. This project is about making sure that brain gets used.

---

## What MARVIN Does

Out of the box, Claude Code is stateless. Every session starts from scratch. MARVIN adds:

| Feature | What it means |
|---|---|
| **Skill system** | 20 structured instruction sets Claude invokes by context — TDD, debugging, architecture review, research, and more |
| **Persistent memory** | Knowledge files Claude writes to and reads from across sessions |
| **Semantic retrieval** | Hybrid BM25 + vector search (nomic-embed-text) surfaces the most relevant files per query |
| **Auto-maintenance** | A PostToolUse hook rebuilds the manifest and re-embeds changed files on every save |
| **Adaptive precision** | Analytical queries use tight thresholds; creative queries cast wider nets |

The goal is a system that grows as you use it — not one that ships complete.

---

## Architecture

```
Your request
     │
     ▼
 manifest.json          ← flat index of all skills + knowledge
     │  tags[]
     ▼
 Tag filter             ← namespace:value matching (domain:, intent:, type:)
     │
     ▼
 ChromaDB               ← 768-dim vectors via nomic-embed-text
     │  cosine similarity
     ▼
 BM25 re-rank           ← keyword overlap on candidates
     │  RRF merge
     ▼
 Loaded files           ← only what this task needs
     │
     ▼
  Claude Code
```

Skills live in `~/.agents/skills/`. Each skill is a `SKILL.md` file with frontmatter tags. Knowledge files live in `~/.claude/projects/*/memory/`. Both feed the same manifest and the same vector store.

---

## Screenshots

> Screenshots are added as the project evolves. Contributions welcome.

| Screenshot | Description |
|---|---|
| `assets/screenshots/skill-invocation.png` | Claude invoking the `tdd` skill via `/tdd` |
| `assets/screenshots/retrieval-output.png` | `retrieve.py` ranked results for a query |
| `assets/screenshots/manifest-structure.png` | `manifest.json` after a full rebuild |
| `assets/screenshots/chroma-populated.png` | ChromaDB collections after initial setup |

---

## Prerequisites

- **[Claude Code](https://claude.ai/code)** — the CLI or desktop app. Free tier works.
- **An Anthropic API key** — set as `ANTHROPIC_API_KEY` in your environment.
- **Python 3.9–3.12** — see [Platform Compatibility](#platform-compatibility) for version notes.
- **~600 MB disk space** — 274 MB for the nomic-embed-text model, ~300 MB for ChromaDB and Python deps.
- **Internet connection** — for the initial Ollama model pull. Fully offline after that.

No GPU required — but GPU is used automatically if available. See [GPU Acceleration](#gpu-acceleration) below.

---

## Quick Start

```bash
git clone https://github.com/your-username/marvin.git
cd marvin
chmod +x setup.sh
./setup.sh
```

That's it. Open Claude Code and start a new session. MARVIN loads silently.

---

## What Gets Installed

```
~/.agents/
├── skills/                    ← 20 skill SKILL.md files
│   └── self-improve/
│       └── scripts/
│           ├── rebuild-manifest.py   ← manifest rebuild
│           ├── rebuild-embeddings.py ← vector sync
│           ├── retrieve.py           ← hybrid retrieval CLI
│           └── tag-files.py          ← one-time migration
└── venv/                      ← Python virtualenv (chromadb, rank_bm25)

~/.claude/
├── CLAUDE.md                  ← Global Claude instructions + skill routing
├── lexicon.md                 ← Shared vocabulary (compressed context)
├── manifest.json              ← Generated index (do not edit by hand)
├── chroma/                    ← ChromaDB vector store
└── settings.local.json        ← PostToolUse hook configuration
```

---

## Manual Setup

If you prefer to install step by step, or if `setup.sh` fails at a specific stage:

### 1. Install Ollama

| Platform | Command |
|---|---|
| macOS (any) | `brew install ollama` |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |
| WSL2 | `curl -fsSL https://ollama.com/install.sh \| sh` |

Then start the service and pull the model:

```bash
# macOS
brew services start ollama
ollama pull nomic-embed-text

# Linux / WSL2
ollama serve &
ollama pull nomic-embed-text
```

### 2. Python virtualenv

```bash
# Find a compatible Python (3.9–3.12)
python3.11 -m venv ~/.agents/venv        # adjust version as needed
~/.agents/venv/bin/pip install chromadb rank_bm25 requests
```

### 3. Copy skills

```bash
mkdir -p ~/.agents/skills
cp -r skills/* ~/.agents/skills/
```

### 4. Copy Claude config

```bash
cp claude-config/CLAUDE.md ~/.claude/CLAUDE.md
cp claude-config/lexicon.md ~/.claude/lexicon.md
```

If these files already exist, review the diff and merge manually.

### 5. Configure the hook

Edit or create `~/.claude/settings.local.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/.agents/venv/bin/python /path/to/.agents/skills/self-improve/scripts/rebuild-manifest.py"
          }
        ]
      }
    ]
  }
}
```

Replace the paths with your actual `~/.agents/venv/bin/python` and skills directory.

### 6. Build the manifest and embeddings

```bash
~/.agents/venv/bin/python ~/.agents/skills/self-improve/scripts/tag-files.py
~/.agents/venv/bin/python ~/.agents/skills/self-improve/scripts/rebuild-manifest.py
```

---

## Platform Compatibility

| Platform | Status | Notes |
|---|---|---|
| macOS ARM (M1/M2/M3/M4) | ✅ Full support | Recommended — Ollama runs natively |
| macOS x86 (Intel) | ✅ Full support | Ollama runs natively |
| Ubuntu / Debian (x86_64) | ✅ Full support | Use Python 3.11 from apt |
| Fedora / RHEL (x86_64) | ✅ Full support | Use Python 3.11 from dnf |
| Linux ARM (Raspberry Pi 5+) | ⚠️ Partial | Works but embedding is slow (~5s/file). 4 GB RAM minimum. |
| Windows (WSL2) | ✅ Full support | Run `setup.sh` inside WSL2. Ollama runs in WSL. |
| Windows (native) | ❌ Not supported | Use WSL2. The hook system uses bash and POSIX paths. |
| ChromeOS (Linux container) | ⚠️ Untested | Should work via the Linux container |

### Python Version Notes

> **Python 3.14+ is not compatible.** A `libexpat` ABI mismatch in macOS system libraries causes pip to crash on Python 3.14 (and some builds of 3.11 installed via Homebrew on macOS 14–15). The setup script detects this automatically and selects a working version.

Verified working: Python **3.9**, **3.10**, **3.11** (from apt/CommandLineTools), **3.12**

---

## Limitations and Computing Requirements

### Minimum requirements

| Resource | Minimum | Recommended |
|---|---|---|
| RAM | 4 GB | 8 GB+ |
| Storage | 1 GB free | 2 GB+ |
| CPU | Any 64-bit | Apple Silicon M1 or Intel Core i5 8th gen+ |
| Internet | Required at setup | Not required after first run |
| OS | macOS 12+, Ubuntu 20.04+, Fedora 35+ | macOS 14+, Ubuntu 22.04+ |

### GPU Acceleration

Ollama detects and uses GPU automatically — no configuration required.

| Hardware | Backend | Relative speed |
|---|---|---|
| Apple Silicon (M1/M2/M3/M4) | Metal + Neural Engine | ~4–8× faster than CPU |
| NVIDIA (Linux / WSL2) | CUDA (auto if drivers installed) | ~10–30× faster than CPU |
| AMD (Linux) | ROCm (requires manual driver setup) | ~10–20× faster than CPU |
| Intel integrated graphics | Not supported by Ollama | CPU fallback |
| No GPU | CPU | baseline |

On Apple Silicon Macs, GPU acceleration is active from the first run — Ollama uses Metal automatically. On Linux with an NVIDIA card, install the CUDA drivers and Ollama picks them up without any extra steps.

**Practical impact:** embedding 100 files on an M2 Mac takes ~8 seconds. On a 2020 Intel MacBook Pro (no discrete GPU), the same task takes ~60–90 seconds.

### What runs locally

- **Ollama + nomic-embed-text**: uses GPU when available, CPU otherwise. Incremental — only re-embeds files that changed.
- **ChromaDB**: embedded (no server). Memory usage scales with corpus size — 100 files uses ~50 MB.
- **Claude Code**: API calls go to Anthropic. This requires internet.

### Known limitations

| Limitation | Impact | Workaround |
|---|---|---|
| nomic-embed-text context window ~2048 tokens | Files > 4000 chars are truncated before embedding | First 4000 chars carry the highest-signal content (frontmatter + intro) |
| ChromaDB persistent client requires Python 3.8+ | Python 3.7 not supported | Use 3.9+ |
| Ollama must be running for semantic search | If Ollama is stopped, retrieval falls back to tag-only matching | Tag fallback works well for most queries |
| Windows native (no WSL2) | The PostToolUse hook uses bash | Use WSL2 |
| Skills are text files, not code | Skills guide Claude's behaviour; they don't execute | Intentional — keeps the system auditable |

### What this project cannot do (yet)

- **Contradiction detection**: MARVIN does not notice when two knowledge files disagree with each other.
- **Staleness detection**: Files do not expire automatically. You are responsible for keeping knowledge current.
- **Cross-session learning**: Claude does not write new knowledge autonomously — only when you ask it to.
- **GPU acceleration for embeddings**: Nomic runs on CPU only via Ollama. For large corpora (1000+ files), a GPU would meaningfully speed up initial indexing.

---

## Adding Your Own Skills

Every skill is a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: my-skill
description: One-line description of what this skill does
tags: [domain:my-domain, intent:my-intent, type:skill]
---

# My Skill

Instructions for Claude here...
```

Drop it in `~/.agents/skills/my-skill/SKILL.md`. The PostToolUse hook will pick it up automatically on the next file save.

To wire a skill to a slash command, add an entry to `~/.claude/CLAUDE.md`'s routing table.

---

## Adding Knowledge Files

Knowledge files are Markdown files in `~/.claude/projects/*/memory/`:

```markdown
---
name: my-knowledge
description: What this file contains
tags: [domain:my-domain, intent:learn, type:knowledge]
---

# My Knowledge

Your content here...
```

The hook rebuilds the manifest and re-embeds on every save.

---

## AI Disclosure

This project was built collaboratively with Claude (claude-sonnet-4-6 via Claude Code).

**Where AI was used:**

| Component | AI involvement |
|---|---|
| Skill SKILL.md files | Authored by AI, reviewed and refined by human |
| `rebuild-manifest.py` | Designed and written by AI |
| `rebuild-embeddings.py` | Designed and written by AI |
| `retrieve.py` | Designed and written by AI |
| `setup.sh` | Written by AI based on human-specified platform requirements |
| `README.md` | Written by AI |
| `CLAUDE.md` | Collaboratively authored (human goals, AI structure) |
| `lexicon.md` | Accumulated over multiple sessions; terms defined by human, formatted by AI |
| Architecture decisions | Grilled and validated by human (BM25+embeddings hybrid, ChromaDB collections, dynamic threshold) |

**What the human contributed:**

- The core concept (male-brain boxes / selective context loading)
- All architectural decisions (frontmatter as source of truth, namespaced tags, ChromaDB over flat JSON for scale, local model over API)
- Platform requirements and testing
- The name

**Transparency note:** AI-generated code has been tested on macOS ARM. Cross-platform behaviour on Linux and WSL2 has not been tested end-to-end. If you find a bug, open an issue — the fix will likely be a small PR.

---

## Contributing

PRs welcome, especially:
- Linux / WSL2 testing and bug reports
- New skills (drop a `SKILL.md` + PR)
- Staleness detection design
- Contradiction detection design
- Windows native support (PowerShell setup script)

---

## License

MIT. See `LICENSE`.

---

*MARVIN: "I could calculate your chances of survival, but you won't like it."*
*You: "Just load the relevant context."*
*MARVIN: "Done."*
