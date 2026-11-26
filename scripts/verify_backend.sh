#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
../backend/.venv/bin/python ../scripts/audit_writer_inventory.py
../backend/.venv/bin/python manage.py check --settings=config.settings.test
printf "\nW0-2E Batch A targeted checks (SQLite)\n"
../backend/.venv/bin/python manage.py test security.test_audit_chain.AuditBatchAIntegrityTests security.test_audit_chain.AuditBatchAFinancialRollbackTests --settings=config.settings.test --verbosity=2
../backend/.venv/bin/python manage.py test --settings=config.settings.test
../backend/.venv/bin/pytest
