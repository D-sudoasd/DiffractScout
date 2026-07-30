#!/usr/bin/env bash
set -euo pipefail

OWNER="${1:-D-sudoasd}"
REPO="${2:-DiffractScout}"
VISIBILITY="${3:---private}"
DRY_RUN="${DIFFRACTSCOUT_PUBLISH_DRY_RUN:-0}"
DESCRIPTION="Provenance-first phase scouting and indexed powder diffraction references"
TARGET_URL="https://github.com/${OWNER}/${REPO}.git"

case "$VISIBILITY" in
  --private|--public) ;;
  *) echo "Visibility must be --private or --public." >&2; exit 2 ;;
esac
case "$DRY_RUN" in
  0|1) ;;
  *) echo "DIFFRACTSCOUT_PUBLISH_DRY_RUN must be 0 or 1." >&2; exit 2 ;;
esac

command -v git >/dev/null || { echo "git is required." >&2; exit 2; }
command -v gh >/dev/null || { echo "GitHub CLI is required: https://cli.github.com/" >&2; exit 2; }
gh auth status >/dev/null

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[[ -d .git ]] || { echo "Run this script from the prepared DiffractScout repository." >&2; exit 2; }
[[ -z "$(git status --porcelain)" ]] || { echo "Refusing to publish a dirty working tree." >&2; exit 3; }

BRANCH="$(git branch --show-current)"
[[ -n "$BRANCH" ]] || { echo "Refusing to publish from detached HEAD." >&2; exit 3; }

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  run gh repo create "$OWNER/$REPO" "$VISIBILITY" --description "$DESCRIPTION"
fi

CURRENT_ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
case "$CURRENT_ORIGIN" in
  "https://github.com/${OWNER}/${REPO}"|"https://github.com/${OWNER}/${REPO}.git"|"git@github.com:${OWNER}/${REPO}.git")
    ;;
  "")
    run git remote add origin "$TARGET_URL"
    ;;
  *)
    echo "Replacing non-target origin: $CURRENT_ORIGIN"
    run git remote set-url origin "$TARGET_URL"
    ;;
esac

run git push -u origin "$BRANCH"
run gh repo edit "$OWNER/$REPO" \
  --description "$DESCRIPTION" \
  --add-topic materials-science \
  --add-topic crystallography \
  --add-topic powder-diffraction \
  --add-topic xrd \
  --add-topic materials-project \
  --add-topic elasticity \
  --add-topic research-software

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run complete; no repository, remote, or branch was changed."
else
  echo "Published: https://github.com/$OWNER/$REPO"
fi
