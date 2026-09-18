# Phase 6 — Stage 6.5 Purchase Return + Sales Return Evidence

Status: **Stage 6.5 implementation and evidence completed — awaiting user review.**

Stage 6.5 and Phase 6 are not frozen. No merge, tag, release, or main update was performed.

## A. Baseline

- Branch: `phase/4`
- HEAD before Stage 6.5 implementation: `4820844509c59578e40c6fe2d9b2e715516dfc7e` (`test(inventory): close Stage 6 evidence gaps`)
- Stage 6.4 implementation commit: `e6d6c3626934000924ae5531cd0a63e7966ea9ad`
- Stage 6.4 implementation parent: `f2f3e30`
- Pre-existing working-tree changes before Stage 6.5: four `scripts/verify_*.sh` files; they were not reset or incorporated.
- `backend/sales` contains only `.gitkeep`; no Purchase Invoice or Sales Invoice model/service exists.
- Existing `Party` supports supplier/customer roles.
- Existing `StockMovement` already contained semantic `PURCHASE_RETURN` and `SALES_RETURN` choices, but no return service or source-party/source-document traceability existed.

## B. Contract and Scope

Implemented only backend inventory return foundation:

- Purchase Return: stock OUT.
- Sales Return: stock IN.
- Immutable return identity linked to a source `StockMovement`, party, product, warehouse, source document reference, and return movement.
- Original source cost/currency/rate/date copied from the immutable source movement; current AVCO is not used for return cost.
- Partial/full/over-return validation from immutable return records.
- Party/product/warehouse/source-document validation.
- Existing fiscal gate, audit, idempotency, immutable movements, AVCO replay, and atomic transaction primitives reused.

Explicitly out of scope: full Purchase Invoice, full Sales Invoice, payable/receivable settlement, customer credit, supplier advance, COGS engine, return accounting journals, payment, API/UI, reporting, new FX engine, new AVCO engine, new ledger, and later Phase 6 stages.

## C. Implementation

Changed Stage 6.5 files:

- `backend/inventory/models.py`
  - `InventoryReturnType`
  - immutable `InventoryReturn`
  - `StockMovement.source_party` for minimal source party traceability
  - operation constants
- `backend/inventory/services.py`
  - `purchase_return()`
  - `sales_return()`
  - shared validation, fingerprint, source resolution, remaining-return calculation, and atomic posting helpers
  - optional `party` source metadata on existing receipt/issue primitives
- `backend/inventory/inventory_tests.py`
  - 9 focused Stage 6.5 tests
- `backend/inventory/migrations/0004_inventoryreturn.py`
- `backend/inventory/migrations/0005_stockmovement_source_party.py`
- this evidence report

`InventoryReturn` is not a stock ledger: stock truth remains `SUM(StockMovement.quantity)`. It exists because `StockMovement` alone could not preserve return business identity, party identity, source document identity, and immutable return-to-source linkage. The source document is the existing immutable source movement `reference`; no Purchase/Sales invoice architecture was invented.

The new `source_party` field is nullable for historical/future non-party inventory primitives. Stage 6.5 source receipts/issues created for returns carry the supplier/customer party; a return requires the source party to match.

## D. Purchase Return Evidence

Executed test: `Stage65ReturnTests.test_purchase_return_uses_original_cost_and_reduces_stock`.

```text
Source purchase movement: PI-65
Supplier:                 Supplier 65
Product:                  OIL-10L
Warehouse:                Omar Rahimi
Original quantity:        100
Original cost:            AFN 10.0000/unit
Later receipt:            100 @ AFN 30.0000
Current AVCO before return: AFN 20.0000
Return quantity:          20
Return movement:          PURCHASE_RETURN, -20
Return cost:              AFN 10.0000 (original source cost)
Stock before return:      200
Stock after return:       180
Return qty_before/after:  200 -> 180
```

The test also verifies the original source quantity remains `100`, and the `InventoryReturn` audit links source movement id to return movement id.

The explicit Sales Return audit closure test is `Stage65ReturnTests.test_sales_return_uses_original_sale_cost_not_current_avco`. It retrieves the `AuditEvent` for the `InventoryReturn` and verifies `return_type=SALES_RETURN`, source movement id, return movement id, quantity `10`, original unit cost `12.0000`, customer id, product id, and warehouse id. It passed in the final focused run (`116 passed`). The shared code path is `_post_return()` → `_create_movement()` → `record_audit_event()` for the movement, followed by the explicit `InventoryReturn` audit event; no Sales-specific audit subsystem exists.

Foreign historical context test: `Stage65ReturnTests.test_foreign_purchase_return_preserves_historical_rate` passed:

```text
Source cost: USD 10.0000
Historical rate: 70.0000
Return cost: USD 10.0000
Return rate: 70.0000
Return rate date: original source rate date
```

## E. Sales Return Evidence

Executed test: `Stage65ReturnTests.test_sales_return_uses_original_sale_cost_not_current_avco`.

```text
Original sale movement: SI-65
Customer:               Customer 65
Original sale quantity:  20 issued
Original recorded cost: AFN 12.0000/unit
Later receipt:          100 @ AFN 30.0000
Current AVCO differs from original sale cost
Return quantity:         10
Return movement:         SALES_RETURN, +10
Return cost:             AFN 12.0000
```

The original sales issue remains quantity `-20`; it is not edited. The return is an independent immutable inbound movement.

## F. Cost Preservation

Both return types use `source.unit_cost`, `source.currency`, `source.rate`, `source.rate_date`, and `source.is_temporary_cost`.

No current warehouse AVCO, reference price, market price, standard cost, or manually re-estimated cost is used when source cost exists.

The purchase test makes the difference observable: original cost `10.0000`, current AVCO `20.0000`; the return stores `10.0000`. The sales test makes the difference observable: original sale cost `12.0000`, later warehouse cost changes AVCO; the return stores `12.0000`.

## G. Partial / Full / Over Return

Executed test: `Stage65ReturnTests.test_partial_full_and_over_return`.

```text
Original quantity: 100
First return:      20
Second return:     80
Remaining:         0
Further return:    1 -> rejected
```

The remaining quantity is derived from `source.quantity - SUM(InventoryReturn.quantity)`. No mutable remaining counter or second stock balance was introduced.

The attempted over-return left movement, return-record, and audit counts unchanged.

## H. Source Validation

Executed test: `Stage65ReturnTests.test_source_party_product_warehouse_and_document_mismatch_rejected`.

Rejected cases:

- wrong supplier
- wrong product
- wrong warehouse
- wrong source document/reference

The source movement type is also checked: Purchase Return requires `PURCHASE_RECEIPT`; Sales Return requires `SALES_ISSUE`. Party role is checked against `is_supplier`/`is_customer`.

## I. Atomicity

Executed test: `Stage65ReturnTests.test_return_and_audit_roll_back_on_late_failure`.

`record_audit_event` was forced to raise after the movement and return record were attempted. Before/after counts for `StockMovement`, `InventoryReturn`, `AuditEvent`, and `IdempotencyRecord` were equal. No partial return state remained.

The operation uses the existing `transaction.atomic()` and idempotency primitives. No second transaction manager was added.

## J. Idempotency

Executed test: `Stage65ReturnTests.test_returns_are_idempotent_and_mismatch_rejected`.

- Exact retry with the same key/payload returned the original `InventoryReturn`.
- Only one return record and one return movement existed.
- Same key with changed quantity was rejected.
- Fingerprint includes operation type, source movement, party, product, warehouse, quantity, source document, posting date, description, and actor.

## K. Immutability

Executed test: `Stage65ReturnTests.test_return_and_source_are_immutable`.

- Posted `InventoryReturn.save()` rejected.
- Posted `InventoryReturn.delete()` rejected.
- Original source `StockMovement.save()` rejected.
- Original source transaction was not modified by return posting.

## L. Audit

Purchase Return basic evidence verifies an `InventoryReturn` audit row containing source movement id and return movement id. Movement audit is created through the existing `_create_movement()` path and contains quantity-before/after, cost/rate context, reference, description, and source party context.

No separate audit engine was introduced.

## M. Fiscal Period

Executed test: `Stage65ReturnTests.test_closed_period_rejects_return`.

A return dated in a closed fiscal period was rejected through the existing `assert_posting_date_open()` gate before posting any return movement.

No fiscal-period code was changed.

## N. Currency

The foreign purchase-return test verified that the source historical USD cost and `70.0000` rate were copied unchanged to the return movement. No current-rate recalculation or FX engine was introduced.

## O. Accounting Boundary

Accounting was deliberately deferred for Stage 6.5.

Phase 0 contains conceptual return mappings and COA identities (`4200`, `5200`) and describes payable/receivable and COGS return entries. However, this repository has no approved Purchase Invoice/Sales Invoice source transaction implementation, no source payable/receivable state for these returns, and no complete Purchase/Sales accounting workflow to which a return could safely attach.

Therefore this stage does not invent journal lines, payable/customer-credit behavior, COGS reversal, account mapping, or a second accounting engine. It implements the inventory-side immutable return foundation and preserves the source cost context. Accounting remains an explicit future boundary until its source transaction contract exists.

## P. SQLite

Executed from `backend/`:

```text
pytest inventory/inventory_tests.py -q
116 passed

pytest -q
688 passed

python manage.py test --verbosity 1
17 OK

python manage.py check
0 issues

python manage.py makemigrations --check --dry-run
No changes detected
```

## Q. PostgreSQL

Attempted:

```text
DJANGO_SETTINGS_MODULE=config.settings.postgres pytest inventory/inventory_tests.py -q
```

Actual result: unavailable in this environment. PostgreSQL connection to `127.0.0.1:5432` was refused during Django test-database setup. No PostgreSQL Stage 6.5 success is claimed.

Previously valid PostgreSQL evidence belongs to the earlier Stage 6.4 run and is not relabeled as a Stage 6.5 result.

## R. Migration

Fresh SQLite migration verification executed:

```text
forward all migrations
reverse inventory 0005 -> 0003
forward inventory 0003 -> 0005
```

Result: **OK**.

## S. Frozen Surface

The implementation diff contains only inventory code/tests/migrations and this report. No files under accounting, fiscal_periods, parties, categories, uom, products, warehouses, cash_accounts, exchange_houses, currencies, documents, security, core, frontend, `.github`, or scripts were added to the Stage 6.5 change.

The four pre-existing modified `scripts/verify_*.sh` files remain outside the Stage 6.5 commit and were not reset or edited.

## T. Git

The Stage 6.5 implementation commit is:

```text
da47273040d332cfb409368e2d5c168fd9890e8a
parent: 4820844509c59578e40c6fe2d9b2e715516dfc7e
subject: feat(inventory): implement Stage 6.5 returns
```

The final evidence-gap closure is a separate narrow test/evidence commit created after the PostgreSQL attempt and final SQLite runs. Its exact hash, parent, subject, changed files, and final working-tree state are reported in the final response from direct Git inspection. The four pre-existing script mode changes remain outside both commits.

## U. Limitations

- PostgreSQL 17 execution was unavailable in this environment; SQLite results are current and PostgreSQL success is not claimed.
- Purchase Invoice and Sales Invoice domains do not yet exist. The source identity is therefore the existing immutable source movement reference plus source party metadata.
- Return accounting, payable/receivable settlement, customer credit, supplier advance, and COGS reversal remain deferred until their source transaction contracts are implemented.

**Stage 6.5 implementation and evidence completed — awaiting user review.**
