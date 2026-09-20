# Phase 7 — Stage 7.6 Implementation Evidence
## Purchase Lifecycle, Editability & Posting Boundary Integrity

**Date:** 2026-09-19  
**Status:** IMPLEMENTED / TESTED  
**Branch:** `phase/4`  
**Starting HEAD:** `c521fb4b6194330142c77bcefd9e9d9795f601d9`  
**Ending HEAD:** `c521fb4b6194330142c77bcefd9e9d9795f601d9`  
**SQLite:** EXECUTED  
**PostgreSQL:** BLOCKED / NOT EXECUTED

## Inspection findings

The repository has exactly two Purchase lifecycle states: `DRAFT` and `POSTED`. The existing `create_purchase()` service creates a DRAFT and performs only commercial-document creation plus CREATE audit. The existing `post_purchase()` / `_post_effects()` service locks the Purchase, revalidates it immediately before posting, gates the date through the fiscal-period service, posts through `post_journal()`, attributes the payable through `PartyLedgerAttribution`, receives stock through `receive_stock()`, records POST audit, and changes the Purchase to POSTED in one transaction.

Before Stage 7.6, there was no Purchase draft-update service. Direct draft model saves could change fields without recalculating the denormalized totals or line allocations. That was a genuine lifecycle-boundary gap: the existing final validator protected posting, but there was no authoritative safe edit path for a prepared commercial document.

## Minimal implementation

Production changes were limited to `backend/purchases/services.py`:

- Added shared `_prepare_lines()` and `_totals()` helpers reused by creation and editing.
- Added `update_purchase()` for DRAFT-only edits of supplier, date, warehouse, currency, rate, rate date, description, discount, freight, and the complete line set.
- Added `update_purchase_line()` for DRAFT-only product, quantity, and unit-price edits.
- Both update paths resolve/validate master data, recalculate subtotal/discount allocation/net totals/freight/total, replace draft lines atomically, and record a normal `UPDATE` audit event.
- Neither update path calls accounting, inventory, party attribution, posting audit, fiscal posting, or financial idempotency.
- Posted Purchases remain rejected by the update service and by the existing model immutability boundary.

Regression coverage was added to `backend/purchases/purchase_tests.py`:

- `test_stage76_draft_edit_recalculates_and_posts_only_final_state`
- `test_stage76_line_edit_recalculates_draft_without_financial_effects`

No migration, new state, reversal, correction, payment, settlement, ledger, accounting engine, inventory engine, or frontend was added.

## Lifecycle contract

The verified boundary is:

```text
DRAFT → editable through validated update services → final validation → POSTED → immutable
```

There are no APPROVED, CANCELLED, VOID, REVERSED, SETTLED, PAID, or other Purchase states.

## Draft editability and no-side-effect evidence

The focused Stage 7.6 test changes a draft from:

- Supplier A to Supplier B;
- Product A to Product B;
- Warehouse A to Warehouse B;
- AFN to USD;
- rate 70-equivalent initial context to final rate 72 and a new rate date;
- original line values to final quantity/price;
- discount and freight values;
- description.

After editing, it asserts the final draft totals are recalculated from the final lines:

```text
subtotal = 400.00 USD
discount = 50.00 USD
net inventory cost = 350.00 USD
freight = 20.00 USD
total = 370.00 USD
```

Before posting, the test asserts zero JournalEntry, zero StockMovement, zero PartyLedgerAttribution, and no Purchase POST AuditEvent. Draft UPDATE audit is legitimate document history and is distinct from posting audit.

The line-specific edit test changes quantity and unit price through `update_purchase_line()`, verifies recalculated totals, and verifies no financial effects.

## Final validation and stale-draft boundary

`_post_effects()` obtains a row lock and calls the existing `validate_purchase()` immediately before fiscal gating and financial side effects. Existing regression `test_post_revalidates_inconsistent_draft_totals_before_side_effects` mutates a persisted draft line so its stored line total becomes inconsistent, then proves posting is rejected while the Purchase remains DRAFT and no JournalEntry or StockMovement exists.

This preserves the Stage 7.2 final-validation contract rather than weakening it or introducing another validator.

## Posting boundary and final-state effects

The final-state edit test posts only after the DRAFT has been updated. It proves:

- journal currency is USD and rate is 72.0000;
- payable account `2110` is credited with the final 370.00 USD total;
- StockMovement uses Product B and Warehouse B;
- movement unit cost is the final net line cost of 87.5000 USD;
- movement historical rate is 72.0000;
- PartyLedgerAttribution points to Supplier B;
- no attribution exists for Supplier A.

The existing posting chain remains authoritative:

```text
Purchase → post_journal() → JournalEntry/JournalLine 2110
         → attribute_journal_line() → PartyLedgerAttribution
         → receive_stock() → StockMovement/AVCO
```

## Accounting, inventory, party ledger, and currency

No accounting or inventory structures were changed. Existing tests continue to cover AFN and foreign-currency posting, freight as account `6200` and not inventory cost, payable account `2110`, historical currency/rate context, line-level receipt references, and AVCO derived from StockMovement.

The Stage 7.6 final-state test specifically proves the final supplier, product, warehouse, currency, rate, discount, freight, and totals—not stale pre-edit values—reach the posted financial event.

## Atomicity

The new update service uses the existing Django transaction primitive and row lock. It validates and prepares all replacement lines before changing the Purchase, then replaces the draft lines and audit event inside the same transaction. A validation failure therefore cannot leave a partially updated draft.

Existing Stage 7.1–7.5 coverage remains in force for late posting failure rollback across journal, stock, attribution, audit, idempotency, and Purchase status.

## Idempotency and lifecycle

Existing Purchase posting idempotency remains unchanged and is covered by the full suite:

- first successful post transitions DRAFT to POSTED;
- exact retry returns the original result;
- retry does not duplicate journal, movement, attribution, or POST audit;
- changed payload with the same idempotency key is rejected;
- a posted Purchase cannot be used to create another financial event through ordinary posting.

Draft updates do not reserve or create financial idempotency records.

## Fiscal gate

Existing closed-period coverage remains in force: a DRAFT posting request for a closed date is rejected before JournalEntry, StockMovement, PartyLedgerAttribution, POST audit, or successful idempotency result. No Phase 3 code was modified.

## Posted immutability and delete protection

Existing model and protected-surface tests remain in force. After POST:

- Purchase save and delete are blocked;
- PurchaseLine save and delete are blocked;
- posted JournalEntry, JournalLine, StockMovement, and PartyLedgerAttribution are immutable;
- line-level creation/deletion cannot be used to alter posted history through the protected model boundary;
- no posted payable, inventory, attribution, or audit history can be silently removed.

No reversal or correction path was added. `reverse_journal()` remains a generic accounting primitive and is not treated as Purchase reversal.

## Test commands and exact results

### Focused Purchase tests

```text
$ cd backend && .venv/bin/pytest -q purchases/purchase_tests.py
..................                                                       [100%]
18 passed in 1.52s
```

### Full backend suite

```text
$ cd backend && .venv/bin/pytest -q
715 passed, 2 skipped in 86.15s (0:01:26)
```

The two skipped tests remain existing PostgreSQL/Phase 6 concurrency debt and are not counted as passed.

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

### Whitespace check

```text
$ git diff --check
# passed; no output
```

## PostgreSQL status

```text
PostgreSQL: BLOCKED / NOT EXECUTED
```

PostgreSQL was unavailable at the known endpoint `127.0.0.1:5432`. SQLite execution is not presented as PostgreSQL evidence.

The Phase 6 command below was not represented as passed and remains pending against PostgreSQL:

```text
python manage.py test inventory.inventory_tests.Stage6ConcurrencyTests --verbosity 2
```

## Git status and diff

Starting and ending HEAD are both:

```text
c521fb4b6194330142c77bcefd9e9d9795f601d9
```

Observed working tree after Stage 7.6:

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
```

Because `backend/purchases/` and the Stage 7 evidence files are untracked working-tree work, `git diff --stat` reports only the tracked pre-existing changes:

```text
 backend/config/settings/base.py                    |   2 +-
 .../PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md   | 105 +++++++++++++++++++++
 2 files changed, 106 insertions(+), 1 deletion(-)
```

Stage 7.6 changes within the untracked Purchase directory are:

- `backend/purchases/services.py` — validated draft update boundary and shared recalculation helpers;
- `backend/purchases/purchase_tests.py` — Stage 7.6 draft lifecycle regressions;
- `docs/phase-reports/PHASE_7_STAGE_7.6_IMPLEMENTATION_EVIDENCE.md` — this report.

All unrelated Stage 7.1–7.5 and Phase 6/settings working-tree work was preserved.

## Protected surfaces

Unchanged as systems of record:

- Phase 0 contract;
- Accounting Core and `post_journal()`;
- Fiscal Periods and posting-date gate;
- Party Ledger and `attribute_journal_line()`;
- Master-data services;
- money and currency helpers;
- Inventory `receive_stock()`, StockMovement, and AVCO;
- audit and idempotency primitives;
- Purchase reversal/correction decision from Stage 7.4;
- Phase 6 concurrency architecture.

## Remaining debt and risks

- PostgreSQL execution remains blocked, including Phase 6 concurrency verification.
- The repository still contains the pre-existing uncommitted Phase 7.1–7.5 work; it was not frozen or committed.
- No Purchase reversal, correction, payment, settlement, tax, sales, frontend, or Phase 7.7 work was started.
- Direct low-level ORM writes can still bypass service-level recalculation for DRAFT objects; the authoritative application edit path is now `update_purchase()` / `update_purchase_line()`, while posting final validation remains the final defense. Tightening all arbitrary ORM mutation paths would require a broader model/API contract decision and was not invented here.

## Explicit out-of-scope confirmation

Not implemented: payments, supplier settlement, advances workflow, FX settlement, payment discount, paid status, sales, frontend, Purchase reversal, Purchase correction, Purchase Return as correction, new accounting/AP/supplier-ledger/inventory/AVCO/audit/idempotency systems, Phase 7.7, and any freeze or merge.

## Stop point

Stage 7.6 is complete for this implementation increment. Evidence is recorded and user review is required. No commit, merge, freeze, or Phase 7.7 start was performed.
