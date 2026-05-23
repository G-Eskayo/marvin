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
MARVIN_DIR="$(cd "$(dirname "$0")" && pwd)"
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
    local hook_cmd="$VENV_PYTHON $SCRIPTS_DIR/rebuild-manifest.py"

    if [[ -f "$settings" ]]; then
        warn "settings.local.json exists — add the hook manually if needed:"
        warn "  Hook command: $hook_cmd"
        warn "  See: $MARVIN_DIR/claude-config/settings.template.json"
    else
        sed "s|{{VENV_PYTHON}}|$VENV_PYTHON|g; s|{{SCRIPTS_DIR}}|$SCRIPTS_DIR|g" \
            "$MARVIN_DIR/claude-config/settings.template.json" > "$settings"
        log "Installed settings.local.json with PostToolUse hook"
    fi
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
    echo ""
    echo -e "${GREEN}${BOLD}  Setup complete.${NC}"
    echo ""
    echo -e "  What was installed:"
    echo -e "  ${BLUE}~/.agents/skills/${NC}     — 20 AI skills"
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
    ensure_homebrew
    install_ollama
    find_python
    setup_venv
    install_deps
    install_skills
    configure_claude
    initial_setup
    start_ollama
    pull_model
    build_embeddings

    print_summary
}

main "$@"
