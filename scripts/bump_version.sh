#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [major|minor|patch] [--commit] [--push] [--tag-message "msg"]

Examples:
  # bump patch and print new version
  $0 patch

  # bump minor, commit, tag and push
  $0 minor --commit --push

Notes:
  - The script updates the file named VERSION at repo root.
  - If --commit is used the working tree must be clean.
EOF
  exit 1
}

PART=${1:-patch}
case "$PART" in
  major|minor|patch)
    shift || true
    ;;
  -h|--help)
    usage
    ;;
  *)
    # default to patch if unknown
    PART=patch
    ;;
esac

COMMIT=0
PUSH=0
TAG_MSG="Release"
while [ $# -gt 0 ]; do
  case "$1" in
    --commit) COMMIT=1 ; shift ;;
    --push) PUSH=1 ; shift ;;
    --tag-message) TAG_MSG="$2"; shift 2 ;;
    --tag-message=*) TAG_MSG="${1#*=}"; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$ROOT_DIR/VERSION"

if [ ! -f "$VERSION_FILE" ]; then
  echo "0.0.0" > "$VERSION_FILE"
fi

VER_RAW=$(cat "$VERSION_FILE" | tr -d ' \n')
VER=${VER_RAW#v}

IFS='.' read -r MAJ MIN PATCH_TMP <<< "$VER"
PATCH=${PATCH_TMP%%-*}

MAJ=${MAJ:-0}
MIN=${MIN:-0}
PATCH=${PATCH:-0}

case "$PART" in
  major)
    MAJ=$((MAJ+1))
    MIN=0
    PATCH=0
    ;;
  minor)
    MIN=$((MIN+1))
    PATCH=0
    ;;
  patch)
    PATCH=$((PATCH+1))
    ;;
esac

NEW_VERSION="${MAJ}.${MIN}.${PATCH}"

if [ "$COMMIT" -eq 1 ]; then
  # ensure working tree clean BEFORE modifying VERSION
  if [ -n "$(git status --porcelain)" ]; then
    echo "Working tree is not clean. Commit or stash changes before using --commit." >&2
    exit 1
  fi
fi

echo "$NEW_VERSION" > "$VERSION_FILE"
echo "Bumped version: $VER -> $NEW_VERSION"

if [ "$COMMIT" -eq 1 ]; then
  git add "$VERSION_FILE"
  git commit -m "Bump version to v$NEW_VERSION"
  git tag -a "v$NEW_VERSION" -m "$TAG_MSG v$NEW_VERSION"
  echo "Committed and tagged v$NEW_VERSION"

  if [ "$PUSH" -eq 1 ]; then
    git push origin HEAD
    git push origin "v$NEW_VERSION"
    echo "Pushed commit and tag v$NEW_VERSION to origin"
  fi
fi

exit 0
