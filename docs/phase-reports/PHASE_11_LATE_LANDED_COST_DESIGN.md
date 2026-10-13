# Phase 11 — Late Landed-Cost Finalization Contract

**Contract status:** User-approved for implementation. **Implementation status:** Incomplete; not frozen.
**Base:** `phase/11-landed-cost-weight-allocation`
**Work branch:** `phase/11-late-landed-cost-finalization`
**Scope:** Costs received after a purchase receipt or goods-in-transit recognition, without editing posted purchase documents, journals, or stock movements.

## 1. Source document and accounting

A later direct-cost document must preserve: unique document number, real payee/creditor, transaction currency, positive amount, manually approved historical exchange rate and rate date, cost date, category, description, creator, idempotency key, posted journal, and immutable allocation snapshots.

At posting, the journal must debit the appropriate inventory/landed-cost control account and credit supplier payable **2110**, in the document transaction currency and using its stored historical rate/date. Any later payment is a separate settlement and must not be implied by posting the cost document. Base-currency documents use rate 1 under the existing journal contract. The posting date must be in an open fiscal period.

## 2. Allocation rules

- Allocation must explicitly identify one or more purchase lines/receipt lots. Never infer ownership from product name or current quantity alone.
- A direct allocation is allowed only when the cost belongs wholly to that selected line.
- Shared freight/other approved shared direct costs use measured weight where the source contract requires it. Every participating line needs a positive measured weight.
- Allocate to currency minor units with deterministic final-row remainder reconciliation. Sum of allocations must exactly equal the source document amount; sum of AFN allocations must exactly equal its snapshotted AFN amount.
- Do not use insurance, unapproved overhead, guessed weight, or an automatically fetched FX rate.
- The same idempotency key and same payload returns the original result; reusing the key for a different payload is rejected.

## 3. Valuation and immutable history

Posted purchase journals, source-cost journals, and stock movements are immutable. Late costs must not edit the source purchase, a posted movement's `unit_cost`, its quantity snapshots, or its original journal.

The existing chronological AVCO implementation remains the only stock valuation engine. Before a late-cost document can be considered complete, an explicit, auditable valuation-adjustment ledger must trace each allocated cost through the source receipt and subsequent history, including:
- quantity still in warehouse inventory;
- goods still in transit;
- quantities sold and their COGS;
- transfers between warehouses;
- sales/purchase returns;
- customer-owned custody where relevant to the sales contract;
- stock that was fully consumed before the cost arrived.

A simplistic split based on current stock quantity is invalid when multiple receipts, returns, transfers, or sales exist. A late cost must not be posted if the system cannot reconcile the full allocation to the affected valuation destinations. The adjustment must be atomic and idempotent, and its accounting effects must balance exactly.

## 4. Required scenarios before implementation can be accepted

| Scenario | Expected contract |
|---|---|
| One receipt, all units remain | Full allocated cost increases inventory value; no COGS adjustment. |
| One receipt, all units sold | Full allocated cost increases COGS through a traceable adjustment; no remaining inventory increase. |
| Part sold, part remains | Cost delta is traced across sold and remaining quantities according to chronological AVCO, not a current-quantity shortcut. |
| Goods in transit | Cost is attached to the correct transit lot and remains in the Goods-in-Transit valuation until the lot moves. |
| Multiple receipts of same product | Only the explicitly allocated source receipt/line receives the cost; later receipts are not blended as a shortcut. |
| Warehouse transfer | Cost follows the transferred stock through immutable transfer movements and reconciles across source/destination warehouses. |
| Sales return / purchase return | Returned quantity follows the linked source movement and return valuation; no duplicate capitalization or relief. |
| Fully consumed / negative-stock obligation | The late cost resolves the source receipt's chronological valuation/COGS consequences without changing historical movement rows. |
| Multiple currencies | Preserve transaction currency and manual historical rate/date; never re-rate from today's exchange table. |
| Duplicate submission / concurrent posting | Exactly one source document, journal, allocation set, and valuation adjustment set. |
| Invalid weight / amount mismatch / closed period | Reject atomically; no partial journal, allocation, or valuation writes. |
| Reversal/correction | Use a separate traceable compensating workflow; never edit a posted source document or movement. |

## 5. Evidence gate

Before this draft can be treated as implemented, tests must cover both SQLite and PostgreSQL for allocation reconciliation, historical-rate snapshots, supplier attribution to account 2110, separate payment, idempotency/concurrency, fiscal-period rejection, immutability, AVCO replay, transit, sales/COGS, transfers, returns, and atomic rollback. Existing purchase, inventory, goods-in-transit, sales, accounting, and golden tests must remain green.

**This document does not certify the feature as implemented.** No merge, approval, or freeze is implied.
