#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
../backend/.venv/bin/python ../scripts/audit_writer_inventory.py
../backend/.venv/bin/python manage.py check --settings=config.settings.test
printf "\nW0-2E Batch A targeted checks (SQLite)\n"
../backend/.venv/bin/python manage.py test security.test_audit_chain.AuditBatchAIntegrityTests security.test_audit_chain.AuditBatchAFinancialRollbackTests --settings=config.settings.test --verbosity=2
printf "\nW0-2E Batch B migration checks (SQLite)\n"
../backend/.venv/bin/python manage.py makemigrations --check --dry-run --settings=config.settings.test
../backend/.venv/bin/python manage.py test security.test_audit_migrations --settings=config.settings.test --verbosity=2
printf "\nW0-2E Batch C restore checks (SQLite)\n"
../backend/.venv/bin/python manage.py test security.test_backup_service.BatchCKeyAndManifestTests security.test_backup_service.BatchCDatabaseRestoreTests --settings=config.settings.test --verbosity=2
printf "\nW0-2E Batch D audit access and privacy checks (SQLite)\n"
../backend/.venv/bin/python manage.py test security.test_audit_views --settings=config.settings.test --verbosity=2
printf "\nW0-2E final quality gate (SQLite)\n"
../backend/.venv/bin/python manage.py test security.test_audit_final_gate --settings=config.settings.test --verbosity=2
printf "\nW0-2E final remediation checks (SQLite)\n"
../backend/.venv/bin/python manage.py test security.test_final_remediation --settings=config.settings.test --verbosity=2
printf "\nW0 security acceptance checks (SQLite)\n"
../backend/.venv/bin/python manage.py test goods_in_transit.tests.GoodsInTransitTests.test_acceptance_transit_sale_final_audit_rollback goods_in_transit.tests.GoodsInTransitTests.test_acceptance_transit_delivery_final_audit_rollback goods_in_transit.tests.GoodsInTransitTests.test_acceptance_legacy_transit_bridge_final_audit_rollback sales.sales_tests.SalesImplementationTests.test_acceptance_future_sale_final_audit_rollback security.test_security_acceptance --settings=config.settings.test --verbosity=2
printf "\nW0 offline recovery checks (SQLite)\n"
../backend/.venv/bin/python manage.py test security.test_offline_recovery security.test_backup_service.BatchCDatabaseRestoreTests.test_offline_recovery_bundle_verifies_financial_restore_in_fresh_process security.test_backup_service.BatchCDatabaseRestoreTests.test_offline_recovery_cli_real_verification_and_wrong_secret security.test_backup_service.BatchCDatabaseRestoreTests.test_recovered_copy_gm_recovery_preserves_financial_history --settings=config.settings.test --verbosity=2
../backend/.venv/bin/python manage.py test --settings=config.settings.test --verbosity=2
../backend/.venv/bin/pytest -rs
