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
../backend/.venv/bin/python manage.py test --settings=config.settings.test
../backend/.venv/bin/pytest
