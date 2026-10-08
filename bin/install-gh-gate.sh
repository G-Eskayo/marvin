#!/bin/bash
# Put the GitHub gate (~/.agents/bin/gh) in front of the real gh on this Mac. Idempotent; run on each Mac.
#   1. MARVIN's Python (the venv): a startup line puts ~/.agents/bin first on PATH for every script and its children
#   2. zsh (~/.zshenv and the end of ~/.zshrc): terminals, Claude sessions, and the dashboard (it adopts the login shell's PATH)
# The dashboard app and its webhook server also put it first themselves (dashboard/electron/main/path.js useGhGate),
# and lib/project_catalog.run_env() does for the jobs that use it.
# Undo: rm the marvin_gh_gate.pth printed below; delete the marked line from ~/.zshenv and ~/.zshrc.
set -euo pipefail
GATE_DIR="$HOME/.agents/bin"
chmod +x "$GATE_DIR/gh"
SITE=$("$HOME/.agents/venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')
PTH="$SITE/marvin_gh_gate.pth"
# one line, no comprehension or lambda: .pth lines run with separate globals/locals, so Python 3.11 can't see a name
# defined earlier on the line from inside one (NameError on every startup, found on the mini 2026-10-08)
echo "import os; os.environ['PATH'] = os.path.expanduser('~/.agents/bin') + ':' + ':'.join(x for x in os.environ.get('PATH', '').split(':') if x and x != os.path.expanduser('~/.agents/bin'))" > "$PTH"
chflags nohidden "$PTH" 2>/dev/null || true   # a hidden .pth is silently skipped (uv_hidden_pth_gotcha)
echo "venv hook: $PTH"
LINE='export PATH="$HOME/.agents/bin:$PATH"  # MARVIN GitHub gate (bin/install-gh-gate.sh)'
# .zshenv for non-interactive zsh; the END of .zshrc too, because .zshrc runs later and puts Homebrew back in front
for f in "$HOME/.zshenv" "$HOME/.zshrc"; do
  grep -qF 'MARVIN GitHub gate' "$f" 2>/dev/null || echo "$LINE" >> "$f"
done
"$HOME/.agents/venv/bin/python" -c 'import shutil; print("venv python finds:", shutil.which("gh"))'
/bin/zsh -ilc 'echo "zsh finds: $(command -v gh)"' 2>/dev/null
