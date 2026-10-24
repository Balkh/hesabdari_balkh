# Phase 8 — Invoice-Time COGS and Warehouse Allocation Contract

Status: owner-approved target contract; implementation and verification are not yet complete.

## Owner decisions

1. COGS for an ordinary available-stock sale is recognized when the sales invoice is finalized.
2. Each finalized invoice line must have an explicit, immutable allocation of its quantity to one or more warehouses before posting COGS.
3. Each allocation uses the applicable cost basis for that product/warehouse at the sale's posting chronology. The journal credits the inventory account assigned to that warehouse and debits COGS.
4. A transit sale uses its specific Goods-in-Transit purchase lot and that lot's cost; it must not be blended into ordinary warehouse inventory.
5. Warehouse Check records physical handover/custody only. It must not issue stock or post COGS a second time for quantities already accounted for at invoice finalization.
6. A later direct landed-cost correction must update prior affected COGS and valuation through controlled chronological replay. If the full event history cannot be reconstructed and validated, the operation must fail closed without partial changes.
7. Posted journals remain immutable; corrections are represented by governed compensating entries/replay, never by editing posted history.
8. Preserve stock identity (Product, Warehouse), existing warehouse account mapping, idempotency, transaction atomicity, and customer ownership/custody separation.

## Required implementation constraints

- A line may be allocated across multiple warehouses; the sum of allocations must equal the invoice-line quantity before finalization can post COGS.
- Warehouse availability, cost layer/valuation, and account mapping must be validated under appropriate row locks in the same atomic transaction as finalization.
- Reject incomplete, duplicate, over-allocated, under-allocated, inactive-warehouse, missing-cost, or unreconstructable-history cases safely.
- COGS must be posted exactly once per invoice allocation. Retries must be idempotent.
- Warehouse Check may be partial or repeated, but may not change the already-posted invoice COGS or company inventory valuation a second time.
- Existing posted sales and warehouse checks must not be silently rewritten by a migration. Any legacy transition needs an explicit, auditable compatibility or reconciliation strategy.

## Required regression evidence

1. One line allocated to one warehouse: correct COGS and inventory account at invoice finalization; Warehouse Check adds no second COGS/stock issue.
2. One line split across two warehouses with distinct inventory accounts/costs: allocation sum, per-warehouse credits, and COGS are correct.
3. Missing/invalid allocation or insufficient/unknown valuation: finalization rolls back all journals and state.
4. Repeated finalization is idempotent.
5. Partial and repeated Warehouse Checks record custody/release only and never duplicate COGS.
6. Transit-lot sale preserves lot-specific cost and does not consume ordinary warehouse stock.
7. Later landed-cost adjustment replays chronology and corrects previously sold quantities; unprovable chronology fails closed atomically.
8. Sales returns, check cancellation, concurrent finalization, PostgreSQL locking, SQLite, and PostgreSQL regression suites remain correct.
9. Existing legacy records are reconciled safely and explicitly.
10. CI evidence must correspond to the exact proposed head SHA; passing CI alone does not constitute accounting-contract approval.

## Current source finding

At the reviewed Phase 11 head, ordinary warehouse-stock COGS is currently posted during Warehouse Check, while transit COGS is posted at invoice finalization. SaleLine currently has no authoritative warehouse allocation. The implementation must address both facts together; moving the journal call alone is not sufficient.

## Review gate

This contract records the owner's approval of the target behavior. It does not mark the code implemented, tested, merged, approved for release, or frozen. Do not merge until the code, migrations, accounting scenarios, exact-SHA CI, and review evidence pass.
