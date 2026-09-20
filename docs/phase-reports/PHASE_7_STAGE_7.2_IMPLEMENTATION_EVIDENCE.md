# Phase 7.2 — Purchase Review, Finalization & Business Integrity Evidence

## Status

Stage 7.2 is **IMPLEMENTED** and SQLite-tested. PostgreSQL is **BLOCKED / NOT
TESTED** because the verification environment has no reachable PostgreSQL server at
`127.0.0.1:5432`.

Phase 6 and Phase 7 are not frozen. Stage 7.3 was not started.

## Baseline

- Branch: `phase/4`
- HEAD/baseline: `c521fb4b6194330142c77bcefd9e9d9795f601d9`
- Stage 7.1 was uncommitted in the working tree before this increment.
- No commit was created for Stage 7.2.

## Implementation changes

Stage 7.1 already provided the DRAFT → POSTED lifecycle, posting transaction,
accounting/inventory trace references, idempotency, audit, fiscal gate, and posted
immutability. Stage 7.2 added only the missing final validation boundary:

- `backend/purchases/services.py`
  - added `validate_purchase()`;
  - revalidates supplier, warehouse, currency, rate, active Product lines,
    quantities, unit prices, line totals, discount allocations, subtotal, freight,
    and final total immediately before posting;
  - reuses the existing deterministic discount allocator;
  - runs before `assert_posting_date_open()` and before journal or inventory effects.
- `backend/purchases/purchase_tests.py`
  - added a regression test proving an inconsistent editable draft is rejected
    before posting side effects.
- `docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md`
  - this evidence report.

No models, migrations, Phase 6 files, accounting files, inventory files, or
protected Phase 2–5 files were changed for Stage 7.2.

## Contract and integrity coverage

The existing implementation continues to provide:

- explicit DRAFT and POSTED states;
- no inventory or journal effects for drafts;
- final validation before posting;
- deterministic discount allocation and conservation;
- freight as expense, not inventory cost;
- Purchase → `PURCHASE_RECEIPT` StockMovement traceability through the existing
  document reference;
- Purchase → Journal → `PartyLedgerAttribution` traceability;
- existing `post_journal()` and `receive_stock()` authorities;
- atomic posting across Purchase state, journal, attribution, inventory, audit, and
  idempotency;
- exact idempotent retry and changed-key rejection;
- posted Purchase and PurchaseLine immutability;
- authoritative `assert_posting_date_open()` gating;
- no duplicate inventory, accounting, AVCO, audit, or idempotency mechanism.

No speculative Purchase-specific database locking was introduced. Posting already
locks the Purchase row with `select_for_update()` and uses the existing idempotency
state checks.

## Focused tests

Command:

```text
pytest -q purchases/purchase_tests.py
```

Actual result:

```text
11 passed in 1.29s
```

The Stage 7.2-specific test proves that a draft whose line unit price is changed
without recomputing the stored line and header totals is rejected before any journal
or StockMovement is created.

Existing focused coverage also verifies discount conservation, freight treatment,
currency/rate preservation, accounting and inventory traceability, idempotency,
late-failure rollback, posted immutability, and closed-period rejection.

## Full regression

Command:

```text
pytest -q
```

Actual result:

```text
708 passed, 2 skipped in 86.49s (0:01:26)
```

The two skipped tests are the existing PostgreSQL-specific Phase 6 concurrency
regressions under `Stage6ConcurrencyTests`. They are not PostgreSQL evidence.

## Structural checks

```text
python manage.py check --settings=config.settings.test
System check identified no issues (0 silenced).

python manage.py makemigrations --check --dry-run --settings=config.settings.test
No changes detected
```

`git diff --check` completed without errors.

## PostgreSQL

```text
PostgreSQL: BLOCKED / NOT TESTED
```

No PostgreSQL test was run because the server remains unavailable at
`127.0.0.1:5432`. SQLite results do not establish PostgreSQL row-locking behavior.

The separate Phase 6 debt remains unchanged:

```text
python manage.py test inventory.inventory_tests.Stage6ConcurrencyTests --verbosity 2
```

## Protected surfaces and scope

- Phase 6 concurrency implementation was not modified.
- `StockMovement`, AVCO replay, returns, dispatch, fiscal infrastructure, and
  inventory services were reused unchanged.
- Phase 2–5 accounting, fiscal-period, Party, Product, Warehouse, currency, and
  party-ledger source files were not changed.
- No payment, settlement, tax, sales, reporting, printing, frontend, landed-cost,
  or Stage 7.3 work was performed.

## Working tree

At evidence capture:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? backend/purchases/
?? docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md
```

No commit, merge, rebase, squash, amend, force-push, or freeze was performed.
