#!/usr/bin/env bash
# PostgreSQL compatibility verification for the Phase 1 foundation.
# Requires a reachable PostgreSQL server configured through POSTGRES_*
# environment variables (see .env.example). Used by CI and local operators.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.postgres}"
PYTHON="$ROOT/backend/.venv/bin/python"

printf 'PostgreSQL verification (DJANGO_SETTINGS_MODULE=%s)\n' "$DJANGO_SETTINGS_MODULE"

"$PYTHON" manage.py check
"$PYTHON" manage.py migrate --no-input
"$PYTHON" manage.py test
DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" "$PYTHON" -m pytest -q

printf '\nPOSTGRESQL VERIFICATION: PASS\n'
