# Phase 7.3 — Purchase Posting Traceability, Reconciliation & Document Integrity

## Status

**IMPLEMENTED / PARTIALLY TESTED**.

Stage 7.3 was exercised with SQLite focused and full regression tests. PostgreSQL
remains **BLOCKED / NOT TESTED** because no server is reachable at
`127.0.0.1:5432`.

Stage 7.3 is not frozen. Phase 7 is not frozen. Stage 7.4 was not started.

## Starting baseline

- Branch: `phase/4`
- Starting HEAD: `c521fb4b6194330142c77bcefd9e9d9795f601d9`
- Stage 7.1 and Stage 7.2 were uncommitted working-tree changes.
- Existing working-tree paths at inspection included the Stage 7.1/7.2 Purchase
  implementation, both prior evidence documents, the app registration, and the
  Phase 6 evidence addendum.

## Inspection findings

The existing Stage 7.1/7.2 implementation already provided:

- DRAFT → POSTED lifecycle;
- `Purchase` and `PurchaseLine` models;
- final draft validation through `validate_purchase()`;
- atomic posting through `_post_effects()`;
- row locking of the Purchase with `select_for_update()`;
- `post_journal()` as the accounting authority;
- `receive_stock()` as the inventory authority;
- `PartyLedgerAttribution` for supplier payable attribution;
- `assert_posting_date_open()` as the fiscal gate;
- existing audit and idempotency infrastructure;
- posted Purchase/PurchaseLine immutability;
- deterministic discount allocation and freight treatment.

The traceability gap was line-level identity: all receipt movements previously used
the Purchase document number alone. That was sufficient for document-level tracing
but ambiguous when multiple PurchaseLines existed, especially multiple lines for the
same Product.

## Implementation changes

Only the following Stage 7.3 behavior was added:

- `backend/purchases/services.py`
  - each receipt movement now uses the deterministic reference
    `PI-document:LINE:purchase-line-id`;
  - posting audit state now records the resulting journal ID/number and receipt
    movement IDs/references;
  - the existing accounting, inventory, audit, idempotency, fiscal, and party
    attribution services remain authoritative.
- `backend/purchases/purchase_tests.py`
  - added line-level traceability and posting-audit-effect coverage;
  - strengthened exact idempotent retry assertions for attribution and posting audit
    duplication.
- `docs/phase-reports/PHASE_7_STAGE_7.3_IMPLEMENTATION_EVIDENCE.md`
  - this report.

No model or migration change was required. No Phase 6 implementation was changed.
No duplicate ledger, AVCO engine, journal engine, audit system, or idempotency system
was introduced.

## Traceability results

The tested chain is:

```text
Purchase
  → PurchaseLine
  → Journal(source_type=PURCHASE, source_id=Purchase.document_number)
  → JournalLine(account=2110)
  → PartyLedgerAttribution(supplier)
  → PURCHASE_RECEIPT StockMovement(reference=Purchase:LINE:PurchaseLine)
```

The focused traceability test verifies for multiple lines, including two lines for
the same Product:

- one movement per PurchaseLine;
- deterministic line-specific movement reference;
- correct Product;
- correct Warehouse;
- correct signed quantity;
- historical discounted unit cost;
- journal source identity;
- supplier payable attribution;
- Purchase POST audit containing journal and movement effect references.

Stock truth remains the existing:

```text
SUM(StockMovement.quantity) per Product + Warehouse
```

## Reconciliation results

The existing Stage 7.1 contract was preserved and tested:

```text
Gross line totals
− allocated discount
= inventory receipt cost

inventory receipt cost
+ freight expense
= Purchase payable total
```

Verified behavior:

- discount allocation is proportional and deterministic;
- allocated discounts conserve the Purchase discount;
- net line totals conserve subtotal minus discount;
- journal inventory debit equals net inventory cost;
- freight is posted to existing account `6200`;
- freight is excluded from inventory unit cost and AVCO;
- payable credit equals final Purchase total;
- currency, exchange rate, rate date, and AFN-equivalent movement context remain
  historical snapshots.

No second rounding engine was introduced.

## Focused tests

Command:

```text
pytest -q purchases/purchase_tests.py
```

Actual result:

```text
12 passed in 1.31s
```

The focused suite covers Purchase validation, totals, discount conservation,
freight exclusion from inventory cost, currency preservation, line-level traceability,
Purchase-to-Journal traceability, supplier attribution, atomic late-failure rollback,
exact idempotent retry, changed-key rejection, closed-period rejection, and posted
immutability.

## Full regression

Command:

```text
pytest -q
```

Actual result:

```text
709 passed, 2 skipped in 86.85s (0:01:26)
```

The two skipped tests are the existing PostgreSQL-specific Phase 6 concurrency tests.
They are not PostgreSQL evidence.

## Structural checks

```text
python manage.py check --settings=config.settings.test
System check identified no issues (0 silenced).

python manage.py makemigrations --check --dry-run --settings=config.settings.test
No changes detected

git diff --check
passed
```

## Atomicity, idempotency, immutability, fiscal, and audit

- Atomicity: existing injected late receipt failure test confirms journal and stock
  effects roll back and the Purchase remains DRAFT.
- Idempotency: exact retry returns the original result without duplicate journal,
  StockMovement, PartyLedgerAttribution, or Purchase POST audit; changed-key reuse
  is rejected.
- Immutability: posted Purchase and PurchaseLine update/delete rejection remains
  tested through existing model guards.
- Fiscal gate: the existing closed-period test confirms rejection before journal,
  movement, attribution, posting audit, or idempotency side effects.
- Audit: Purchase creation and posting use existing AuditEvent infrastructure; the
  POST event now records journal and movement effect references.
- Concurrency: existing Purchase row locking and idempotency behavior were preserved;
  no speculative new lock architecture was added.

## PostgreSQL

```text
PostgreSQL: BLOCKED / NOT TESTED
```

No PostgreSQL tests were executed because PostgreSQL remains unavailable at
`127.0.0.1:5432`. SQLite results do not prove PostgreSQL row-locking behavior.

## Phase 6 concurrency debt

The existing Phase 6 debt remains open and unchanged:

```text
python manage.py test inventory.inventory_tests.Stage6ConcurrencyTests --verbosity 2
```

The two PostgreSQL-specific concurrency tests remain pending until an actual
PostgreSQL service is available.

## Protected surfaces

Unchanged:

- Phase 2 accounting core, COA, money, balances, posting integrity, and FX;
- Phase 3 fiscal-period implementation;
- Phase 4 master-data systems;
- Phase 5 PartyLedgerAttribution architecture;
- Phase 6 StockMovement, AVCO, returns, dispatch, adjustments, and concurrency
  locking.

No payments, settlement, tax, sales, reporting, printing, frontend, landed-cost,
new ledger, new GL, new audit system, new idempotency system, or Stage 7.4 work was
introduced.

## Working tree at evidence capture

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? backend/purchases/
?? docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.3_IMPLEMENTATION_EVIDENCE.md
```

## Commit and freeze status

```text
No commit created.
No merge performed.
No freeze performed.
```

Stage 7.3 implementation/evidence is complete for this increment. Waiting for USER
REVIEW. Stage 7.4 was not started.
