#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCALES_DIR="$ROOT_DIR/locales"
DOMAIN="rmmanager"
POT_FILE="$LOCALES_DIR/$DOMAIN.pot"

PYBABEL="${PYBABEL:-pybabel}"

if ! command -v "$PYBABEL" &>/dev/null; then
  echo "pybabel not found. Activate your virtual environment first." >&2
  exit 1
fi

echo "Extracting messages..."
"$PYBABEL" extract -F "$ROOT_DIR/pyproject.toml" -k "_n:1,2" -o "$POT_FILE" "$ROOT_DIR"

echo "Updating .po files..."
"$PYBABEL" update -i "$POT_FILE" -d "$LOCALES_DIR" -D "$DOMAIN"

echo "Done. Review changes in $LOCALES_DIR before committing."
