# Phase 6 — Stage 6.4 Evidence Gap Check

## A. Gap 1 — Stage 6.4 Commit Identity

Direct Git inspection:

- Exact Stage 6.4 implementation commit: `e6d6c3626934000924ae5531cd0a63e7966ea9ad`
- Subject: `feat(inventory): implement Stage 6.4 adjustments and shortage`
- Parent: `f2f3e30` (`feat(inventory): implement Stage 6.3 warehouse transfer`)
- Commit timestamp: `2026-09-18 11:45:47 +0000`
- Exact files in that commit:
  - `backend/inventory/inventory_tests.py`
  - `backend/inventory/migrations/0003_shortagesettlement_and_more.py`
  - `backend/inventory/models.py`
  - `backend/inventory/services.py`
  - `docs/phase-reports/PHASE_6_STAGE_6.4_IMPLEMENTATION_EVIDENCE.md`

The commit is narrow and Stage-6.4-only. Its parent is the Stage 6.3 commit; it contains no accounting, fiscal-period, master-data, security, frontend, CI, or script changes.

Current `git status --short` also shows these pre-existing working-tree modifications, not included in either the Stage 6.4 commit or this gap-check commit:

```text
 M scripts/verify_backend.sh
 M scripts/verify_frontend.sh
 M scripts/verify_phase1.sh
 M scripts/verify_postgresql.sh
```

No merge, amend, force-push, tag, or freeze was performed.

## B. Gap 2 — Atomic Rollback Evidence

The original Stage 6.4 tests did not have explicit late-failure rollback coverage. Three smallest focused tests were added. The settlement test exposed a real idempotency error path: when the atomic body failed, the reservation had already rolled back, but the handler attempted to read it as an existing retry. The handler was corrected to re-raise the original failure when the reservation no longer exists. The settlement idempotency insert was also corrected to persist `compensation_amount` and `reference`.

Executed command:

```text
cd backend && pytest inventory/inventory_tests.py -q
106 passed
```

The four new test methods are:

1. `Stage64Tests.test_adjustment_failure_rolls_back_movement_audit_and_idempotency`
   - Failure injected: `inventory.services.record_audit_event` raises `RuntimeError("audit store down")` after movement creation is attempted.
   - Before/after assertion: `StockMovement`, `AuditEvent`, and `IdempotencyRecord` counts are identical.
   - Actual result: passed; movement, audit, and idempotency reservation all rolled back.

2. `Stage64Tests.test_waste_failure_rolls_back_usable_movement_audit_and_idempotency`
   - Failure injected: the same audit failure during `receive_with_waste()`.
   - Before/after assertion: `StockMovement`, `AuditEvent`, and `IdempotencyRecord` counts are identical.
   - Actual result: passed; no usable movement, waste annotation, audit, or idempotency state remained.

3. `Stage64Tests.test_shortage_settlement_failure_rolls_back_settlement_and_audit`
   - A real `SHORTAGE` movement is created first.
   - Failure injected: audit failure after `ShortageSettlement` creation is attempted.
   - Before/after assertion: `ShortageSettlement` and `AuditEvent` counts are identical.
   - Actual result: passed; settlement, audit, and idempotency reservation rolled back.

4. `TransferAtomicityIdempotencyTests.test_leg_failure_rolls_back_journal`
   - Existing Stage 6.3 test; failure injected on the second `StockMovement.objects.create` call.
   - Assertions: no transfer legs, no journal, and no transfer audit remain.
   - Actual result: passed in the same 106-test focused run.

`record_shortage()` uses the same `_adjustment_operation()` → `_post_movement()` transaction path as `adjust_stock_out()`. The adjustment rollback test therefore covers its movement/audit/idempotency rollback primitive; the explicit settlement test covers the separate settlement state.

## C. Gap 3A — AVCO / Value Conservation

The existing test `TransferCostTests.test_cost_basis_preserved` was strengthened and passed in the 106-test run. It now records the pre-transfer and post-transfer state:

```text
Source before:      quantity 150, AVCO 13.3333
Destination before: quantity 0,   AVCO None
Transfer:           50 units
Transfer basis:     13.3333 AFN/unit
Transfer value:     50 × 13.3333 = 666.6650 AFN
Source after:       quantity 100, AVCO 13.3334 (displayed/replayed)
Destination after:  quantity 50,  AVCO 13.3333
```

The exact replay value before rounding is:

```text
Source original value: 100×10 + 50×20 = 2,000.0000 AFN
Source remaining exact value: 100×13.33335 = 1,333.3350 AFN
Destination exact value: 50×13.3333 = 666.6650 AFN
Total exact value after: 1,333.3350 + 666.6650 = 2,000.0000 AFN
```

The source displayed AVCO is `13.3334` because the existing replay relief uses the defined four-decimal Half-Up quantization: exact `13.33335` rounds upward. Multiplying the displayed source AVCO by 100 produces a displayed value of `1,333.3400`, which is the documented `0.0050` display/replay dust. That is not an additional movement value and is not a second valuation engine. Exact movement/replay values conserve the original `2,000.0000 AFN`; no artificial inventory value is created or lost.

No AVCO algorithm or precision was changed.

## D. Gap 3B — AFN-Only Transfer Journal

A new executable test was added and passed:

- `TransferAccountingTests.test_usd_costed_transfer_journal_is_afn_book_value`
- SQLite focused command: `pytest inventory/inventory_tests.py -q`
- Result: **107 passed** after the additional AFN test.

Concrete scenario:

```text
USD receipt:       10 units × USD 10.0000
Historical rate:   70 AFN/USD
AFN inventory cost: 700.0000 per unit
Transfer:          10 units
Journal amount:    7,000.00 AFN
```

Observed journal fields:

```text
currency:       AFN
rate:           1.0000
rate_direction: AFN->AFN
total_debit:    7,000.00
total_credit:   7,000.00
afn_total:      7,000.00
```

The reasoning is consistent with the inspected contract and implementation:

- Phase 0 defines AFN as the system-wide accounting/reporting base currency and says AFN equivalent supplements, rather than replaces, transaction currency.
- Phase 0 also states that V1 inventory valuation and AVCO are authoritative in AFN.
- `post_journal()` implements one transaction currency per journal, snapshots the rate, and computes `afn_total`. For an AFN journal it requires rate `1.0000`, sets direction `AFN->AFN`, and does not convert the book amount a second time.
- Stage 6.3 computes the transfer basis from the existing AFN AVCO and calls `post_journal()` with that AFN book value. This avoids multiplying an already-AFN inventory value by the USD rate again.
- The original USD receipt remains immutable with its USD unit cost and historical rate. The transfer legs preserve the AFN cost context used for the reclassification, including `unit_cost_afn`; the source/destination mapped accounts receive `Dr destination inventory / Cr source inventory`.
- The transfer journal creates no FX gain/loss, revenue, expense, COGS, or P&L change. It is a balanced asset-to-asset reclassification and does not change total inventory value.
- The implementation uses the existing `post_journal()` and money/FX precision utilities; no multi-currency journal or second FX engine was introduced.

Existing `TransferAccountingTests.test_reclass_journal_balanced_and_mapped` and `test_no_pnl_cogs_or_fx` also passed.

## E. Regression

### SQLite — executed

- Focused inventory suite: `pytest inventory/inventory_tests.py -q` → **107 passed**
- Full backend suite: `pytest -q` → **679 passed**
- Django runner: `python manage.py test --verbosity 1` → **17 OK**
- `python manage.py check` → **0 issues**
- `python manage.py makemigrations --check --dry-run` → **No changes detected**
- Fresh SQLite migration verification: forward → `inventory 0002` (reverse of 0003) → `inventory 0003` (forward) → **OK**

### PostgreSQL 17.x — not executable in this continuation environment

The required equivalent command was attempted:

```text
DJANGO_SETTINGS_MODULE=config.settings.postgres pytest inventory/inventory_tests.py -q
```

Actual result: setup failed for all tests because PostgreSQL was not listening on `127.0.0.1:5432` (`connection refused`). The PostgreSQL binaries/cluster were not available in this continuation environment. Therefore no new PostgreSQL result is claimed here. The previously recorded Stage 6.4 PostgreSQL result (`675 passed`) predates these new gap-check tests and is not represented as the current 107/679 result.

## F. Final Diff / Scope

This gap-check change is intended to be a narrow evidence/code-fix commit containing only:

- `backend/inventory/inventory_tests.py`
- `backend/inventory/services.py`
- `docs/phase-reports/PHASE_6_STAGE_6.4_EVIDENCE_GAP_CHECK.md`

The protected surfaces remain untouched: accounting, fiscal_periods, parties, categories, uom, products, warehouses, cash_accounts, exchange_houses, currencies, documents, security, core, frontend, scripts, and `.github` were not changed by this gap-check commit. The four pre-existing modified script files remain outside the commit and were not edited by this work.

## G. Status

**Evidence Gap Check completed — awaiting user review.**

Stage 6.4 is not frozen. Phase 6 is not frozen. Stage 6.5 was not started.
