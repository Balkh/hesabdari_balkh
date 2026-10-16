# Phase 11 — Purchase-Wide Transit Loss and Final Unit Cost Contract

**Status:** Business rule confirmed by the user; implementation and evidence pending.
**Branch:** `phase/11-transit-final-unit-cost`
**Base:** `main` at `5ee0ae8b946c03307b2a4917ce045e577fc8f3b1`
**Workflow:** INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → FROZEN.

## 1. Confirmed business rule: one purchase, multiple vehicle arrivals

The costing unit is the **complete purchase line/lot**, not each vehicle, trip, or partial arrival. A purchase of 10,000 barrels may arrive in several loads (for example, about 2,000 per truck). Those partial arrivals are physical receipt events only; they do not independently finalize the purchase's unit cost.

When the purchased lot is reconciled and all applicable direct costs and wastage are known:

`good_quantity = original_purchased_quantity - confirmed_wastage_quantity`

`final_unit_cost = (net_purchase_cost + all_approved_direct_costs) / good_quantity`

Example: 10,000 barrels purchased; 30 barrels confirmed lost across transport; 9,970 good barrels. If purchase cost is $170,000 and freight, porter/labor, loading/unloading and other approved direct costs total $3,000, final cost is $173,000 / 9,970 = approximately $17.3521 per good barrel.

Do not finalize or independently calculate a different final cost per truck simply because one truck arrived earlier. Temporary/estimated cost may be used before reconciliation, but the final purchase-wide calculation must include all applicable costs and confirmed loss.

**Purchase-invoice baseline (explicit clarification):** the purchase price is not an unknown estimate. Each posted purchase line already has its own invoice-backed net purchase cost (`net_total`, after the approved line discount) and original quantity. That is the source cost for that line from the moment the purchase is posted. A temporary unit cost means the *provisional valuation* before all approved direct costs and confirmed wastage are finalized; it does not mean the system may guess or replace the invoice purchase price. Final cost must start from that line's invoice-backed net cost, add its properly allocated direct costs, and divide by the line's reconciled good quantity. Keep different purchase lines/products separate, preserve the original invoice and exchange-rate/date snapshots, and apply any later difference through compensating valuation entries.

## 2. Direct-cost allocation

- Costs directly attributable to a specific purchase line are assigned to that line.
- Shared freight and other shared direct costs use measured weight where required by the existing approved allocation contract.
- Include only approved direct costs. Do not introduce insurance or other unapproved cost categories.
- Preserve each cost document's currency, manually approved historical rate/date, immutable allocation snapshot, and source journal.
- If a purchase consists of genuinely separate purchase lines with different products or independently attributable costs, compute each line's unit cost from its own net cost, allocated shared costs, and good quantity. Do not mix unlike products into one denominator.

## 3. Required records and invariants

- Preserve original purchased quantity, each physical receipt quantity, confirmed loss quantity, good quantity, purchase cost, and each direct-cost source separately.
- A transit loss must be a distinct, immutable, auditable event with date, reason, actor, quantity, source shipment/lot, and idempotency protection. It must not be recorded by editing a posted purchase, posted journal, stock movement, or transit receipt.
- Reconcile the whole lot explicitly: original quantity must equal good quantity accounted for by company-owned transit remaining, company-owned warehouse receipts, transit sales/dispositions and other supported good-quantity flows, plus confirmed loss. Returns and customer-owned custody must be traceable without double-counting.
- Reject non-positive loss quantities, duplicate/idempotency conflicts, quantities beyond the unreconciled quantity, and any event that makes good quantity zero/negative. Do not reject a valid retrospective loss solely because other good units from the same lot have already arrived or sold; use whole-lot reconciliation, not just current remaining transit quantity.
- Final unit cost is based on the full applicable cost divided by the whole-lot good quantity. Do not divide direct costs by original purchased quantity after a confirmed loss.
- The adjustment must flow through the existing chronological AVCO / landed-cost valuation path; do not create a second stock valuation engine.
- If some good units were already sold, received, transferred, returned, or held in customer-owned custody before final costing, post balanced, traceable compensating valuation effects to affected inventory/transit/COGS destinations. Do not rewrite historical journals or movement snapshots.
- Customer revenue, customer balances, cash, and payment/allocation records must not change solely because cost is finalized.
- Preserve atomic posting, idempotency, manual historical FX rate/date, immutable source snapshots, and reversal-only correction semantics. If history cannot be reconciled safely, fail closed and roll back.

## 4. Required scenarios before acceptance

1. 10,000 purchased, delivered in several partial vehicle receipts, 30 total lost; denominator is 9,970 for the whole purchase line.
2. Same purchase with purchase cost only and no additional direct costs.
3. Same purchase with freight, porter/labor and other approved direct costs; all costs are included before dividing by good quantity.
4. Shared direct costs allocated by measured weight; line-specific costs assigned to the proper line; deterministic minor-unit rounding and remainder reconciliation.
5. No loss; denominator remains original quantity.
6. Zero/negative loss, over-reported loss, duplicate and concurrent submissions, or zero/negative good quantity; reject atomically.
7. Loss is recorded after multiple partial receipts; whole-lot reconciliation still succeeds when valid.
8. Partial transit sale or warehouse sale before final costing; recalculate prior COGS and remaining transit/inventory value with compensating journals.
9. Some quantity sold, some in transit, some in warehouse; exact value reconciliation across all destinations.
10. Returns, transfers, negative-stock obligations and customer-owned custody are present.
11. Repeated/late direct-cost documents and finalization are idempotent; source records remain immutable.
12. SQLite and PostgreSQL tests plus existing accounting, inventory, transit, landed-cost, sales, frontend and Tauri CI on the exact candidate SHA.

## 5. Implementation boundary

The current landed-cost service divides allocated late costs by original purchase-line quantity. Merely changing that divisor is insufficient: whole-lot loss changes the cost per good unit and can require revaluation of already-sold and remaining units. Implementation must add explicit loss/reconciliation records and integrate their valuation deltas with the existing landed-cost ledger and AVCO replay. A partial truck arrival must never trigger final costing by itself. Any uncertain or unreconcilable history must fail closed.

This contract records the user's confirmed business rule. It does not claim implementation, test success, approval, or freeze.
