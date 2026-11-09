#!/bin/bash
# Runs INSIDE a throwaway marvin-test VM (build-builder-image.sh, marvin #950) and turns it into the marvin-build image:
# what a ticket build needs, and no credentials. Every version is pinned here; change one and rebuild the image.
# Claude Code is pinned to the Macs' version, so a box build behaves like a Mac build.
set -euo pipefail
CLAUDE_VERSION=2.1.314
NODE_VERSION=v24.21.0   # the box's own Node
NPM_VERSION=12.0.2      # the box's npm (npm 12 runs only allow-listed install scripts, dashboard/package.json)
REPO_URL=https://github.com/G-Eskayo/marvin.git   # public: cloned without a credential
here="$(cd "$(dirname "$0")" && pwd)"
step() { printf '\n== %s\n' "$*"; }
export DEBIAN_FRONTEND=noninteractive PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

step "apt: git, rg, gh, build tools (Debian's older Node goes)"
sudo apt-get update -q
sudo apt-get purge -y -q nodejs npm >/dev/null 2>&1 || true
sudo apt-get install -y -q --no-install-recommends git curl ca-certificates rsync jq build-essential xz-utils ripgrep gh
sudo apt-get autoremove -y -q

step "Node $NODE_VERSION (nodejs.org build, checksum-verified), npm $NPM_VERSION, corepack + pnpm"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
tarball="node-$NODE_VERSION-linux-x64.tar.xz"
curl -fsSL -o "$tmp/SHASUMS256.txt" "https://nodejs.org/dist/$NODE_VERSION/SHASUMS256.txt"
curl -fsSL -o "$tmp/$tarball" "https://nodejs.org/dist/$NODE_VERSION/$tarball"
(cd "$tmp" && grep " $tarball\$" SHASUMS256.txt | sha256sum -c -)
sudo tar -xJf "$tmp/$tarball" -C /usr/local --strip-components=1 --no-same-owner
sudo /usr/local/bin/npm install -g --no-fund --no-audit -q "npm@$NPM_VERSION"
sudo /usr/local/bin/corepack enable
COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm --version   # fetches pnpm once, into the image's corepack cache

step "Claude Code $CLAUDE_VERSION"
curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_VERSION"
claude --version | grep -q "^$CLAUDE_VERSION " || { echo "claude is not $CLAUDE_VERSION" >&2; exit 1; }

step "MARVIN engine + venv (Python 3.11, CPU torch)"
rm -rf "$HOME/.agents"
git clone -q "$REPO_URL" "$HOME/.agents"
uv venv -q --python 3.11 "$HOME/.agents/venv"
uv pip install -q --python "$HOME/.agents/venv/bin/python" --index-strategy unsafe-best-match \
  --extra-index-url https://download.pytorch.org/whl/cpu -r "$here/requirements.txt"
"$HOME/.agents/venv/bin/python" -c "import pytest, xdist, pytest_timeout, torch; print('venv ok, torch', torch.__version__)"

step "Tidy: caches that only make the image bigger"
rm -rf "$HOME/.cache/uv" "$HOME/.npm/_cacache"
sudo apt-get clean

step "No credentials in the image (ADR 0069: the push credential and the login are handed in per run)"
bad=0
for f in "$HOME/.claude/.credentials.json" "$HOME/.claude/.oauth-token" "$HOME/.claude/.gh-token" \
         "$HOME/.claude/.marvin-bot-token" "$HOME/.claude/.anthropic-api-key" "$HOME/.config/gh/hosts.yml" \
         "$HOME/.git-credentials" "$HOME/.netrc"; do
  if [ -e "$f" ]; then echo "credential file in the image: $f" >&2; bad=1; fi
done
if [ -f "$HOME/.claude.json" ] && grep -Eq '"(primaryApiKey|oauthAccount)"' "$HOME/.claude.json"; then
  echo "a login in ~/.claude.json" >&2; bad=1
fi
if git -C "$HOME/.agents" config --get-regexp '^(credential|http\..*extraheader)' >/dev/null; then
  echo "a git credential setting in the clone" >&2; bad=1
fi
[ "$bad" = 0 ] || exit 1

step "Versions"
printf 'python %s\nnode %s\nnpm %s\npnpm %s\ngit %s\nrg %s\ngh %s\nclaude %s\n' \
  "$("$HOME/.agents/venv/bin/python" -V 2>&1 | cut -d' ' -f2)" "$(node -v)" "$(npm -v)" "$(pnpm -v)" \
  "$(git --version | cut -d' ' -f3)" "$(rg --version | head -1 | cut -d' ' -f2)" "$(gh --version | head -1 | cut -d' ' -f3)" \
  "$(claude --version | cut -d' ' -f1)" | tee "$HOME/.marvin-build-versions"
