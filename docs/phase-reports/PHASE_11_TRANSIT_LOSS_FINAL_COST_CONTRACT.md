# Phase 11 — Transit Loss and Final Unit Cost Contract

**Status:** Business rule confirmed by the user; implementation and evidence pending.
**Branch:** `phase/11-transit-final-unit-cost`
**Base:** `main` at `5ee0ae8b946c03307b2a4917ce045e577fc8f3b1`
**Workflow:** INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → FROZEN.

## 1. Confirmed business rule

For each purchase shipment, calculate final unit cost over the quantity that arrived in good condition, not the quantity originally purchased.

`good_quantity = purchased_quantity - transit_wastage_quantity`

`final_unit_cost = (net_purchase_cost + approved_direct_costs) / good_quantity`

Example: 2,000 barrels purchased; 10 barrels leak or are damaged in transit; 1,990 barrels remain good. The full purchase cost plus freight, porter/labor, and other approved direct costs is absorbed by the 1,990 good barrels. The 10 lost barrels are recorded as quantity wastage, not as good inventory. Shared direct costs continue to use measured shipment weight where required by the existing contract.

## 2. Required records and invariants

- Preserve the original purchased quantity, loss quantity, good quantity, purchase cost, and each direct-cost source separately.
- A transit loss must be a distinct, immutable, auditable event with date, reason, actor, quantity, source shipment/lot, and idempotency protection. It must not be recorded by editing a posted purchase, posted journal, stock movement, or transit receipt.
- Reject loss quantities that are non-positive, exceed the un-disposed transit quantity, or would make good quantity zero/negative.
- Quantity reconciliation must explicitly account for transit loss in addition to remaining transit, company-owned warehouse receipt, and transit sale/disposition.
- The final unit cost is based on total applicable cost divided by good quantity. Do not divide direct costs by original purchased quantity when a confirmed loss exists.
- The adjustment must flow through the existing chronological AVCO / landed-cost valuation path; do not create a second stock valuation engine.
- If some goods were already sold, received, transferred, returned, or held in customer-owned custody before the loss/final cost was recorded, post balanced, traceable compensating valuation effects to the affected inventory/transit/COGS destinations. Do not rewrite historical journals or movement snapshots.
- Customer revenue, customer balances, cash, and payment/allocation records must not change solely because cost is finalized.
- Preserve manually approved historical currency rate/date, immutable allocation snapshots, atomic posting, idempotency, and reversal-only correction semantics.

## 3. Required scenarios before acceptance

1. 2,000 purchased, 10 lost, 1,990 good; purchase cost only.
2. Same shipment with freight and porter costs; final cost divides by 1,990.
3. No loss; denominator remains original quantity.
4. Loss quantity is zero, negative, exceeds remaining transit, or leaves no good quantity; reject atomically.
5. Loss recorded before any receipt/sale.
6. Partial transit sale before loss is recorded; recalculate prior COGS and remaining transit valuation through compensating journals.
7. Partial warehouse receipt before loss; reconcile transit and warehouse value without double capitalization.
8. Some quantity sold, some in transit, some in warehouse; final cost effects reconcile exactly across all destinations.
9. Returns, transfers, and customer-owned custody are present.
10. Duplicate and concurrent loss/final-cost submission creates only one event and one set of adjustments.
11. SQLite and PostgreSQL tests, plus existing accounting, inventory, transit, landed-cost, sales, frontend and Tauri CI on the exact candidate SHA.

## 4. Implementation boundary

The existing landed-cost posting code currently divides allocated late costs by the original purchase-line quantity. Merely changing that divisor is insufficient: transit loss also changes owned quantity and can require revaluation of already-sold and remaining units. Implementation must add the explicit loss/finalization record and integrate its valuation deltas with the existing ledger and AVCO replay. Any uncertain or unreconcilable history must fail closed and roll back atomically.

This contract records the user's confirmed business rule. It does not claim implementation, test success, approval, or freeze.
