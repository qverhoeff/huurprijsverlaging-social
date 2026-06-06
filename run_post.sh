#!/bin/bash
# Laad .env variabelen en voer het post script uit
# Zet dit script op een cron job: ma/wo/vr om 09:00

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Laad omgevingsvariabelen
if [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

cd "$SCRIPT_DIR"
python3 post_generator.py "$@"
