#!/bin/bash
# run-check.sh <id> — run one of this repo's required checks (marvin#826).
#
# The one runner GitHub CI and MARVIN's merge gate both call, so "passes CI" and "passes the gate" mean the same
# thing. The checks are listed in .github/required-checks.json (format: lib/required_checks.py in G-Eskayo/marvin);
# this script is identical in every project repo. Needs bash and jq (both on GitHub's runners and on macOS 15+).
#
# Exit codes: the check's own, or 2 when the id is unknown or the check is CI-only.
set -euo pipefail

top=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
list="$top/.github/required-checks.json"
id=${1:-}
[ -n "$id" ] || { echo "usage: .github/run-check.sh <check id>  (ids: $(jq -r '[.checks[].id]|join(", ")' "$list"))" >&2; exit 2; }

check=$(jq -c --arg id "$id" '.checks[] | select(.id == $id)' "$list")
[ -n "$check" ] || { echo "run-check: no check '$id' in .github/required-checks.json" >&2; exit 2; }
if [ "$(jq -r '.where // "both"' <<<"$check")" = ci ]; then
  echo "run-check: '$id' runs in CI only (its own job in .github/workflows/ci.yml)" >&2
  exit 2
fi

cd "$top/$(jq -r '.cwd // "."' <<<"$check")"
cmd=$(jq -r '.command | @sh' <<<"$check")
echo "run-check: $id: $(jq -r '.command | join(" ")' <<<"$check")"
eval "exec $cmd"
