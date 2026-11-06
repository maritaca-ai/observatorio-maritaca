#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$root"
export PYTHONPATH="$root/src:$root${PYTHONPATH:+:$PYTHONPATH}"
exec "${S5_NANO_PYTHON:-python3}" -m s5_nano.run_all "$@"
