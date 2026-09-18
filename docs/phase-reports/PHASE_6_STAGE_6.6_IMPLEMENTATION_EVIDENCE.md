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

## Out of Scope

Not implemented:

- Sales Invoice or Sales Invoice Line;
- invoice numbering, prices, discounts, taxes;
- payments, AR, customer credit, credit limits;
- revenue, COGS, FX, or other accounting journals;
- new AVCO, audit, idempotency, stock, or FX engine;
- API, UI, reporting, commissions, salesperson workflows;
- Phase 7 or Stage 6.6 follow-on work.
