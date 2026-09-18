# Phase 6 — Stage 6.4 Implementation Evidence

Status: **Stage 6.4 implementation and evidence completed. Awaiting user review.**

This report records the executed Stage 6.4 work. Stage 6.4 and Phase 6 are not frozen; no merge, tag, or release was created.

## A. Baseline

- Branch: `phase/4`
- Baseline HEAD: `f2f3e30` (`feat(inventory): implement Stage 6.3 warehouse transfer`)
- Working tree before implementation: clean.
- Recent chain: `2f65472 -> 50625b4 -> 8697768 -> f2f3e30`.
- Existing inventory test baseline: 95 pytest tests.
- Existing movement architecture already had `ADJUSTMENT_IN` and `ADJUSTMENT_OUT`; `SHORTAGE` was added only because the later shortage event has distinct business meaning.
- Existing `StockMovement`, signed integer stock sum, AVCO replay, receive/issue/open/transfer primitives, audit, idempotency, negative-stock acknowledgement, temporary cost, fiscal gate, and warehouse mapping were inspected before implementation.

## B. Implementation

Changed only the Stage 6.4 inventory surface plus this report:

- `backend/inventory/models.py`
- `backend/inventory/services.py`
- `backend/inventory/inventory_tests.py`
- `backend/inventory/migrations/0003_shortagesettlement_and_more.py`

Implemented:

- `adjust_stock_in()` — positive explicit-cost adjustment.
- `adjust_stock_out()` — negative adjustment using the existing issue/AVCO and negative acknowledgement policy.
- `receive_with_waste()` — one usable receipt movement with `gross_quantity` and `waste_quantity` traceability; total cost is divided by usable quantity.
- `record_shortage()` — later shortage as a new immutable `SHORTAGE` outbound event.
- `settle_shortage()` — immutable manual actual-sales-rate settlement record; it does not change stock or AVCO.
- `ShortageSettlement` — stores shortage reference, settlement date, manual rate, currency/rate snapshot, compensation amount, reference, and idempotency key.

No ownership dimension, secondary UOM, purchase/landed-cost workflow, sales module, keeper master, duplicate stock ledger, duplicate AVCO engine, duplicate accounting engine, or new COA/account mapping was introduced.

### Accounting boundary

Inspection found no approved Phase 0 mapping for adjustment gain/loss, receiving waste, shortage loss, or shortage compensation. Therefore no journal is invented. These Stage 6.4 operations remain inside the approved inventory boundary and explicitly defer accounting until an approved mapping exists. `settle_shortage()` stores the compensation concept and manual amount only; it does not post P&L or rewrite inventory valuation.

## C. Positive Adjustment Evidence

Executed focused test `Stage64Tests.test_positive_adjustment_stock_cost_and_audit`:

- Before: `0`
- `ADJUSTMENT_IN`: `+5` at AFN 12.0000
- After: `5`
- Movement type: `ADJUSTMENT_IN`
- Audit row: present for the posted `StockMovement`.

## D. Negative Adjustment Evidence

Executed `Stage64Tests.test_negative_adjustment_reuses_ack_and_temporary_cost`:

- `+2` received through a positive adjustment at AFN 10.0000.
- Attempted `-3` without acknowledgement: rejected with the existing negative-stock warning.
- Retried with acknowledgement and explicit manual temporary cost AFN 11.0000: posted.
- Result: stock `-1`; `is_temporary_cost=True`.
- No reference price was consulted or substituted.

## E. Waste Evidence

Executed `Stage64Tests.test_waste_allocates_total_cost_over_usable_and_is_traceable`:

- Gross received: `2,000`
- Waste during unloading: `3`
- Usable stock movement: `1,997`
- Total shipment cost: USD `370,000`
- Explicit rate: `1`
- Stored unit cost: `370,000 / 1,997 = 185.2779` (existing Half-Up precision)
- Stored traceability: `gross_quantity=2000`, `waste_quantity=3`
- Stock movements created: one usable receipt only; waste was not silently posted as a later shortage.

## F. Shortage Evidence

Executed `Stage64Tests.test_shortage_is_new_event_and_settlement_uses_manual_rate`:

- Original receipt: `+1,997` at unit cost `20.0000`.
- Later shortage event: `-7` as a new immutable `SHORTAGE` movement.
- Resulting stock: `1,990`.
- Original receipt remained quantity `1,997` and unit cost `20.0000`.
- No historical movement was edited or deleted.

## G. Compensation Evidence

The same executed test created a settlement for the `7`-unit shortage with manually supplied actual sales rate USD `125.0000`.

- Stored manual unit rate: `125.0000`
- Stored compensation amount: `7 × 125 = 875.0000`
- Stored settlement date, currency/rate snapshot, reference, and shortage link.
- No Product reference price, AVCO, standard cost, last purchase price, market price, or inferred rate was used.
- Stock remained `1,990`; no valuation rewrite and no journal was created.

## H. AVCO Evidence

Executed `Stage64Tests.test_zero_reset_and_later_receipt`:

- Receipt `5 @ 10`, then negative adjustment `-5`.
- Stock reached zero and `avco_for()` returned `None`.
- Later receipt `2 @ 30` established AVCO `30.0000`.

The implementation calls the existing `avco_for()` and `_post_movement()` primitives; no second replay engine was added.

## I. Atomicity

The new operations use the existing `transaction.atomic()` path through `_post_movement()` and the existing idempotency transaction wrapper. Settlement creation and its audit are in one atomic block. No accounting transaction is created because accounting is explicitly deferred by the inspected contract boundary.

## J. Idempotency

Executed `Stage64Tests.test_adjustment_exact_retry_and_mismatch`:

- Exact retry with the same key and payload returned the original movement.
- Movement count for the key remained `1`.
- Same key with changed quantity was rejected as a materially different operation.
- Fingerprints include operation/movement identity, product, warehouse, signed quantity, date, currency, cost/rate context, reference, description, temporary flag, actor, and waste fields where applicable.

## K. Immutability

Executed `Stage64Tests.test_posted_adjustment_and_settlement_are_immutable`:

- Posted adjustment edit rejected by `PostedImmutabilityError`.
- Posted adjustment delete rejected by `PostedImmutabilityError`.
- Posted settlement delete rejected by `PostedImmutabilityError`.
- `SHORTAGE` is in the existing outbound movement direction set and uses the existing immutable `StockMovement` model.

## L. Audit

Adjustment, waste receipt, and shortage movement creation reuse the existing `record_audit_event()` through `_create_movement()`. Movement snapshots include before/after quantities, date, signed quantity, cost/rate context, temporary-cost state, reference, description, and waste fields. Settlement audit stores the shortage id, settlement date, manual rate, currency, and compensation amount.

## M. Fiscal Period

Stage 6.4 posting entry points call the existing single `assert_posting_date_open()` gate. No fiscal-period architecture was changed. Empty-period bootstrap behavior remains the existing approved behavior.

## N. Database Tests

### SQLite

Executed from `backend/`:

- `pytest inventory -q`: **103 passed** (95 baseline + 8 Stage 6.4 tests).
- `pytest -q`: **675 passed**.
- `python manage.py check`: 0 issues.
- `python manage.py makemigrations --check --dry-run`: `No changes detected`.
- Migration verification on a fresh `/tmp/stage64-migration.sqlite3`: forward, backward from `inventory 0003` to `0002`, and forward again: **OK**.
- Django runner: **17 tests OK**.

### PostgreSQL 17.x

Executed with `DJANGO_SETTINGS_MODULE=config.settings.postgres`:

- `pytest inventory -q`: **103 passed**.
- `pytest -q`: **675 passed**.
- `python manage.py check`: 0 issues.
- `python manage.py makemigrations --check --dry-run`: `No changes detected`.
- PostgreSQL migration verification: full forward, `inventory 0003 -> 0002`, `inventory 0002 -> 0003`, full forward: **OK**.
- Django runner: **17 tests OK**.

## O. Frozen Surface

Executed protected-surface diff:

```text
git diff --name-only -- backend/accounting backend/fiscal_periods backend/parties \
  backend/categories backend/uom backend/products backend/warehouses \
  backend/cash_accounts backend/exchange_houses backend/currencies \
  backend/documents backend/security backend/core frontend
```

Result: no paths reported. Only inventory models, services, tests, migration, and this evidence report changed.

Accounting protection check: no new COA number, P&L logic, FX engine, duplicate journal, or duplicate account mapping was introduced. Accounting is explicitly deferred because the inspected contract did not specify an approved mapping.

## P. Git

A narrow Stage 6.4 commit was created after the evidence runs:

- Commit: the commit created for this implementation (verified by the final `git log` below)
- Scope: the four inventory implementation files plus this Stage 6.4 evidence report.
- No history rewrite, amend, force-push, merge, main update, tag, or freeze.
- Final working tree status is verified after commit.

**Stage 6.4 implementation and evidence completed. Awaiting user review.**
