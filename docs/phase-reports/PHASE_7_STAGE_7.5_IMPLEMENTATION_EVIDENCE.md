# Phase 7 — Stage 7.5 Implementation Evidence
## Purchase Financial Integrity, Supplier Payable & Reconciliation

**Date:** 2026-09-19  
**Status:** Implemented as regression coverage only; user review required  
**Branch:** `phase/4`  
**Commit:** `c521fb4b6194330142c77bcefd9e9d9795f601d9`  
**PostgreSQL:** BLOCKED / NOT TESTED

## Scope and implementation decision

Stage 7.5 inspection found that the existing Purchase implementation already uses the required authoritative systems and satisfies the financial-integrity contract. No production code, schema, accounting structure, inventory structure, payable system, or reversal/correction workflow was added.

Three focused Stage 7.5 regressions were added to `backend/purchases/purchase_tests.py`:

- `test_stage75_afn_purchase_reconciles_inventory_freight_and_payable`
- `test_stage75_foreign_purchase_preserves_amount_rate_and_afn_reconciliation`
- `test_full_discount_is_permitted_but_over_discount_is_rejected`

These tests make the existing reconciliation explicit for both AFN and foreign-currency purchases, including inventory net cost, freight expense, payable account `2110`, AFN equivalent, StockMovement/AVCO cost, and derived supplier payable balance.

The authoritative Stage 7.4 decision remains unchanged: Purchase reversal/correction is not implemented in Stage 7.5, and Purchase Return is not used as a substitute.

## Authoritative reconciliation proven

The tests and existing Stage 7.1–7.4 coverage prove the following without creating a second financial truth:

| Concern | Authoritative behavior/evidence |
|---|---|
| Commercial total | `Purchase.subtotal` is gross line total; allocated discount is subtracted; freight is added to `Purchase.total`. |
| Net inventory cost | Purchase posting debits inventory using each line's `net_total`; StockMovement and AVCO use the net acquisition cost. |
| Freight | Freight is posted separately to existing expense account `6200`; it is excluded from StockMovement unit cost and AVCO. |
| Supplier payable | The purchase payable is the existing journal credit on account `2110`; it is attributed through immutable `PartyLedgerAttribution`. |
| AFN purchase | Example: gross 10,000 − discount 500 + freight 1,000 = 10,500; inventory debit 9,500, freight debit 1,000, payable credit 10,500, stock/AVCO unit cost 95. |
| Foreign currency | Example: gross 1,000 USD − discount 50 + freight 20 = 970 USD at rate 70; journal AFN equivalent is 67,900 and inventory AFN unit cost is 6,650 for the 95 USD net unit cost. |
| Historical currency context | Journal and StockMovement retain the purchase currency, rate, and rate date; no current-rate recomputation is introduced. |
| Discount allocation | `_allocate()` deterministically allocates discount across lines with final-line remainder handling; existing tests cover proportional allocation, multiple lines, and repeated products. |
| Party ledger | Payable attribution and derived supplier balance are checked against exactly the posted payable effect; no parallel supplier ledger is introduced. |

## Existing contract coverage retained

The full Purchase suite continues to cover:

- deterministic multi-line discount allocation;
- multiple-line and repeated-product receipt references;
- zero discount/freight paths;
- permitted discount validation and discount bounds;
- freight separation from inventory/AVCO;
- exact idempotent retry;
- changed-payload idempotency rejection;
- late receipt failure atomic rollback;
- fiscal-period/closed-period rejection;
- audit and attribution behavior;
- historical foreign-currency/rate context;
- posted Purchase and posted-history immutability.

No Purchase reversal/correction behavior was added.

## Verification results

Commands were run from the repository's existing virtual environment.

### Focused Purchase tests

```text
$ cd backend && .venv/bin/pytest -q purchases/purchase_tests.py
................                                                         [100%]
16 passed in 2.26s
```

### Full backend suite

```text
$ cd backend && .venv/bin/pytest -q
713 passed, 2 skipped in 87.10s (0:01:27)
```

The two skipped tests remain separate pre-existing PostgreSQL/Phase 6 concurrency debt. They are not represented as passed.

### Django checks

```text
$ cd backend && .venv/bin/python manage.py check
System check identified no issues (0 silenced).
```

### Migration check

```text
$ cd backend && .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected
```

No migration was added or required.

### Diff whitespace check

```text
$ git diff --check
# passed; no output
```

## Atomicity, idempotency, fiscal gating, and immutability

These Stage 7.5 invariants remain enforced by the existing Purchase service and regression suite:

- posting is atomic across Purchase state, journal, inventory receipt, party attribution, audit, and idempotency effects;
- a late inventory/receipt failure leaves no partial journal, movement, attribution, audit, or idempotency result;
- exact retry returns the original result without duplicating financial or inventory effects;
- a changed payload using the same idempotency key is rejected;
- closed fiscal periods reject posting before financial side effects;
- posted Purchase history and posted accounting/inventory/party-ledger records remain immutable;
- `select_for_update()`, `post_journal()`, `receive_stock()`, `attribute_journal_line()`, fiscal-period services, audit, and idempotency primitives remain authoritative.

## Files changed for Stage 7.5

- `backend/purchases/purchase_tests.py` — added three reconciliation regression tests.
- `docs/phase-reports/PHASE_7_STAGE_7.5_IMPLEMENTATION_EVIDENCE.md` — this evidence document.

No production implementation files or migrations were changed for Stage 7.5.

## Protected surfaces and remaining debt

Protected and unchanged as systems of record:

- accounting JournalEntry/JournalLine and `post_journal()`;
- inventory `receive_stock()`, StockMovement, and AVCO replay;
- immutable `PartyLedgerAttribution` and derived supplier balances;
- money/currency and historical AFN conversion helpers;
- fiscal-period gates;
- audit and idempotency primitives;
- Phase 6 PostgreSQL concurrency work and its separate debt.

PostgreSQL was unavailable at `127.0.0.1:5432`; therefore no PostgreSQL claim is made. SQLite results above do not substitute for PostgreSQL execution. The existing Phase 6 PostgreSQL concurrency debt remains open.

## Working tree and history policy

Observed working tree includes the pre-existing uncommitted Phase 6/settings work and untracked Phase 7 Purchase/evidence files, including the prior Stage 7.1–7.4 artifacts. Those changes were preserved. No unrelated files were reset, cleaned, reverted, or cosmetically altered.

No commit, merge, rebase, squash, amend, force-push, reset, clean, stash, freeze, or history rewrite was performed.

## Stop point

Stage 7.5 stops here after evidence. User review is required. Phase 7.6 has not been started.
