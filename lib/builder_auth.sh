# Sourced by task_dispatch.py's wrapper (marvin #775, #849). The Max plan includes a monthly API credit that pays for
# `claude -p` only when it runs on a Console API key, and it expires unspent at the end of each billing cycle.
# Plan first, the credit only once the plan runs out (Gil, 2026-10-30; replaces #849's "credit for the slots past
# the plan's"): every build uses the plan while it has room, however many are running. Only while this Mac's plan is
# at its usage limit (dispatch_concurrency plan-limited, set by sandbox_orchestration._launch when a run hits it) does
# a build start on the credit, and only when this machine has a key in ~/.claude/.anthropic-api-key (never synced,
# mode 600) and one tiny request shows the credit is there. A spent credit, a rejected key or an unreachable API keeps
# the plan's token: running out of credit must never stop a build. That check's result goes to
# ~/.claude/dispatch/credit-state.json, which closes the extra slots for a while after a failure.
#
# The key is read here at run time, so it is never written into the wrapper's text, and it reaches curl through a
# header file, not argv (argv shows in `ps`). Each choice is appended to ~/.claude/logs/builder-billing.jsonl.

marvin_builder_auth() {
  local task="${1:-}" key_file="$HOME/.claude/.anthropic-api-key" key="" mode="plan" why="no-key"
  local status body limited
  # Unreadable state: assume the plan has room, so a guess never spends the credit.
  limited="$(cd "$HOME/.agents" 2>/dev/null && "$HOME/.agents/venv/bin/python" -m lib.dispatch_concurrency plan-limited 2>/dev/null)"
  [ -f "$key_file" ] && key="$(tr -d '[:space:]' < "$key_file")"
  if [ "$limited" != "true" ]; then
    why="plan-first"
  elif [ -n "$key" ]; then
    body="$(mktemp)"
    status="$(curl -sS -o "$body" -w '%{http_code}' --max-time 15 https://api.anthropic.com/v1/messages \
      -H @<(printf 'x-api-key: %s\n' "$key") \
      -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' \
      -d '{"model":"claude-haiku-5-5","max_tokens":1,"messages": [{"role": "user", "content": "ok"}]}' 2>/dev/null)"
    case "$status" in
      200) mode="api"; why="credit-ok" ;;
      401|403) why="key-rejected" ;;
      000|"") why="unreachable" ;;
      *) if grep -q 'credit balance is too low' "$body" 2>/dev/null; then why="credit-exhausted"; else why="http-$status"; fi ;;
    esac
    rm -f "$body"
    mkdir -p "$HOME/.claude/dispatch"
    printf '{"ok": %s, "why": "%s", "at": "%s"}\n' "$([ "$mode" = api ] && echo true || echo false)" "$why" \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$HOME/.claude/dispatch/credit-state.json"
  fi
  if [ "$mode" = "api" ]; then
    export ANTHROPIC_API_KEY="$key"
    unset CLAUDE_CODE_OAUTH_TOKEN
  fi
  mkdir -p "$HOME/.claude/logs"
  printf '{"at": "%s", "task": "%s", "mode": "%s", "why": "%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$task" "$mode" "$why" >> "$HOME/.claude/logs/builder-billing.jsonl"
}
