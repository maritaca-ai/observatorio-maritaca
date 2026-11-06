#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${JAVA_HOME:?Set JAVA_HOME to an existing Java 21 JDK}"
test -x "$JAVA_HOME/bin/java"
test -x "$JAVA_HOME/bin/javac"
uv venv --python 3.10 .cache/plus-venv
uv pip sync --python .cache/plus-venv/bin/python --require-hashes requirements-plus.lock
# Run through PYTHONPATH=src; this optional native environment is independent
# from the Python 3.12 environment used by the other benchmark engines.
