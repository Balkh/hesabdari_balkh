# Phase 7.1 — Purchase Foundation + Purchase Receipt Evidence

## Status

Phase 7.1 is **IMPLEMENTED** and SQLite-tested. PostgreSQL evidence is **BLOCKED**
because the verification environment has no reachable PostgreSQL server at
`127.0.0.1:5432`. Phase 6 remains unfrozen and its PostgreSQL concurrency debt
remains unchanged.

This document does not freeze Phase 6 or Phase 7.1 and does not claim PostgreSQL
verification from SQLite.

## Baseline and implementation

- Branch: `phase/4`
- Baseline HEAD: `c521fb4b6194330142c77bcefd9e9d9795f601d9`
- Baseline purpose: Phase 6 concurrency locking and `TransactionTestCase` fixture correction
- Implementation commit: not committed; awaiting user review
- Working-tree documentation already present before this stage:
  `docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md`

## Contract implemented

Phase 7.1 implements the smallest Purchase foundation and receipt workflow:

```text
DRAFT Purchase
    ↓ post
Purchase journal + supplier payable attribution
    ↓
Purchase receipt StockMovement per line
    ↓
AVCO replay from canonical movements
    ↓
POSTED immutable Purchase
```

Implemented business rules:

- Purchase has a supplier, date, currency/rate context, warehouse, description,
  discount, freight, total, status, actor, and timestamps.
- Purchase has one or more Product lines with positive integer quantity and
  4-decimal unit price.
- Supplier must be an active existing `Party` with `is_supplier=True`.
- Product and Warehouse must be existing and active.
- Foreign-currency purchases require a positive rate and rate date; AFN uses rate
  `1.0000` and the purchase date as its rate date.
- Discount reduces inventory purchase cost.
- Multi-line discount allocation is proportional, deterministic, and conserves
  the full discount amount by assigning the final rounding remainder to the last
  line.
- Freight is posted as V1 expense to the existing `6200 Freight & Transport`
  account and is not included in inventory unit cost.
- Inventory is posted through existing `receive_stock()` only.
- The existing warehouse inventory account mapping is reused for the inventory
  debit.
- The existing `2110 Trade Payables` mapping is reused for the supplier payable
  credit.
- The payable journal line is attributed through the existing
  `attribute_journal_line()` service.
- Journal, inventory receipt, party attribution, audit, Purchase status change,
  and idempotency state occur inside one posting transaction.
- Exact post retries reuse the original Purchase; reuse of an idempotency key for
  a different Purchase is rejected.
- Posted Purchase and PurchaseLine records are immutable and cannot be deleted.
- Posting uses the existing fiscal-period gate.

Explicitly not implemented: payments, partial payments, payment allocation,
exchange-house settlement, tax, advanced landed cost, sales, reporting, printing,
frontend UI, approval workflow, new supplier master, or any second accounting,
inventory, AVCO, audit, currency, or idempotency engine.

## Changed files

- `backend/config/settings/base.py` — registers the new `purchases` app.
- `backend/purchases/apps.py` — Django app configuration.
- `backend/purchases/models.py` — `Purchase`, `PurchaseLine`, and posted-state
  immutability.
- `backend/purchases/services.py` — validation, deterministic discount allocation,
  atomic posting, journal/party attribution, receipt creation, audit, and
  idempotency.
- `backend/purchases/purchase_tests.py` — focused Stage 7.1 tests.
- `backend/purchases/migrations/0001_initial.py` — Purchase schema.
- `docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md` — this report.

The pre-existing Phase 6 evidence addendum was not rewritten as part of the Stage
7.1 evidence update.

## Focused SQLite tests

Command:

```text
pytest -q purchases/purchase_tests.py
```

Actual result:

```text
10 passed in 1.21s
```

The focused tests cover:

- valid Purchase and deterministic multi-line discount allocation;
- supplier-role and quantity validation;
- receipt creation and warehouse/Product association;
- AVCO and historical unit cost;
- payable journal and supplier attribution;
- freight expense treatment;
- foreign-currency/rate preservation;
- exact idempotent retry and changed-key rejection;
- late receipt failure rollback of journal and stock;
- posted Purchase and line immutability;
- missing foreign rate rejection;
- closed fiscal-period rejection with no Purchase journal, StockMovement,
  PartyLedgerAttribution, posting audit, or idempotency record left behind.

## Full SQLite/backend regression

Command:

```text
pytest -q
```

Actual result:

```text
707 passed, 2 skipped in 85.83s (0:01:25)
```

The two skipped tests are the existing PostgreSQL-specific Phase 6 concurrency
regression tests under `Stage6ConcurrencyTests`. They were not treated as
PostgreSQL evidence.

## PostgreSQL

Status: **BLOCKED / NOT TESTED**.

The required PostgreSQL server remains unavailable at `127.0.0.1:5432`, so no
Stage 7.1 PostgreSQL tests were executed and no PostgreSQL result is claimed.
The Phase 6 PostgreSQL concurrency verification debt remains:

```text
python manage.py test inventory.inventory_tests.Stage6ConcurrencyTests --verbosity 2
```

## Structural checks

Executed with the SQLite test settings:

```text
python manage.py check --settings=config.settings.test
System check identified no issues (0 silenced).

python manage.py makemigrations --check --dry-run --settings=config.settings.test
No changes detected
```

## Integrity evidence

- Accounting: the existing `post_journal()` path posts balanced inventory,
  freight, and payable lines using existing accounts `1410`/warehouse mapping,
  `6200`, and `2110`; focused tests verify debit/credit totals and attribution.
- Inventory: existing `receive_stock()` creates `PURCHASE_RECEIPT` movements;
  `StockMovement` remains the sole stock truth and AVCO remains derived by the
  existing replay implementation.
- Currency: transaction currency, rate, rate date, and AFN-equivalent movement
  context are preserved; foreign-rate requirement is tested.
- Idempotency: exact post retry and changed-key rejection are tested.
- Atomicity: an injected late receipt failure was tested to roll back the
  journal and stock effects while leaving the Purchase draft.
- Audit: Purchase creation/posting, journal posting, party attribution, and
  inventory movement continue through existing audit infrastructure; focused
  tests verify Purchase audit presence.
- Immutability: posted Purchase and PurchaseLine mutation/deletion rejection is
  tested, and historical StockMovement immutability remains delegated to the
  existing model.
- Fiscal period: posting calls the existing `assert_posting_date_open()` gate;
  the dedicated closed-period Stage 7.1 test executed and verified rejection,
  draft preservation, and absence of journal, movement, attribution, audit-post,
  and idempotency side effects.

## Protected-surface verification

No Phase 2–5 source files were changed. Existing accounting, party ledger,
fiscal-period, product, warehouse, currency, inventory, AVCO, audit, and
idempotency implementations were reused. Phase 6 inventory files were not
modified.

## Final working-tree state at evidence capture

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? backend/purchases/
?? docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
```

No commit, merge, rebase, squash, amend, force-push, tag, release, or freeze was
performed. Stage 7.2 was not started.
