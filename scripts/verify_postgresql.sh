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
printf "\nW0-2E Batch A targeted checks (PostgreSQL)\n"
"$PYTHON" manage.py test security.test_audit_chain.AuditBatchAIntegrityTests security.test_audit_chain.AuditBatchAFinancialRollbackTests --verbosity=2
printf "\nW0-2E Batch B migration checks (PostgreSQL)\n"
"$PYTHON" manage.py makemigrations --check --dry-run
"$PYTHON" manage.py test security.test_audit_migrations --verbosity=2
printf "\nW0-2E Batch C restore checks (PostgreSQL)\n"
"$PYTHON" manage.py test security.test_backup_service.BatchCKeyAndManifestTests security.test_backup_service.BatchCDatabaseRestoreTests --verbosity=2
printf "\nW0-2E Batch D audit access and privacy checks (PostgreSQL)\n"
"$PYTHON" manage.py test security.test_audit_views --verbosity=2
printf "\nW0-2E final quality gate (PostgreSQL)\n"
"$PYTHON" manage.py test security.test_audit_final_gate --verbosity=2
"$PYTHON" manage.py test
DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" "$PYTHON" -m pytest -q

printf '\nPOSTGRESQL VERIFICATION: PASS\n'
