#!/bin/zsh
# Pobiera nowe dane z Garmina i, jeśli repo ma zdalny origin, commituje i pushuje.
# Użycie: ./sync.sh [argumenty dla garmin_sync.py]
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
# Pod launchd /usr/bin/git bez tej zmiennej odmawia działania (licencja Xcode).
if [[ -z "${DEVELOPER_DIR:-}" && -d /Library/Developer/CommandLineTools ]]; then
  export DEVELOPER_DIR=/Library/Developer/CommandLineTools
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') sync start"
uv run scripts/garmin_sync.py "$@"

# Błąd gita ma przerwać skrypt i trafić do logu, a nie zostać przemilczany.
git rev-parse --is-inside-work-tree >/dev/null
git add data
if git diff --cached --quiet; then
  echo "git: brak zmian w danych"
else
  git commit -q -m "garmin: sync $(date +%Y-%m-%d\ %H:%M)"
  echo "git: commit $(git rev-parse --short HEAD)"
  if git remote get-url origin >/dev/null 2>&1; then
    GIT_TERMINAL_PROMPT=0 git push -q
    echo "git: push ok"
  fi
fi
