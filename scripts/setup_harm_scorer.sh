#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .cache/harm-scorer-venv/bin/python ]; then
  uv venv --python 3.12 .cache/harm-scorer-venv
fi
uv pip sync --python .cache/harm-scorer-venv/bin/python --require-hashes requirements-harm-scorer.lock
