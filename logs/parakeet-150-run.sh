#!/bin/zsh -l
cd ~/Developer/clarity-captions
/Users/gileskayo/.local/bin/claude -p "$(cat ~/.claude/handoffs/resume-2026-10-24-parakeet-headless.prompt)" --permission-mode auto --output-format stream-json --verbose -n "Seal Speak Parakeet 150" >> ~/.agents/logs/parakeet-150.jsonl 2>&1
echo "EXIT $?" >> ~/.agents/logs/parakeet-150.jsonl
