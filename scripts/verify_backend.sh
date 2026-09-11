#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
../backend/.venv/bin/python manage.py check --settings=config.settings.test
../backend/.venv/bin/python manage.py test --settings=config.settings.test
../backend/.venv/bin/pytest
