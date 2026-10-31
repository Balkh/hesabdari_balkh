# OD-1 — Future Type-B Sale Owner Decision

**Decision ID:** OD-1  
**Record date:** 2026-10-31  
**Authority:** Explicit owner-approved decisions recorded in the Hesabdari Balkh project conversation  
**Status:** OWNER-APPROVED DECISION — DOCUMENTED BY W0-1  
**Scope:** Future / Forward (Type-B) Sales fulfillment, ownership transfer, and COGS timing

## 1. Approved fulfillment chain

    Sale
      → Purchase
      → PurchaseLine / actual receipt
      → receive_stock()
      → actual Product + Warehouse inventory and cost
      → fulfillment allocation to the originating SalesLine
      → Warehouse Release Authorization
      → physical release / handover

Each fulfillment allocation must identify the actual source PurchaseLine/lot and actual received Product + Warehouse quantity. It must prevent double allocation, over-allocation, over-fulfillment, allocation from nonexistent stock, and duplicate use of one physical quantity.

## 2. Commercial entitlement and ownership are distinct

- Type-B Sale finalization establishes the commercial entitlement/obligation only.
- Type-B finalization must not fabricate physical stock, a StockMovement, physical ownership, or a source-lot cost.
- Purchase and actual receipt establish actual company inventory and its traceable cost.
- Allocation identifies actual goods assigned to the Type-B obligation; allocation alone does not transfer ownership.
- **Ownership of the actual allocated physical goods transfers at the authoritative Warehouse Release Authorization.**
- Physical release remains a separate physical handover/issue event. It is not the ownership trigger.
- If authorized goods remain physically held by the company, they are customer-owned custody goods and must remain traceable as such.

Payment is not an ownership trigger and does not replace any step in this chain.

## 3. Type-B COGS timing

**Owner-approved rule:** Type-B COGS is recognized at the authoritative Warehouse Release Authorization for the actual allocated quantity.

At that event:

- use the actual source PurchaseLine/lot cost;
- preserve each source lot's cost independently; never blend distinct purchase lots;
- calculate COGS from the actual authorized allocated quantity and its source-lot cost;
- preserve source-lot, SalesLine, authorization, inventory, and journal traceability;
- use the existing canonical accounting and inventory posting boundaries; do not create a parallel posting or costing engine.

If actual source-lot cost cannot be established, the operation must stop/fail closed. It must not estimate, substitute, or silently use an unrelated or blended cost.

This rule does not authorize a new account mapping, alter the existing AVCO/lot-cost contract, or permit direct mutation of posted history.

## 4. Explicit separation from other sale paths

This decision is specific to Type-B Future/Forward Sale.

- Existing AVAILABLE / Type-A sale behavior remains governed by its approved invoice-finalization COGS contract.
- Existing Phase 11 Transit Sale behavior remains governed by its approved invoice-finalization COGS contract.
- Do not move Type-A or Transit Sale COGS to Warehouse Release Authorization by analogy.
- Do not treat Type-B Release Authorization as physical release.

## 5. Required integrity controls

All fulfillment, authorization, inventory, and accounting effects must be atomic, idempotent, concurrency-safe, auditable, and source-traceable. Duplicate requests must not duplicate allocation, ownership events, inventory effects, or journals.

Posted financial and inventory history remains immutable. Corrections use only the applicable approved reversal/adjustment path.

## 6. Boundaries and unresolved matters

This decision resolves the Type-B ownership trigger and Type-B COGS trigger only. It does not independently settle separate open decisions concerning customer-custody valuation/reporting, Sales Return accounting, cancellation/reversal policy, or other Sales lifecycle details not expressly covered above.

No implementation, migration, API, UI, test result, merge, or freeze is implied by this decision record.

## 7. Authority and reconciliation

This record is part of W0-1 Owner Decision & Contract Reconciliation. It must be read together with the governance roadmap and existing Phase 8 and Phase 11 contracts. Where this decision explicitly resolves the Type-B COGS trigger, older Phase 8 statements describing that same trigger as unresolved are superseded only to that extent. All unrelated Phase 8 and Phase 11 rules remain protected.
