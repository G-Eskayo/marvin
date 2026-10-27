#!/usr/bin/env bash
# =============================================================
# MARVIN — Setup Script
# Transforms Claude Code into a persistent AI partner.
# Supports: macOS ARM (M1/M2/M3/M4), macOS x86 (Intel),
#           Linux (x86_64/ARM), Windows via WSL2
# =============================================================
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

# ── Paths ─────────────────────────────────────────────────────
MARVIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$HOME/.agents"
SKILLS_DIR="$AGENTS_DIR/skills"
VENV_DIR="$AGENTS_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"
CLAUDE_DIR="$HOME/.claude"
SCRIPTS_DIR="$SKILLS_DIR/self-improve/scripts"

log()  { echo -e "${GREEN}✓${NC}  $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
info() { echo -e "${BLUE}→${NC}  $1"; }
err()  { echo -e "${RED}✗  ERROR:${NC} $1"; exit 1; }

# =============================================================
# 1. OS DETECTION
# =============================================================
detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        ARCH=$(uname -m)
        [[ "$ARCH" == "arm64" ]] && OS="macos-arm" || OS="macos-x86"
    elif [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "linux"* ]]; then
        OS="linux"
        # Detect WSL
        if grep -qi microsoft /proc/version 2>/dev/null; then
            OS="wsl2"
        fi
    else
        err "Unsupported OS: $OSTYPE\nWindows users: run this script inside WSL2."
    fi
    log "Platform: $OS ($(uname -m))"
}

# =============================================================
# 2. HOMEBREW (macOS only)
# =============================================================
ensure_homebrew() {
    [[ "$OS" == "linux" || "$OS" == "wsl2" ]] && return
    if ! command -v brew &>/dev/null; then
        info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add brew to PATH for Apple Silicon
        if [[ "$OS" == "macos-arm" ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
    else
        log "Homebrew: $(brew --version | head -1)"
    fi
}

# =============================================================
# 3. GPU DETECTION (informational — Ollama handles this automatically)
# =============================================================
detect_gpu() {
    local gpu_info="CPU (no GPU detected)"

    case "$OS" in
        macos-arm)
            gpu_info="Apple Silicon Metal + Neural Engine (automatic)"
            ;;
        macos-x86)
            if system_profiler SPDisplaysDataType 2>/dev/null | grep -qi "amd\|radeon\|nvidia"; then
                gpu_info="Discrete GPU detected — Ollama will use Metal if supported"
            else
                gpu_info="Intel integrated graphics (CPU fallback)"
            fi
            ;;
        linux|wsl2)
            if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
                local gpu_name
                gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
                gpu_info="NVIDIA: $gpu_name — CUDA acceleration automatic"
            elif command -v rocminfo &>/dev/null; then
                gpu_info="AMD GPU with ROCm — acceleration automatic"
            fi
            ;;
    esac

    log "GPU: $gpu_info"
}

# =============================================================
# 3. OLLAMA
# =============================================================
install_ollama() {
    if command -v ollama &>/dev/null; then
        log "Ollama already installed"
        return
    fi
    info "Installing Ollama..."
    case "$OS" in
        macos-arm|macos-x86)
            brew install ollama
            ;;
        linux|wsl2)
            curl -fsSL https://ollama.com/install.sh | sh
            ;;
    esac
    log "Ollama installed"
}

start_ollama() {
    info "Starting Ollama service..."
    case "$OS" in
        macos-arm|macos-x86)
            brew services start ollama 2>/dev/null || true
            sleep 3
            ;;
        linux)
            if command -v systemctl &>/dev/null && systemctl is-system-running &>/dev/null; then
                sudo systemctl enable --now ollama 2>/dev/null || true
            else
                ollama serve &>/dev/null & disown
                sleep 3
            fi
            ;;
        wsl2)
            # WSL2 typically lacks systemd — run directly
            ollama serve &>/dev/null & disown
            sleep 3
            ;;
    esac

    # Verify reachable
    if curl -sf http://localhost:11434/ &>/dev/null; then
        log "Ollama running"
    else
        warn "Ollama may not be running. Pull model manually: ollama pull nomic-embed-text"
    fi
}

pull_model() {
    info "Pulling nomic-embed-text (~274 MB)..."
    if ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
        log "nomic-embed-text already pulled"
    else
        ollama pull nomic-embed-text
        log "nomic-embed-text ready"
    fi
}

# =============================================================
# 4. PYTHON — find compatible version (3.9–3.12)
# =============================================================
find_python() {
    # Try candidates newest-compatible first
    local candidates=(python3.12 python3.11 python3.10 python3.9)

    # macOS: also check CommandLineTools path
    if [[ "$OS" == "macos-arm" || "$OS" == "macos-x86" ]]; then
        candidates+=(
            /opt/homebrew/bin/python3.12
            /opt/homebrew/bin/python3.11
            /opt/homebrew/bin/python3.10
            /Library/Developer/CommandLineTools/usr/bin/python3.9
        )
    fi

    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" &>/dev/null || [[ -f "$candidate" ]]; then
            local bin
            bin=$(command -v "$candidate" 2>/dev/null || echo "$candidate")
            # Sanity check: can it run pip and core modules?
            if "$bin" -c "import hashlib, json, subprocess, venv" &>/dev/null; then
                PYTHON_BIN="$bin"
                local ver
                ver=$("$PYTHON_BIN" --version 2>&1)
                log "Python: $ver ($PYTHON_BIN)"
                return
            fi
        fi
    done

    err "No compatible Python found (3.9–3.12 required).\n\
macOS:   brew install python@3.11\n\
Ubuntu:  sudo apt install python3.11 python3.11-venv\n\
Fedora:  sudo dnf install python3.11"
}

# =============================================================
# 5. VIRTUAL ENVIRONMENT
# =============================================================
setup_venv() {
    if [[ -d "$VENV_DIR" ]] && [[ -f "$VENV_PYTHON" ]]; then
        log "Virtualenv exists: $VENV_DIR"
        return
    fi
    info "Creating virtualenv at $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    log "Virtualenv created"
}

install_deps() {
    info "Installing Python dependencies..."
    "$VENV_PYTHON" -m pip install --upgrade pip --quiet
    "$VENV_PYTHON" -m pip install chromadb rank_bm25 requests --quiet
    log "chromadb, rank_bm25, requests installed"

    # The test harness: a hung test fails in 2 min by name (pytest.ini `timeout`), and the suite can run in parallel.
    # lib/tests/test_test_harness.py fails on a machine without them, so the merge gate never silently loses its limit.
    "$VENV_PYTHON" -m pip install pytest pytest-timeout pytest-xdist --quiet
    log "pytest, pytest-timeout, pytest-xdist installed (test harness)"

    # resume-tailor's deps — this was missing entirely until a fresh-machine
    # setup was actually attempted and it silently left the skill non-functional.
    if [[ "$OS" == "macos-arm" || "$OS" == "macos-x86" ]]; then
        if ! brew list pango &>/dev/null; then
            info "Installing Pango (WeasyPrint's PDF rendering dependency)..."
            brew install pango
        fi
    fi
    "$VENV_PYTHON" -m pip install weasyprint markdown-it-py pdfminer.six python-docx beautifulsoup4 --quiet
    log "weasyprint, markdown-it-py, pdfminer.six, python-docx, beautifulsoup4 installed (resume-tailor)"
}

# resume-tailor is its own repo, gitignored from marvin's — a plain clone of
# marvin never brings it along, so install_skills() below would silently
# skip it (nothing to copy from $MARVIN_DIR/skills/resume-tailor).
clone_resume_tailor() {
    local dest="$SKILLS_DIR/resume-tailor"
    if [[ -d "$dest" ]]; then
        log "resume-tailor already present — skipping clone"
        return
    fi
    info "Cloning resume-tailor..."
    git clone --quiet https://github.com/G-Eskayo/resume-tailor.git "$dest"
    log "resume-tailor cloned to $dest"
    warn "Master resume is personal and never lives in git — create ~/.claude/resume/master.md yourself (see resume-tailor's README)"
}

# =============================================================
# 6. SKILLS
# =============================================================
install_skills() {
    info "Installing skills to $SKILLS_DIR..."
    mkdir -p "$SKILLS_DIR"

    local installed=0 skipped=0

    for skill_dir in "$MARVIN_DIR/skills"/*/; do
        local name dest
        name=$(basename "$skill_dir")
        dest="$SKILLS_DIR/$name"

        if [[ -d "$dest" ]]; then
            warn "Skill '$name' already exists — skipping"
            ((skipped++)) || true
        else
            cp -r "$skill_dir" "$dest"
            ((installed++)) || true
        fi
    done

    log "Skills: $installed installed, $skipped already present"
}

# brain-map/ lives at the top level of this repo, not under skills/, so
# install_skills() above never copies it — found by actually running this
# script on a second machine: install.sh assumed ~/.agents/brain-map already
# existed and failed with "No such file or directory".
deploy_brain_map() {
    local dest="$AGENTS_DIR/brain-map"
    if [[ -d "$dest" ]]; then
        log "brain-map already present at $dest — skipping"
        return
    fi
    info "Deploying brain-map to $dest..."
    cp -r "$MARVIN_DIR/brain-map" "$dest"
    chmod +x "$dest/install.sh"
    log "brain-map deployed — run bash $dest/install.sh to compile and install it (macOS only)"
}

# retrospective-log.md is the same story as brain-map — a top-level file
# install_skills() never touches. It's also load-bearing now: the
# background reviewer hook (self-improve/scripts/background_review.py)
# appends to it after every handoff, and since it's git-tracked, a
# push+pull between machines merges each one's learned patterns into the
# same shared file — the cheapest real cross-machine context sharing
# available, so it's worth not silently skipping.
#
# Symlink, not copy, when $MARVIN_DIR != $AGENTS_DIR (i.e. this clone isn't
# ~/.agents itself, the deployed-copy case). A plain copy here was found
# live on a second machine to silently defeat both the cross-machine
# sharing above AND the integrity checker (verify_retrospective_integrity.py
# needs an actual git-tracked file, not a detached copy sitting outside any
# repo) — the reviewer would keep appending to a file that never made it
# back into git at all.
deploy_retrospective_log() {
    # ADR 0071: the log is learned from this person's sessions, so it lives in their private instance, never the
    # public engine. Created empty with its header; installer --new / --join (ADR 0071 step 3) make it a repo.
    local dest="$AGENTS_DIR/instance/retrospective-log.md"
    if [[ -f "$dest" ]]; then
        log "retrospective-log.md already present in the instance — skipping"
        return
    fi
    mkdir -p "$AGENTS_DIR/instance"
    printf '%s\n' "# Retrospective Log" "" \
        "Cross-skill pattern index. One line per self-improve run. Written by the self-improve skill." "" \
        "| Date | Skill | Type | Summary |" "|------|-------|------|---------|" > "$dest"
    log "Created $dest"
}

# =============================================================
# 7. CLAUDE CONFIGURATION
# =============================================================
configure_claude() {
    mkdir -p "$CLAUDE_DIR"

    # CLAUDE.md
    if [[ -f "$CLAUDE_DIR/CLAUDE.md" ]]; then
        warn "~/.claude/CLAUDE.md exists — not overwriting"
        warn "Review diff: diff ~/.claude/CLAUDE.md $MARVIN_DIR/claude-config/CLAUDE.md"
    else
        cp "$MARVIN_DIR/claude-config/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
        log "Installed CLAUDE.md"
    fi

    # lexicon.md
    if [[ -f "$CLAUDE_DIR/lexicon.md" ]]; then
        warn "~/.claude/lexicon.md exists — not overwriting"
    else
        cp "$MARVIN_DIR/claude-config/lexicon.md" "$CLAUDE_DIR/lexicon.md"
        log "Installed lexicon.md"
    fi

    # PostToolUse hook in settings.local.json
    configure_hook
}

configure_hook() {
    local settings="$CLAUDE_DIR/settings.local.json"
    local template="$MARVIN_DIR/claude-config/settings.template.json"
    # Count from the template itself rather than hardcoding a number here —
    # a hardcoded "4" already went stale once (found 2026-07-02) when a 5th
    # hook was added and this string wasn't updated.
    local hook_count
    hook_count=$(grep -c '"command"' "$template")

    if [[ -f "$settings" ]]; then
        warn "settings.local.json exists — add these $hook_count PostToolUse hooks manually if needed:"
        warn "  $VENV_PYTHON $SKILLS_DIR/self-improve/scripts/rebuild-manifest.py"
        warn "  $VENV_PYTHON $SKILLS_DIR/handoff/scripts/emit-resume-prompt.py"
        warn "  $VENV_PYTHON $SKILLS_DIR/qa-agent/scripts/qa_session_capture.py"
        warn "  $VENV_PYTHON $SKILLS_DIR/improve/scripts/improvement_sweep.py"
        warn "  $VENV_PYTHON $SKILLS_DIR/self-improve/scripts/background_review.py"
        warn "  $VENV_PYTHON $AGENTS_DIR/brain-map/scripts/skill_activity.py  (matcher: Skill, not Write|Edit)"
        warn "  See: $template"
    else
        sed "s|{{VENV_PYTHON}}|$VENV_PYTHON|g; s|{{SKILLS_DIR}}|$SKILLS_DIR|g; s|{{AGENTS_DIR}}|$AGENTS_DIR|g" \
            "$template" > "$settings"
        log "Installed settings.local.json with all $hook_count PostToolUse hooks"
    fi
}

# =============================================================
# 7b. PUSH GUARD (ADR 0071)
# =============================================================
# Refuses any push whose new commits add a secret, a session transcript, or one of this
# person's own strings. The engine repo is public; on 2026-10-25 auto-sync pushed a 2 MB
# transcript to it, and a phone number had been public since July. Linked, not copied, so
# a guard fix reaches every clone on the next pull. code_sync.py calls the same script.
install_push_guard() {
    local private="$CLAUDE_DIR/private-push-patterns.txt"
    if [[ ! -f "$private" ]]; then
        mkdir -p "$CLAUDE_DIR"
        ( umask 077; cat > "$private" <<'PATTERNS'
# Your own strings the push guard must never let reach a public repo: one extended regex per line.
# Examples: your phone number, home address, a client's name. Private: never copy this file into a repo.
# Secrets and transcripts are already covered by the shared list (config/push-guard/patterns.txt).
PATTERNS
        )
        log "Created $private (add your phone, address, anything personal)"
    fi
    chmod 600 "$private"

    local git_dir hook
    git_dir=$(git -C "$MARVIN_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || {
        warn "$MARVIN_DIR is not a git clone: push guard not installed"; return; }
    hook="$git_dir/hooks/pre-push"
    mkdir -p "$git_dir/hooks"
    if [[ -e "$hook" && ! -L "$hook" ]] && ! grep -q 'pre-push-guard' "$hook"; then
        warn "A different pre-push hook already exists at $hook; left it alone."
        warn "  Call $MARVIN_DIR/bin/pre-push-guard from it, or the guard won't run on git push."
        return
    fi
    chmod +x "$MARVIN_DIR/bin/pre-push-guard"
    ln -sfn "$MARVIN_DIR/bin/pre-push-guard" "$hook"
    log "Push guard installed: $hook"
}

# Keeps the graphify code graph current however commits land (marvin#691): post-commit, post-merge (code_sync pulls
# with git merge), post-rewrite. Only matters where the graph has been built; idempotent.
install_graphify_hooks() {
    [[ -d "$MARVIN_DIR/graphify-out" ]] || { info "No graphify-out yet: graph freshness hooks skipped"; return; }
    "$VENV_PYTHON" "$MARVIN_DIR/lib/graphify_freshness.py" install-hooks "$MARVIN_DIR" \
        && log "Graph freshness hooks installed" || warn "Graph freshness hooks not installed"
}

# =============================================================
# 8. INITIAL MANIFEST + EMBEDDINGS
# =============================================================
initial_setup() {
    info "Tagging skill files..."
    "$VENV_PYTHON" "$SCRIPTS_DIR/tag-files.py"

    info "Building manifest..."
    # Run manifest only (not the full chain — embeddings handled separately)
    "$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '$SCRIPTS_DIR')
import subprocess, sys
subprocess.run([sys.executable, '$SCRIPTS_DIR/rebuild-manifest.py'], check=False)
" 2>/dev/null || "$VENV_PYTHON" "$SCRIPTS_DIR/rebuild-manifest.py"

    log "Manifest built"
}

build_embeddings() {
    info "Building initial embeddings (this may take a minute)..."
    if curl -sf http://localhost:11434/ &>/dev/null; then
        "$VENV_PYTHON" "$SCRIPTS_DIR/rebuild-embeddings.py"
        log "Embeddings built"
    else
        warn "Ollama not reachable — skipping initial embeddings"
        warn "Run manually after starting Ollama: $VENV_PYTHON $SCRIPTS_DIR/rebuild-embeddings.py"
    fi
}

# =============================================================
# BANNER
# =============================================================
print_banner() {
    echo ""
    echo -e "${BOLD}  ███╗   ███╗ █████╗ ██████╗ ██╗   ██╗██╗███╗   ██╗${NC}"
    echo -e "${BOLD}  ████╗ ████║██╔══██╗██╔══██╗██║   ██║██║████╗  ██║${NC}"
    echo -e "${BOLD}  ██╔████╔██║███████║██████╔╝██║   ██║██║██╔██╗ ██║${NC}"
    echo -e "${BOLD}  ██║╚██╔╝██║██╔══██║██╔══██╗╚██╗ ██╔╝██║██║╚██╗██║${NC}"
    echo -e "${BOLD}  ██║ ╚═╝ ██║██║  ██║██║  ██║ ╚████╔╝ ██║██║ ╚████║${NC}"
    echo -e "${BOLD}  ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚═╝  ╚═══╝${NC}"
    echo ""
    echo -e "  Your AI partner, configured from scratch."
    echo ""
}

print_summary() {
    local skill_count
    skill_count=$(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d -exec test -e "{}/SKILL.md" \; -print 2>/dev/null | wc -l | tr -d ' ')

    echo ""
    echo -e "${GREEN}${BOLD}  Setup complete.${NC}"
    echo ""
    echo -e "  What was installed:"
    echo -e "  ${BLUE}~/.agents/skills/${NC}     — $skill_count AI skills"
    echo -e "  ${BLUE}~/.agents/venv/${NC}        — Python virtualenv"
    echo -e "  ${BLUE}~/.claude/CLAUDE.md${NC}    — Global Claude instructions"
    echo -e "  ${BLUE}~/.claude/lexicon.md${NC}   — Shared vocabulary"
    echo -e "  ${BLUE}~/.claude/manifest.json${NC} — Skill/knowledge index"
    echo -e "  ${BLUE}~/.claude/chroma/${NC}       — Semantic embeddings"
    echo ""
    echo -e "  ${YELLOW}Next step:${NC} Open Claude Code and start a new session."
    echo -e "  MARVIN will load your context automatically."
    echo ""
}

# =============================================================
# MAIN
# =============================================================
main() {
    print_banner

    detect_os
    detect_gpu
    ensure_homebrew
    install_ollama
    find_python
    setup_venv
    install_deps
    install_skills
    clone_resume_tailor
    deploy_brain_map
    deploy_retrospective_log
    configure_claude
    install_push_guard
    install_graphify_hooks
    initial_setup
    start_ollama
    pull_model
    build_embeddings

    print_summary
}

# Sourcing (tests) defines the functions without installing anything.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
