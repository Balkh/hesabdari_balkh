# Phase 11 — Landed Cost and Weight-Based Freight Allocation

**Status:** Implementation work plan; not frozen.  
**Target branch:** `phase/11-landed-cost-weight-allocation`  
**Baseline:** current `main` at branch creation.  
**Workflow:** INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → FROZEN.

## 1. Approved business rules

1. Freight and other approved direct costs are part of landed/final unit cost, not automatically period expense.
2. A cost traceably attributable to one product/line is assigned directly to that line.
3. Shared freight is allocated by the measured weight of each purchase line. For each line:
   `allocated freight = shared freight × line measured weight ÷ total measured weight`.
4. Monetary rounding uses the existing Half-Up money utilities. Any allocation remainder is assigned deterministically so line allocations sum exactly to the source cost.
5. For one-line purchases, the freight belongs entirely to that line; no comparative weight allocation is needed.
6. Purchase currency and the purchase's recorded historical exchange rate/date remain authoritative. Do not silently re-rate historical purchases.
7. Posted source documents and posted journals remain immutable. Later cost information must be represented by a traceable, atomic, idempotent adjustment—not by rewriting old entries.
8. Revenue, customer balances, and cash/payment records must not change when cost alone is corrected.

## 2. Existing-code findings

- `Purchase` stores subtotal, discount, freight, and total.
- `PurchaseLine` currently stores quantity, unit price, line total, discount allocation, and net total; no measured-weight field is present in the inspected model.
- Current purchase posting debits the warehouse/Goods-in-Transit inventory account for `subtotal - discount`, debits account `6200` for freight, and credits supplier payable for the purchase total.
- Current immediate-receipt and transit-lot unit costs are calculated from `PurchaseLine.net_total / quantity`, so freight is excluded from the unit cost.
- Current negative-COGS resolution compares a temporary cost with the receipt movement's unit cost and records an adjustment. It does not, by itself, establish a general recalculation mechanism for later-added landed costs across all remaining stock, transit, custody, and returns.

## 3. Required design boundary

Weight must be an explicit, auditable measurement associated with each purchase line (including its unit, with a normalized unit such as kg used for calculation). Do not infer weight from product names, UOM conversion factors, or quantity.

- If shared freight is positive across multiple lines, each participating line must have a valid positive measured weight; otherwise reject posting before any financial or stock side effects.
- If a cost is directly attributable to a line, allocate it directly rather than redistributing it by weight.
- Keep the existing master Product contract unchanged unless separate approval is given; purchase-specific measured weight belongs to the purchase line because the actual shipment measurement can vary.
- The existing schema has a freight field but no complete general ledger of other direct-cost categories. Do not silently invent additional expense types or account mappings; model those only with explicit source, currency, attribution, and posting rules.
- Freight capitalization changes the purchase journal's inventory debit and the cost basis of immediate receipts/transit lots. Supplier payable remains the purchase total. Account 6200 must not also be debited for the same capitalized freight.
- For partial receipts, partial transit disposition, sales, customer-owned custody, and returns, maintain the cost basis and quantity reconciliation without double capitalization or double adjustment.

## 4. Scenario and evidence matrix

| ID | Scenario | Required assertions |
|---|---|---|
| LC-01 | Single-line purchase with freight | All freight allocated to the line; unit cost includes net line cost plus freight per unit. |
| LC-02 | Multi-line shared freight, unequal weights | Allocation follows measured-weight ratios, not line value or quantity. |
| LC-03 | Fractional allocation / rounding | Half-Up rounding; allocated totals equal source freight exactly; deterministic remainder. |
| LC-04 | Missing, zero, negative, or invalid weight with shared freight | Deterministic validation rejection before journal, stock movement, transit lot, payable attribution, or POST audit. |
| LC-05 | Directly attributable cost | Cost goes only to its identified line; it is not shared by weight. |
| LC-06 | Discount plus freight | Discount allocation remains consistent; landed cost includes net purchase cost plus allocated direct cost. |
| LC-07 | USD purchase with historical rate/date | Foreign amount, recorded rate/date, AFN valuation, supplier payable, and inventory valuation reconcile. |
| LC-08 | Immediate warehouse receipt | Movement cost, movement AFN cost, AVCO, inventory debit, and payable reconcile; no duplicate freight expense. |
| LC-09 | Owned goods in transit | Transit lot unit cost and account 1430 value include allocated freight; later receipt transfers the same cost basis without duplication. |
| LC-10 | Negative stock with temporary COGS cost | Receipt-cost correction adjusts COGS and inventory by the actual cost difference; original posted journals remain unchanged. |
| LC-11 | More than one receipt for one product/warehouse | Obligations resolve only by eligible quantity; no duplicate or over-resolution; total adjustment equals the applicable cost difference. |
| LC-12 | Cost becomes known after receipt or sale | A separate immutable adjustment updates the appropriate remaining inventory, transit quantity, and sold quantity/COGS with traceability; no historical journal mutation. |
| LC-13 | Sold, remaining, transit, customer-owned custody, and returned portions | Cost difference is allocated only to the quantities and ownership buckets that actually retain that cost; no double count. |
| LC-14 | Repeated request / transaction retry | Idempotent result; no duplicate journal, movement, lot, adjustment, or audit effect. |
| LC-15 | Atomic failure in any posting step | Entire operation rolls back; no partial journal, movement, lot, payable attribution, or status transition. |
| LC-16 | Posted purchase/line mutation attempt | Existing posted immutability is preserved. |
| LC-17 | Revenue and customer balances | Landed-cost-only changes do not alter sales revenue, customer receivables, or payments. |
| LC-18 | PostgreSQL and SQLite | Relevant contract tests pass on both configured database engines, including transaction/idempotency behavior. |

## 5. Implementation sequence

1. Add explicit measured weight to purchase-line input, validation, persistence, and migration; preserve draft-edit semantics and posted immutability.
2. Add one deterministic landed-cost allocation function and contract tests for direct and weight-based allocation.
3. Update purchase journal and immediate/transit cost basis consistently.
4. Design and implement late-cost adjustments as a separate immutable posting workflow. It must reconcile quantity/cost across inventory, transit, customer-owned custody, sales COGS, and returns; do not treat a simple negative-COGS resolver as sufficient.
5. Add retry, atomic rollback, historical-rate, and dual-database evidence.
6. Run focused Purchase/Sales/Transit tests, full backend suite, Django checks, and frontend build if affected; inspect CI results.
7. Stop for user review with exact commit SHA, changed-file summary, test commands/results, and any unresolved limitations. No merge without explicit approval.

## 6. Non-goals and safeguards

- Do not change frozen Product master-data or Inventory identity contracts.
- Do not change posted history or backdate a new journal into a closed period.
- Do not use revenue, customer receivables, or cash to balance a cost adjustment.
- Do not claim complete/frozen status until all applicable evidence has been collected and reviewed.
