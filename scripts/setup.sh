#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python --require-hashes envs/requirements.lock
uv pip install --python .venv/bin/python --no-build-isolation --no-deps -e .
uv venv --python 3.12 .cache/scorer-venv
uv pip sync --python .cache/scorer-venv/bin/python --require-hashes envs/requirements-scorer.lock
