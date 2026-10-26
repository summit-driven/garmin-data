#!/bin/zsh
# Pobiera nowe dane z Garmina i, jeśli repo ma zdalny origin, commituje i pushuje.
# Użycie: ./sync.sh [argumenty dla garmin_sync.py]
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

uv run scripts/garmin_sync.py "$@"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git add data
  if ! git diff --cached --quiet; then
    git commit -q -m "garmin: sync $(date +%Y-%m-%d\ %H:%M)"
    if git remote get-url origin >/dev/null 2>&1; then
      git push -q
    fi
  fi
fi
