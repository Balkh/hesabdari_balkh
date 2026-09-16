#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/verify_backend.sh"
"$ROOT/scripts/verify_frontend.sh"
printf '\nPHASE 1 LOCAL VERIFICATION: PASS\n'
