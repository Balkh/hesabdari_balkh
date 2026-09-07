# Phase 1 Increment 23 — PostgreSQL Compatibility Verification Setup

Date: 2026-09-07

## Scope

Closes the previously BLOCKED "PostgreSQL is not installed / compatibility not verified" item from `PHASE_1_CURRENT_STATUS.md` by making the PostgreSQL check a reproducible, executed step — while keeping SQLite as the offline development baseline (ADR-0002).

No business workflow was implemented. No accounting rule was added.

## Changes

1. `requirements.txt`: added `psycopg[binary]>=3.1,<4.0` (Django 5.2 PostgreSQL driver).
2. `backend/config/settings/postgres.py`: new verification settings profile that reads the documented `POSTGRES_*` environment variables (defaults match `.env.example`). Development/CI only.
3. `backend/config/settings/production.py`: production now requires every `POSTGRES_*` variable and never falls back to SQLite, implementing the ADR-0002 consequence "PostgreSQL is required before a networked/production deployment".
4. `scripts/verify_postgresql.sh`: runs `manage.py check`, `migrate`, the Django suite, and pytest against a live PostgreSQL server.
5. `.github/workflows/ci.yml`: new `postgresql` job that starts a `postgres:16` service container and executes the verification script.

## Honest environment limitation

This development sandbox cannot install a PostgreSQL server: outbound access to the Debian package repositories is blocked (network egress is limited to PyPI/npm/GitHub), and no PostgreSQL binary is otherwise available. Therefore the full-suite PostgreSQL execution is performed by the GitHub Actions `postgresql` job, which provisions a real server. Local evidence in this environment is limited to:

```text
$ manage.py check --settings=config.settings.postgres
System check identified no issues (0 silenced).

$ python -c "import psycopg; print(psycopg.__version__)"
psycopg 3.3.5

production settings raise KeyError('POSTGRES_DB') when POSTGRES_* are absent (fail fast, no SQLite fallback)
```

Local SQLite baseline remains green after the dependency change:

```text
PHASE 1 LOCAL VERIFICATION: PASS   (Django 17 tests, pytest 25, frontend build, frontend 4 tests)
```

## Status

Setup PASS locally. PostgreSQL suite result is reported once the CI `postgresql` job completes.
