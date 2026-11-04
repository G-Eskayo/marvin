#!/bin/bash
# secret-scan.sh — the secret and transcript scan (ADR 0071), run by GitHub CI and by MARVIN's merge gate alike through
# `.github/run-check.sh secret-scan` (marvin#1101), so no merge waits on GitHub for it.
#
# Scans only the commits this change adds: $MARVIN_BASE..HEAD (CI: the PR's base, or the push's "before"; unset: the
# branch point from origin/main, or the root commit). Two passes, both must pass:
#   1. gitleaks with .gitleaks.toml: ./gitleaks (CI's checksum-pinned install) or the one on PATH
#   2. bin/pre-push-guard, with the shared patterns and an empty private-pattern file (personal patterns never leave
#      their owner's Mac; every clone runs them locally before it pushes)
# Exit codes: 0 clean; 1 a finding (or a scan that couldn't run); 3 gitleaks missing (a merge Mac without it refuses
# through the check's "requires", it never passes blind).
set -uo pipefail
top=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$top" || exit 1
gitleaks="./gitleaks"
[ -x "$gitleaks" ] || gitleaks=$(command -v gitleaks || true)
if [ -z "$gitleaks" ]; then
  echo "secret-scan: gitleaks isn't installed here; refusing to report clean without it" >&2
  exit 3
fi
base=${MARVIN_BASE:-}
if [ -n "$base" ] && ! git cat-file -e "$base^{commit}" 2>/dev/null; then
  echo "secret-scan: base $base isn't in this checkout; scanning from the branch point instead" >&2
  base=""
fi
[ -n "$base" ] || base=$(git merge-base origin/main HEAD 2>/dev/null || true)
[ -n "$base" ] || base=$(git rev-list --max-parents=0 HEAD | tail -1)
echo "secret-scan: commits $(git rev-parse --short "$base")..$(git rev-parse --short HEAD)"
"$gitleaks" git --no-banner --redact --config .gitleaks.toml --log-opts="$base..HEAD" . || exit 1
home=$(mktemp -d) || exit 1
trap 'rm -rf "$home"' EXIT
mkdir -p "$home/.claude" && touch "$home/.claude/private-push-patterns.txt"
echo "refs/heads/scan $(git rev-parse HEAD) refs/heads/scan $(git rev-parse "$base")" | HOME="$home" bin/pre-push-guard origin || exit 1
echo "secret-scan: clean"
