#!/bin/bash
# run-check.sh <id> [--affected] — run one of this repo's required checks (marvin#826).
#
# The one runner GitHub CI and MARVIN's merge gate both call, so "passes CI" and "passes the gate" mean the same
# thing. The checks are listed in .github/required-checks.json (format: lib/required_checks.py in G-Eskayo/marvin);
# this script is identical in every project repo. Needs bash, git and jq (all on GitHub's runners and on macOS 15+).
#
# With $MARVIN_BASE set (a PR: the base it is tested against), a check with "paths" runs only when a path changed
# since the branch left that base matches one of them (bash globs, where * crosses /), and passes as "not affected"
# otherwise. A change under .github/ affects every check. Without $MARVIN_BASE (main after a merge) every check
# runs. --affected prints true or false instead of running, for a CI job to skip its own setup.
#
# Exit codes: the check's own, or 2 when the id is unknown or the check is CI-only.
set -euo pipefail

top=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
list="$top/.github/required-checks.json"
id=${1:-}
[ -n "$id" ] || { echo "usage: .github/run-check.sh <check id> [--affected]  (ids: $(jq -r '[.checks[].id]|join(", ")' "$list"))" >&2; exit 2; }

check=$(jq -c --arg id "$id" '.checks[] | select(.id == $id)' "$list")
[ -n "$check" ] || { echo "run-check: no check '$id' in .github/required-checks.json" >&2; exit 2; }

affected=true
base=${MARVIN_BASE:-}
if [ -n "$base" ] && [ "$(jq -r 'has("paths")' <<<"$check")" = true ]; then
  if changed=$(git -C "$top" diff --name-only "$base...HEAD" 2>/dev/null); then
    affected=false
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      [[ $f == .github/* ]] && { affected=true; break; }
      while IFS= read -r pat; do
        # shellcheck disable=SC2053  # the pattern is a glob on purpose
        [[ $f == $pat ]] && { affected=true; break 2; }
      done < <(jq -r '.paths[]' <<<"$check")
    done <<<"$changed"
  else
    echo "run-check: cannot tell what changed since $base; running $id" >&2
  fi
fi

if [ "${2:-}" = --affected ]; then
  echo "$affected"
  exit 0
fi
if [ "$(jq -r '.where // "both"' <<<"$check")" = ci ]; then
  echo "run-check: '$id' runs in CI only (its own job in .github/workflows/ci.yml)" >&2
  exit 2
fi
if [ "$affected" = false ]; then
  echo "run-check: $id: not affected by this change (nothing it covers changed since $base): no tests ran"
  exit 0
fi

cd "$top/$(jq -r '.cwd // "."' <<<"$check")"
cmd=$(jq -r '.command | @sh' <<<"$check")
echo "run-check: $id: $(jq -r '.command | join(" ")' <<<"$check")"
eval "exec $cmd"
