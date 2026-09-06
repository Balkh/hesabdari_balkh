# Phase 1 Increment 03 — Currency Foundation

Date: 2026-09-06

## Scope

Implemented the technical currency master and historical directional exchange-rate foundation. No sales, purchases, payments, inventory, or accounting workflow was implemented.

## Implemented

- Configurable `Currency` model
- AFN/USD-compatible currency records
- Single base-currency database constraint
- Currency precision field
- Historical `ExchangeRate` model
- Directional rate convention: one source unit equals X target units
- Positive-rate and distinct-currency constraints
- Unique rate per currency pair and effective date
- SQLite migration

## Verification evidence

```text
cd backend && ../backend/.venv/bin/python manage.py test --settings=config.settings.test
Found 3 test(s). Ran 3 tests. OK

cd backend && ../backend/.venv/bin/pytest
4 passed
```

## Status

PASS for this increment only.

Complete Phase 1 remains BLOCKED until all foundation increments are implemented and verified.
