#!/bin/bash
# mac-mini-2012 shows the M4 Mini's view instead of re-checking every machine itself (ADR 0069): copy the Mini's
# health-status.json (it already covers all three machines) and github-feed.json (open PRs and boards, marvin#954: the
# box holds no GitHub credential) to where the dashboard reads them. Uses the observer key (read-only allow-list).
# Each file is replaced only by valid JSON, atomically; one failing copy never stops the other, and a failed copy
# leaves the last good one in place (its age is what the dashboard shows).
set -uo pipefail
py="$HOME/.agents/venv/bin/python"
# The primary Mac's Tailscale hostname comes from the synced machine registry, so no machine is named here.
host="${MARVIN_OBSERVER_HOST:-$(cd "$HOME/.agents" && "$py" -c 'import sys; sys.path.insert(0, "lib"); import scanner_role; print(scanner_role._primary_device()[1]["tailscale_hostname"])' 2>/dev/null)}"
[ -n "$host" ] || { echo "$(date -Is) no primary Mac in the machine registry; nothing copied" >&2; exit 1; }
rc=0
copy() { # $1 = file name under ~/.claude/logs on both machines
  local dest="$HOME/.claude/logs/$1" tmp
  tmp="$(mktemp "$dest.XXXXXX")" || return 1
  if ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" "cat ~/.claude/logs/$1" > "$tmp" \
     && "$py" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert isinstance(d, dict)' "$tmp" 2>/dev/null; then
    chmod 600 "$tmp" && mv "$tmp" "$dest"
  else
    rm -f "$tmp"; echo "$(date -Is) could not copy $1 from $host; keeping the last good copy" >&2; return 1
  fi
}
copy health-status.json || rc=1
copy github-feed.json || rc=1
exit $rc
