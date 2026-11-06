#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "$0")/../../.." && pwd)"
exec "$root/run_all.sh" --benchmarks mmlu_pt "$@"
