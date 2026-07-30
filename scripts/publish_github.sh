#!/usr/bin/env bash
set -euo pipefail

OWNER="${1:-D-sudoasd}"
REPO="${2:-DiffractScout}"
VISIBILITY="${3:---private}"

case "$VISIBILITY" in
  --private|--public) ;;
  *) echo "Visibility must be --private or --public." >&2; exit 2 ;;
esac

command -v git >/dev/null || { echo "git is required." >&2; exit 2; }
command -v gh >/dev/null || { echo "GitHub CLI is required: https://cli.github.com/" >&2; exit 2; }
gh auth status >/dev/null

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[[ -d .git ]] || { echo "Run this script from the prepared DiffractScout repository." >&2; exit 2; }
[[ -z "$(git status --porcelain)" ]] || { echo "Refusing to publish a dirty working tree." >&2; exit 3; }

if git remote get-url origin >/dev/null 2>&1; then
  echo "origin already exists: $(git remote get-url origin)"
else
  gh repo create "$OWNER/$REPO" "$VISIBILITY" --source . --remote origin --push \
    --description "Provenance-first phase scouting and indexed powder diffraction references"
fi

gh repo edit "$OWNER/$REPO" \
  --description "Provenance-first phase scouting and indexed powder diffraction references" \
  --add-topic materials-science \
  --add-topic crystallography \
  --add-topic powder-diffraction \
  --add-topic xrd \
  --add-topic materials-project \
  --add-topic elasticity \
  --add-topic research-software

echo "Published: https://github.com/$OWNER/$REPO"
