#!/usr/bin/env bash
set -euo pipefail

python3 -m compileall -q main.py src

tracked_generated="$(
  git ls-files \
    '.DS_Store' \
    '.history' \
    'venv' \
    '*.log' \
    'src/seo_report_*.csv' \
    'src/results.csv' \
    'src/logs' \
    'src/nltk_data' \
    'src/utils/nltk_data'
)"

if [[ -n "$tracked_generated" ]]; then
  echo "Generated/local files are tracked:" >&2
  echo "$tracked_generated" >&2
  exit 1
fi

echo "Validation passed."
