# Phase 7 — Stage 7.7 Evidence
## Purchase Final Boundary, Regression & Integration Hardening

**Date:** 2026-09-19  
**Branch:** `phase/4`  
**Starting HEAD:** `c521fb4b6194330142c77bcefd9e9d9795f601d9`  
**Ending HEAD:** `c521fb4b6194330142c77bcefd9e9d9795f601d9`  
**Status:** IMPLEMENTED / TESTED  
**SQLite:** EXECUTED  
**PostgreSQL:** BLOCKED / NOT EXECUTED

## Scope

Stage 7.7 performed final operational boundary inspection and targeted regression hardening for the existing Purchase workflow. It did not introduce a new Purchase engine or alter the accounting, inventory, party-ledger, currency, fiscal-period, audit, or idempotency primitives.

The tested boundary is:

```text
DRAFT
  → validated draft update
  → final validation
  → atomic posting
  → JournalEntry / payable / attribution / receipt
  → POSTED immutable history
```

Payments, settlement, sales, tax, UI, reporting, reversal/correction, and Phase 8 remain out of scope.

## Starting state and working tree

Before implementation, the repository was inspected with:

```text
$ git status --short
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? backend/purchases/
?? docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.3_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.4_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.5_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.6_IMPLEMENTATION_EVIDENCE.md

$ git rev-parse HEAD
c521fb4b6194330142c77bcefd9e9d9795f601d9

$ git branch --show-current
phase/4
```

The pre-existing Phase 6/settings and Phase 7.1–7.6 working-tree work was preserved.

## Inspection findings

### Purchase state machine

`PurchaseStatus` contains exactly `DRAFT` and `POSTED`. No hidden intermediate financial state was found. `create_purchase()` creates a DRAFT. `post_purchase()` locks the row, rejects non-DRAFT/non-valid states, runs `validate_purchase()` immediately before effects, then changes the Purchase to POSTED in the same transaction as the posting effects.

`Purchase.save()` and `Purchase.delete()` reject modifications/deletion after POSTED. `PurchaseLine.save()` and `PurchaseLine.delete()` apply the same posted-history boundary. Stage 7.6's `update_purchase()` and `update_purchase_line()` reject non-DRAFT edits.

### Financial boundary

Draft creation and validated draft updates create only commercial document state and ordinary CREATE/UPDATE audit events. They do not call `post_journal()`, `receive_stock()`, or `attribute_journal_line()` and do not reserve financial idempotency.

Before posting, the Stage 7.7 draft-safety regression asserts zero JournalEntry, zero JournalLine, zero StockMovement, zero PartyLedgerAttribution, and no Purchase POST audit event.

### Inventory boundary

Purchase posting calls the existing `receive_stock()` primitive once per PurchaseLine. No Purchase-specific stock engine or direct stock mutation was found. Receipt references are deterministic and line-level:

```text
{document_number}:LINE:{purchase_line_id}
```

The final-state and repeated-product tests prove that product and warehouse identity come from the final draft and that repeated products retain separate line references.

### Supplier payable boundary

Purchase posting uses existing account `2110`, then calls `attribute_journal_line()` for the payable JournalLine. Party balances remain derived from the existing PartyLedgerAttribution path. No Purchase-specific payable ledger or balance engine was found.

### Currency boundary

AFN and foreign-currency posting continue through the existing currency/rate/money helpers. JournalEntry and StockMovement retain the original transaction currency, historical exchange rate, and rate date. Journal AFN equivalent and movement AFN unit cost are stored by the existing accounting/inventory primitives.

### Fiscal boundary

`post_journal()` and Purchase posting use the existing fiscal-period gate. Closed-period posting is rejected before effects and leaves the Purchase DRAFT. Draft creation/update is not treated as posting.

### Idempotency boundary

Purchase posting uses the existing `idempotent_operation()` primitive, with the Purchase operation record and the existing journal/inventory idempotency mechanisms. Exact retry resolves the original result. Reuse with a different Purchase fingerprint is rejected. No second journal, receipt, attribution, POST audit, or financial effect is created.

### Historical integrity

Posted Purchase, PurchaseLine, JournalEntry, JournalLine, StockMovement, and PartyLedgerAttribution records retain their existing immutability protections. Generic `accounting.services.reverse_journal()` remains a generic journal operation and was not integrated into Purchase posting or Purchase correction.

### Return boundary

The existing inventory return architecture was inspected. `purchase_return()` is a separate immutable inventory event linked to an original `PURCHASE_RECEIPT`, with original movement cost/rate context. Purchase posting does not mutate source movements and does not invoke return behavior. No new return test was necessary for this Purchase boundary increment because the existing Phase 6 inventory return tests cover the return contract.

## Changes

### Production code

No production code was changed for Stage 7.7. The validated draft update implementation from Stage 7.6 remains the authoritative edit path.

### Tests

Added four focused Stage 7.7 regressions to `backend/purchases/purchase_tests.py`:

1. `test_stage77_draft_creation_has_only_commercial_and_create_audit_effects`
2. `test_stage77_multiline_repeated_product_retry_preserves_line_traceability`
3. `test_stage77_late_failure_rolls_back_all_purchase_posting_effects`
4. `test_stage77_posted_purchase_rejects_draft_update_service`

These complement the existing Stage 7.1–7.6 Purchase tests for final validation, edited final-state posting, AFN/foreign reconciliation, freight, discount allocation, closed periods, exact retry, changed-key rejection, atomicity, audit, attribution, and posted immutability.

### Documentation

Corrected one factual Stage 7.5 evidence inconsistency: its file-change section said two reconciliation tests, while the document and executed focused result identify three. The correction was limited to that statement; historical architecture and results were not rewritten.

Created this Stage 7.7 evidence document.

### Migrations

No migration was added or required.

## Regression evidence

### Draft safety

`test_stage77_draft_creation_has_only_commercial_and_create_audit_effects` proves a newly created DRAFT has its Purchase CREATE audit event but no JournalEntry, JournalLine, StockMovement, PartyLedgerAttribution, or POST audit event.

Existing Stage 7.6 tests prove validated draft updates recalculate line totals, discount allocation, subtotal, freight, and final total without financial effects.

### Final-state posting

`test_stage76_draft_edit_recalculates_and_posts_only_final_state` changes supplier, product, warehouse, currency, rate, rate date, discount, freight, and description before posting. It proves the posted JournalEntry, payable attribution, StockMovement, movement rate, product, and warehouse use the final persisted draft state.

### Failed posting atomicity

`test_stage77_late_failure_rolls_back_all_purchase_posting_effects` injects a failure at `receive_stock()` while posting with an idempotency key. After the exception it asserts:

- Purchase remains DRAFT;
- `posted_at` remains null;
- zero JournalEntry;
- zero JournalLine;
- zero StockMovement;
- zero PartyLedgerAttribution;
- no Purchase POST audit event;
- no surviving idempotency record.

The existing final-validation regression separately mutates a draft into an inconsistent state and proves rejection before financial effects.

### Closed period

The existing `test_closed_fiscal_period_rejects_purchase_without_posting_side_effects` asserts DRAFT status, no journal, no movement, no attribution, no POST audit, and no successful idempotency record after closed-period rejection. Draft creation and update are independently covered as non-financial operations.

### Multi-line and repeated product

`test_stage77_multiline_repeated_product_retry_preserves_line_traceability` posts three lines, including the same product on two separate lines, with discount and freight. It retries the same idempotency key and proves:

- three unique deterministic line references;
- exactly three StockMovements;
- one JournalEntry;
- three JournalLines, including freight;
- one PartyLedgerAttribution;
- one Purchase POST audit event;
- one idempotency record;
- final stock quantities of 5 and 4 for the two products.

No repeated-product lines are merged.

## Accounting evidence

The tested chain remains:

```text
Purchase
  → post_journal()
  → JournalEntry / JournalLine
  → account 2110 Trade Payables
  → attribute_journal_line()
  → PartyLedgerAttribution
```

Existing Stage 7.5 tests assert AFN and foreign-currency commercial totals, inventory debit, freight debit to `6200`, payable credit to `2110`, AFN equivalent, and derived supplier balance. Stage 7.7 retry tests prove the chain is not duplicated.

## Inventory evidence

The tested chain remains:

```text
PurchaseLine
  → receive_stock()
  → StockMovement
  → AVCO / stock derived from movement history
```

Final-state and repeated-product tests prove final product/warehouse identity, deterministic line-level references, separate repeated-product movements, and no duplicate movements on retry. No direct Purchase stock ledger was introduced.

## Currency evidence

Existing Stage 7.5 tests cover:

- AFN purchase amount and AFN movement context;
- foreign-currency original amount;
- historical rate and rate date;
- JournalEntry AFN equivalent;
- StockMovement historical currency/rate context;
- AFN movement unit cost.

Stage 7.6 additionally proves that a changed draft rate and rate date are the values used by the final posted JournalEntry and StockMovement.

## Idempotency evidence

Existing exact retry and changed-key coverage, together with the Stage 7.7 repeated-product retry test, proves:

- same key and same Purchase returns the original posting result;
- no duplicate JournalEntry;
- no duplicate JournalLines;
- no duplicate StockMovements;
- no duplicate PartyLedgerAttribution;
- no duplicate POST audit;
- same key with a different Purchase is rejected.

The late-failure regression proves a failed transaction does not leave a successful idempotency record.

## Historical integrity evidence

Existing Stage 7.4 coverage exercises immutability of Purchase, PurchaseLine, JournalEntry, JournalLine, StockMovement, and PartyLedgerAttribution, including save and delete protections. Stage 7.7 adds explicit rejection of the Stage 7.6 draft update service once a Purchase is POSTED.

No Purchase reversal/correction workflow was added. Generic journal reversal remains distinct from a complete Purchase correction and does not alter the original Purchase model state.

## Exact test results

### Focused Purchase suite

```text
$ cd backend && .venv/bin/pytest -q purchases/purchase_tests.py
......................                                                   [100%]
22 passed in 1.56s
```

### Full backend suite

```text
$ cd backend && .venv/bin/pytest -q
719 passed, 2 skipped in 84.72s (0:01:24)
```

The two skipped tests remain existing PostgreSQL/Phase 6 concurrency debt and are not counted as executed successes.

### Django check

```text
$ cd backend && .venv/bin/python manage.py check
System check identified no issues (0 silenced).
```

### Migration check

```text
$ cd backend && .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected
```

### Diff check

```text
$ git diff --check
# clean; no output
```

## PostgreSQL

```text
PostgreSQL verification: BLOCKED / NOT EXECUTED
Reason: PostgreSQL was unavailable at the known endpoint 127.0.0.1:5432.
```

SQLite execution above is not presented as PostgreSQL evidence.

The Phase 6 pending command remains:

```bash
python manage.py test inventory.inventory_tests.Stage6ConcurrencyTests --verbosity 2
```

It was not claimed as executed or resolved.

## Git and protected surfaces

Ending HEAD remains:

```text
c521fb4b6194330142c77bcefd9e9d9795f601d9
```

The final working tree remains:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? backend/purchases/
?? docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.3_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.4_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.5_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.6_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.7_IMPLEMENTATION_EVIDENCE.md
```

`git diff --stat` continues to show only tracked pre-existing changes because the Purchase directory and Phase 7 evidence files are untracked working-tree work:

```text
 backend/config/settings/base.py                    |   2 +-
 .../PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md   | 105 +++++++++++++++++++++
 2 files changed, 106 insertions(+), 1 deletion(-)
```

Protected and unchanged:

- Phase 0 contracts;
- Accounting Core and `post_journal()`;
- Fiscal Periods;
- Master Data;
- Party Ledger and `attribute_journal_line()`;
- money/currency helpers;
- Inventory `receive_stock()`, StockMovement, returns, and AVCO;
- audit and idempotency primitives;
- Purchase reversal/correction boundary;
- Phase 6 concurrency architecture.

No reset, clean, stash, rebase, amend, force-push, merge, commit, freeze, or history rewrite was performed.

## Remaining debt

- PostgreSQL Purchase verification is blocked/not executed.
- Phase 6 PostgreSQL concurrency verification remains pending.
- Phase 7.1–7.6 remain uncommitted working-tree work.
- Direct low-level ORM mutation of DRAFT objects can still bypass service-level recalculation; the validated update services and final posting validator are the authoritative application boundary. Expanding protection against arbitrary low-level ORM writes would require a separate contract decision.

## Phase 7 readiness

Stage 7.7 evidence is sufficient to proceed to **Comprehensive Phase 7 Review**. This is not a Phase 7 freeze or approval declaration. Phase 7 remains unfrozen pending explicit user review and approval.

## Stop condition

Stage 7.7 stops after evidence. No Phase 7 freeze, merge, tag, approval, Phase 8 work, payment, sales, tax, or Purchase reversal/correction work was started.
