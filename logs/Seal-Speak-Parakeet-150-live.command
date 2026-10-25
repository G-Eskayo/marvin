#!/bin/zsh -l
printf "\e]0;Seal Speak: Parakeet build 7 (#150) live\a"
~/.agents/logs/parakeet-150-run.sh &
python3 ~/.agents/logs/parakeet-150-watch.py
