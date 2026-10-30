#!/bin/bash
# Forced command for mac-mini-2012's observer key on each Mac (ADR 0069). The box's dashboard may READ a fixed list of
# things and nothing else. The requested text is only ever compared, never executed: each allowed request runs this
# script's own copy of the command. Install in ~/.ssh/authorized_keys as:
#   restrict,command="$HOME/.agents/config/mac-mini-2012/marvin-observer.sh" ssh-ed25519 ... marvin_observer
set -u
cmd="${SSH_ORIGINAL_COMMAND-}"
py="$HOME/.agents/venv/bin/python"
lib="$HOME/.agents/lib"

case "$cmd" in
  "echo ok")                                          echo ok ;;
  "cat ~/.claude/logs/tool-usage.json")               exec cat "$HOME/.claude/logs/tool-usage.json" ;;
  "cat ~/.claude/logs/token-usage.json")              exec cat "$HOME/.claude/logs/token-usage.json" ;;
  "cat ~/.claude/logs/health-status.json")            exec cat "$HOME/.claude/logs/health-status.json" ;;
  "cat ~/.claude/logs/github-feed.json")              exec cat "$HOME/.claude/logs/github-feed.json" ;;
  'cat "$HOME/.claude/dispatch-state.json"')          exec cat "$HOME/.claude/dispatch-state.json" ;;
  'cat "$HOME/.claude/ticket-scan-heartbeat.json"')   exec cat "$HOME/.claude/ticket-scan-heartbeat.json" ;;
  "ps -axo command")                                  exec ps -axo command ;;
  "git -C .agents rev-parse HEAD")                    exec git -C "$HOME/.agents" rev-parse HEAD ;;
  "git -C .claude rev-parse HEAD")                    exec git -C "$HOME/.claude" rev-parse HEAD ;;
  '$HOME/.agents/venv/bin/python $HOME/.agents/lib/error_log.py recent --json --hours 24')
                                                      exec "$py" "$lib/error_log.py" recent --json --hours 24 ;;
  "~/.agents/venv/bin/python ~/.agents/lib/github_usage.py")
                                                      exec "$py" "$lib/github_usage.py" ;;
  "~/.agents/venv/bin/python ~/.agents/lib/usage_report.py scan")
                                                      exec "$py" "$lib/usage_report.py" scan ;;
  "~/.agents/venv/bin/python ~/.agents/lib/auto_merge_shadow.py report-json")
                                                      exec "$py" "$lib/auto_merge_shadow.py" report-json ;;
  *)
    slots='^cd "\$HOME/\.agents" && "\$HOME/\.agents/venv/bin/python" -m lib\.dispatch_concurrency slots-in-use --machine ([a-z0-9][a-z0-9-]{0,40})$'
    metric='^~/\.agents/venv/bin/python ~/\.agents/lib/purpose_metrics\.py measure ([a-z0-9][a-z0-9-]{0,60}) --local$'
    if [[ "$cmd" =~ $slots ]]; then
      cd "$HOME/.agents" && exec "$py" -m lib.dispatch_concurrency slots-in-use --machine "${BASH_REMATCH[1]}"
    elif [[ "$cmd" =~ $metric ]]; then
      exec "$py" "$lib/purpose_metrics.py" measure "${BASH_REMATCH[1]}" --local
    fi
    echo "refused: mac-mini-2012's observer key may only read a fixed list (config/mac-mini-2012/marvin-observer.sh)" >&2
    exit 1 ;;
esac
