#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .cache/remaining-venv/bin/python ]; then
  uv venv --python 3.12 .cache/remaining-venv
fi
uv pip sync --python .cache/remaining-venv/bin/python --require-hashes envs/requirements.lock envs/requirements-remaining.lock
uv pip install --python .cache/remaining-venv/bin/python --no-build-isolation --no-deps -e .
