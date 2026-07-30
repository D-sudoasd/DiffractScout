#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/paper"

if command -v docker >/dev/null 2>&1; then
  docker run --rm \
    --volume "$PWD:/data" \
    --user "$(id -u):$(id -g)" \
    --env JOURNAL=joss \
    openjournals/inara
else
  echo "Docker is required for the exact Open Journals draft. Use the draft-pdf GitHub workflow." >&2
  exit 2
fi
