# Phase 11 — Open Decisions Memo (owner decision required)

Status: **UNDECIDED — no policy implemented from this memo.**
Prepared during the PR #38/#39/#40 audit. Nothing in this memo changes
code or approved contracts; it isolates the two questions that cannot
safely be answered from the repository.

---

## Decision A — Cost-pool correction after downstream warehouse activity

### Exact current behavior
- `reverse_landed_cost` (backend/purchases/landed_cost_reversal.py:131)
  posts dated mirror journals, but
  `_assert_no_later_activity` (:84) **fails closed** when, after the
  landed cost was posted, there is any later StockMovement for the
  product, later TransitReceipt, later TransitSaleAllocation, or a
  later active landed-cost layer for the same product.
- `reverse_transit_loss_valuation` (PR #39, migration 0007) likewise
  fails closed after dependent stock movements / receipts / sales /
  later landed-cost postings; it restores lot state and re-opens the
  loss so a corrected loss can be re-recorded.
- Posted journals are never edited; corrections are compensating only.

### What can be corrected safely today
1. Wrong freight/direct cost with **no** later activity: reverse landed
   cost → repost corrected → re-finalize loss valuation. Regression
   proven end-to-end (unit 112.0408 scenario on PR #39).
2. Wrong loss valuation with no dependent postings: governed reversal
   → re-record corrected loss; prior sale COGS replay is proven
   (COGS 3,000 → 3,061.22 → reversal → 3,361.22 corrected).
3. Anything else: owner-approved manual compensating journal.

### What cannot be reconstructed safely today
A wrong cost pool after sales/transfers/returns/partial releases have
consumed AVCO layers: the posted COGS of each historical issue depends
on the exact chronological order of receipts, issues, returns and
valuation layers. The current data preserves movements and journals,
but no approved contract defines replay ordering across warehouses,
returned-quantity cost relief, negative-COGS obligations, or
multi-layer interaction — and the approved reversal guard explicitly
refuses to guess.

### Options
- **A1 — Keep fail-closed (status quo).** Corrections after downstream
  activity require manual review and an owner-approved compensating
  journal. Lowest risk; corrections are slower and manual.
- **A2 — Bounded chronological replay (new contract required).** Would
  need owner-approved rules for: event ordering (movement_date vs
  created_at vs posting chronology), cost provenance per movement,
  idempotency keys per replay step, row-lock ordering, compensating
  journal design, returned quantities, negative-COGS obligations,
  multi-warehouse transfers, period gates, and failure recovery; plus
  a migration/audit design and the full regression matrix before any
  code. This is a new accounting contract, not a bug fix.

### Owner question A
**Do you approve A1 (keep fail-closed + manual compensating journals),
or do you want a design proposal for A2 (bounded chronological replay)
as a separate, separately-approved workstream?**

Blocked until answered: any automatic correction of a cost pool after
downstream warehouse activity; Phase 11 freeze.

---

## Decision B — Transit COGS timing

### Where the question lives
`docs/phase-reports/PHASE_11_WAREHOUSE_CHECK_CANCELLATION_DECISION.md`
(§"Accounting boundary") explicitly does **not** decide "the initial
revenue-recognition timing, COGS timing, inventory-reduction timing,
or the financial valuation policy for customer-owned custody."

### Current behavior (code-proven, PR #38/#39)
- Transit COGS posts at **sales-invoice finalization**:
  Dr 5100 / Cr 1430 at the lot's current unit cost, with a
  `TransitSaleAllocation` recording lot, quantity and unit cost
  (backend/sales/services.py, `finalize_sale` transit branch).
- Later landed costs adjust already-sold transit quantities through
  `post_transit_sale_landed_cost_adjustments`; purchase-wide final
  costing uses `G = N − R − L` after all arrivals; loss valuation
  replays affected COGS through compensating journals (PR #39).
- Physical receipt into a warehouse does not post transit COGS again.

### Alternatives and consequences
- **B1 — Keep invoice-time transit COGS (status quo).** COGS matches
  the ownership transfer; later final-cost corrections flow through
  the existing adjustment/replay journals. No migration.
- **B2 — COGS at physical receipt/delivery.** Would defer COGS for
  goods sold in transit, change 1430 clearing behavior, require new
  journals at receipt, rework returns/custody, and a migration/
  compatibility plan for existing TransitSaleAllocations. This is a
  policy change requiring explicit approval and a new test matrix.

### Owner question B
**Do you confirm B1 (transit COGS at invoice finalization, as currently
implemented and tested), or do you direct B2 (receipt/delivery-time
COGS) as a new contract?**

Blocked until answered: any change to transit COGS timing; Phase 11
freeze statement. PR #40's ordinary-stock invoice-time contract does
not by itself authorize changing the transit rule.

---

## What is NOT blocked
PR #38/#39/#40 technical review, testing, and merge-readiness evidence
proceed independently. Merge still requires explicit owner
authorization; freeze requires both decisions above plus post-merge
verification on `main`.
