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
printf "\nW0-2E final remediation checks (PostgreSQL)\n"
"$PYTHON" manage.py test security.test_final_remediation --verbosity=2
printf "\nW0 security acceptance checks (PostgreSQL)\n"
"$PYTHON" manage.py test goods_in_transit.tests.GoodsInTransitTests.test_acceptance_transit_sale_final_audit_rollback goods_in_transit.tests.GoodsInTransitTests.test_acceptance_transit_delivery_final_audit_rollback goods_in_transit.tests.GoodsInTransitTests.test_acceptance_legacy_transit_bridge_final_audit_rollback sales.sales_tests.SalesImplementationTests.test_acceptance_future_sale_final_audit_rollback security.test_security_acceptance --verbosity=2
printf "\nW0 offline recovery checks (PostgreSQL)\n"
"$PYTHON" manage.py test security.test_offline_recovery security.test_backup_service.BatchCDatabaseRestoreTests.test_offline_recovery_bundle_verifies_financial_restore_in_fresh_process --verbosity=2
"$PYTHON" manage.py test --verbosity=2
DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" "$PYTHON" -m pytest -q -rs

printf '\nPOSTGRESQL VERIFICATION: PASS\n'
