# Phase 6 — Stage 6.6 Customer Dispatch / Sales Issue Evidence

Status: **Stage 6.6 implementation and evidence complete — awaiting user review.**

Stage 6.6 and Phase 6 are not frozen. No merge, tag, release, or Phase 7 work was started.

## Baseline

- Branch: `phase/4`
- Starting HEAD: `df0463e129e51ec01e1f749639c7806accd7fc34`
- Stage 6.5 implementation: `da47273040d332cfb409368e2d5c168fd9890e8a`
- Stage 6.5 final gap closure: `df0463e129e51ec01e1f749639c7806accd7fc34`
- Pre-existing working-tree changes: mode changes in four `scripts/verify_*.sh` files. They were not reset, edited, or staged.

## Inspection and Decision

`issue_stock()` already provided the Stage 6.6 stock-side behavior: signed `SALES_ISSUE` OUT movement, existing AVCO/temporary-cost logic, negative-stock acknowledgement, immutable `StockMovement`, audit, idempotency, and movement transaction handling.

There was no full Sales/Dispatch implementation. No new Dispatch model was necessary. The smallest missing business semantic was a customer-attributed wrapper:

```text
customer_dispatch()
    -> validate Party.is_customer
    -> validate nonblank description
    -> existing issue_stock(..., party=customer)
```

The wrapper stores customer context in the existing `StockMovement.source_party` field, which is already used by Stage 6.5 source traceability. No second ledger, source document model, price model, invoice model, or accounting workflow was introduced.

## Implementation

Changed files:

- `backend/inventory/services.py`
  - added `customer_dispatch()` only;
  - reuses `_resolve_party()`, `_clean_description()`, `assert_posting_date_open()`, and `issue_stock()`.
- `backend/inventory/inventory_tests.py`
  - added nine focused Stage 6.6 tests.
- `docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md`

No migration was required. No protected Phase 2–5 surface was changed.

## Focused Evidence

The focused inventory test suite passed **125 tests** on both engines.

Coverage includes:

- valid customer dispatch: `SALES_ISSUE`, `-20`, stock `100 -> 80`;
- customer role rejection for supplier-only Party;
- required dispatch description;
- warehouse isolation;
- existing cost/AVCO behavior and no reference-price substitution;
- exact idempotent retry and changed-payload rejection;
- late audit failure rollback of movement, audit, and idempotency state;
- posted movement edit/delete rejection;
- closed fiscal-period rejection with no mutation;
- existing negative-stock acknowledgement and temporary-cost behavior;
- Stage 6.5 compatibility: dispatch source can be used by `sales_return()`, and return cost remains the dispatch source cost.

The dispatch audit evidence is produced through the existing `_create_movement()` → `record_audit_event()` path and includes the existing movement snapshot, including source party, signed quantity, stock before/after, cost context, reference, and description.

## Accounting Boundary

No accounting was implemented for Stage 6.6:

- no revenue journal;
- no COGS journal;
- no AR/customer-credit journal;
- no FX journal;
- no new account mapping.

The full Sales Invoice and financial settlement contracts do not exist. Phase 0 conceptual mappings were not treated as permission to invent a Sales accounting workflow.

## SQLite Evidence

Executed from `backend/`:

```text
pytest inventory/inventory_tests.py -q
125 passed

pytest -q
697 passed

python manage.py check
System check identified no issues (0 silenced).

python manage.py makemigrations --check
No changes detected

python manage.py test --verbosity 1
17 OK
```

## PostgreSQL 17.11 Evidence

Executed with `DJANGO_SETTINGS_MODULE=config.settings.postgres`:

```text
pytest inventory/inventory_tests.py -q
125 passed in 11.06s

pytest -q
697 passed in 102.04s

python manage.py check
System check identified no issues (0 silenced).

python manage.py makemigrations --check
No changes detected
```

PostgreSQL version: `17.11 (Debian 17.11-0+deb13u1)`.

## Git Scope

The four pre-existing script mode changes remain outside the Stage 6.6 commit. No unrelated or protected files were staged.

The final Stage 6.6 commit hash, parent, subject, changed files, and final working-tree state are recorded after the evidence commit in the final response.


## Phase 6 Concurrency Fix Evidence Addendum

This addendum documents the two concurrency/root-cause fixes present on the canonical
Phase 6 branch `fix/phase6-stock-concurrency` at commit
`c521fb4b6194330142c77bcefd9e9d9795f601d9` (`test(inventory): initialize concurrency transaction fixtures`).
This is documentation only. No production inventory implementation was changed for
this addendum.

### Fix 1 — Concurrent stock mutation race

The original mutation flow could read current stock for a Product + Warehouse,
validate against that value, and then create a StockMovement without serializing the
canonical stock identity. Two concurrent issues could therefore validate against the
same stock snapshot and both pass negative-stock validation.

The canonical service correction serializes the Product + Warehouse identity with
`select_for_update()`. `_lock_stock_identity(product, warehouse)` locks the Product
and Warehouse rows, while `_lock_stock_identities(product, *warehouses)` locks the
Product and multiple Warehouse rows in deterministic order. The locks are acquired
before stock calculation in the affected mutation paths, including:

- `issue_stock()`;
- `open_stock()`;
- `transfer_stock()` source and destination;
- adjustment operations;
- movement creation and related stock mutation flows.

The existing immutable StockMovement ledger remains the sole inventory truth:

```text
SUM(StockMovement.quantity) per Product + Warehouse
```

No second stock ledger or concurrency engine was introduced. For 100 units and two
concurrent 80-unit issues, the intended result is one success, one existing
`InventoryValidationError`, and final stock of 20. Negative stock still requires the
existing explicit acknowledgement path.

### Fix 2 — Concurrent purchase-return over-return race

Purchase Return originally validated remaining returnable quantity against the source
StockMovement without serializing that source row. Two concurrent 40-unit returns
against a 50-unit purchase could therefore both observe the same remaining quantity.

The canonical return posting path now locks the source StockMovement with
`select_for_update()` before calculating remaining returnable quantity and creating
the `InventoryReturn` and return movement. Existing validation remains authoritative
and no second return ledger was introduced:

```text
InventoryReturn
    ↓
source StockMovement
    ↓
return StockMovement
```

For a 50-unit purchase and two concurrent 40-unit returns, the intended result is one
success, one existing `InventoryValidationError`, total returned quantity of 40, and
remaining stock of 10.

### PostgreSQL regression coverage

`backend/inventory/inventory_tests.py` contains the PostgreSQL-specific
`Stage6ConcurrencyTests` class with two regression tests:

1. concurrent 80-unit issues against 100 units, asserting one success, one
   `InventoryValidationError`, final stock of 20, and one `SALES_ISSUE` movement;
2. concurrent 40-unit purchase returns against a 50-unit purchase, asserting one
   success, one `InventoryValidationError`, total returned quantity of 40, and final
   stock of 10.

These tests intentionally require PostgreSQL row-locking semantics. SQLite execution
alone is not sufficient evidence for these guarantees.

### Test infrastructure correction

`Stage6ConcurrencyTests` uses `TransactionTestCase`. Unlike the ordinary `TestCase`
fixture path, `TransactionTestCase` does not invoke the shared
`InventoryFixture.setUpTestData()` initialization in the same way. The canonical
branch therefore gives the concurrency class its own `setUp()` initialization for:

- the chart of accounts;
- AFN and USD currencies;
- the test user;
- inherited per-test inventory fixture data.

This is a test-fixture correction only. It is not an inventory or business-logic fix.

### Verification status

The existence of the implementation and regression tests is documented here, but
these concurrency fixes are **not marked PASS, VERIFIED, COMPLETE, GREEN, or FROZEN**
by this addendum. Final evidence requires actual execution and recording of:

1. PostgreSQL concurrency tests;
2. the full PostgreSQL Inventory test suite;
3. the full SQLite Inventory test suite;
4. `python manage.py check`;
5. `python manage.py makemigrations --check --dry-run`.

No test counts or results are asserted here because those commands were not executed
as part of this documentation-only update.

## Out of Scope

Not implemented:

- Sales Invoice or Sales Invoice Line;
- invoice numbering, prices, discounts, taxes;
- payments, AR, customer credit, credit limits;
- revenue, COGS, FX, or other accounting journals;
- new AVCO, audit, idempotency, stock, or FX engine;
- API, UI, reporting, commissions, salesperson workflows;
- Phase 7 or Stage 6.6 follow-on work.
