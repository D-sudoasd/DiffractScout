#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
pandoc paper.md \
  --citeproc \
  --bibliography=paper.bib \
  --pdf-engine=xelatex \
  --metadata=author:'Delun Gong' \
  --variable=geometry:margin=0.75in \
  --variable=fontsize:10pt \
  --variable=papersize:letter \
  --variable=colorlinks:true \
  --variable=linkcolor:blue \
  --variable=urlcolor:blue \
  --output=paper.pdf
