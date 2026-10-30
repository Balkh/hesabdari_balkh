# Phase 8 — Invoice-Time COGS and Warehouse Allocation Contract

Status: owner-approved contract; the implementation from PR #40 was merged on 2026-10-24. The revenue-timing rule and related decision-status reconciliation were recorded in PR #46, which is now merged. This document does not declare Phase 8 complete or frozen; remaining fulfillment, future-sale COGS, custody-accounting, cancellation/reversal, and return gates remain subject to their approved contracts.

## Owner-approved accounting contract

1. COGS for an ordinary available-stock sale is recognized when the sales invoice is finalized.
2. Each finalized invoice line must have an explicit, immutable allocation of its quantity to one or more warehouses before posting COGS.
3. Each allocation uses the applicable cost basis for that product/warehouse at the sale's posting chronology. The journal credits the inventory account assigned to that warehouse and debits COGS.
4. A transit sale uses its specific Goods-in-Transit purchase lot and that lot's cost; it must not be blended into ordinary warehouse inventory. The owner explicitly confirmed transit COGS at invoice finalization (Decision B1, 2026-10-24).
5. Warehouse Check records physical handover/custody only. It must not issue stock or post COGS a second time for quantities already accounted for at invoice finalization.
6. Posted journals remain immutable. Corrections use the approved reversal/compensating mechanisms, never direct edits to posted history.
7. Preserve stock identity (Product, Warehouse), existing warehouse account mapping, idempotency, transaction atomicity, and customer ownership/custody separation.

## Owner decision A1 — Cost-pool correction after downstream activity

On 2026-10-24 the owner selected **A1: retain the fail-closed behavior**.

- When downstream stock movements, receipts, sales, returns, transfers, or later valuation layers make a landed-cost/cost-pool correction unsafe under the existing approved guards, the system must reject the automatic correction atomically.
- The rejected case requires accountant review and an explicitly approved compensating/controlled correction. Do not silently automate a manual journal.
- No new general chronological-replay engine is authorized under A1.
- Where the existing, tested reversal workflow proves there is no later dependent activity and correction is safe, use that approved reverse → repost → re-finalize path.
- Preserve any already-existing narrowly scoped and guarded transit-loss valuation behavior; do not broaden it, bypass its guards, or claim it authorizes general cost-pool replay.
- A failed safe-reconstruction check must leave journals, stock, lot valuation, obligations, and document state unchanged.

## Owner decision — Sales revenue recognition timing (resolves PH8-026)

On 2026-10-29 the owner approved, in the working conversation, the
following revenue-timing rule for Phase 8 Sales:

> Once a sales invoice is finalized, the sale is considered commercially
> completed. This applies whether the goods are already in the warehouse,
> in transit, or will reach the warehouse/customer later. The invoice
> determines sales revenue. Physical receipt, warehouse custody, customer
> delivery, and collection of money are separate events.

Recorded rule:

1. Sales revenue is recognized when the sales invoice is successfully
   finalized, for all supported sale types, including `FUTURE`.
2. The following events are separate and none of them delays or repeats
   revenue posting for a finalized sale:
   - Revenue recognition (at invoice finalization).
   - Payment receipt (a separate event; finalization must not create a
     payment receipt, and revenue must not be equated with cash receipt).
   - Physical receipt / warehouse custody.
   - Customer delivery / handover (Warehouse Check).
3. This decision does not redesign COGS, costing, inventory, or transit logic. Existing invoice-time COGS rules continue to apply to the already-contracted AVAILABLE and transit paths. This revenue-timing decision does not authorize COGS for a FUTURE sale before actual goods exist; FUTURE fulfillment and its COGS trigger remain a separate unresolved contract.
4. This decision applies to sales only. It does not define, and must not
   be read as inferring, any purchase-side recognition policy.
5. Account mapping, revenue channels, and other accounting policies are
   not changed by this decision.

Decision status: owner-approved on 2026-10-29 and recorded in PR #46,
which has since been merged. The merged PR includes the implementation,
regression tests, and exact-head CI evidence for the entitlement guard and
revenue-timing alignment. This does not declare Phase 8 complete or frozen.

### Required tests and evidence for this decision

- A finalized `FUTURE` sale posts its revenue journal exactly once with the
  existing approved structure, and creates no stock movement, no COGS
  journal, no customer ownership/custody record, and no payment receipt.
- A Warehouse Check finalization for a line without a customer ownership
  entitlement (today: any `FUTURE` line) is rejected with the project's
  `SalesValidationError`, leaves the check in `DRAFT`, leaks no
  `DoesNotExist` exception, and leaves no partial accounting, stock, or
  custody side effects.
- Existing AVAILABLE, transit, and Warehouse Check flows remain unchanged;
  the full backend suite must pass with these tests included.

### Related defect fixed while recording this decision

`finalize_warehouse_check` retrieved the SaleLine's
`CustomerOwnershipEntitlement` through an unguarded `.get()` in all three
branches (transit, allocated, ordinary). `FUTURE` sale lines never receive
an entitlement at finalization (the approved Type B ownership trigger is
actual fulfillment, not finalization), so any Warehouse Check finalization
for a `FUTURE` sale raised an unhandled
`CustomerOwnershipEntitlement.DoesNotExist` and rolled back. The fix
enforces the entitlement prerequisite explicitly with the project's
`SalesValidationError`; the check stays in `DRAFT` with no side effects,
and the flow remains available once an approved fulfillment path creates
the entitlement.

### Remaining unresolved decisions (unchanged by this decision)

- Revenue account selection (PH8-005) is **resolved and owner-approved**: `WHOLESALE → 4110` and `RETAIL → 4120` (PH8.2-001, approved 2026-09-23 and reaffirmed 2026-09-24). Older discovery documents retain historical unresolved wording; that wording is not the current decision. PR #46 did not change this mapping.
- `FUTURE`-sale fulfillment, authorization, and allocation remain
  unapproved and unimplemented; until then a `FUTURE` Warehouse Check
  cannot finalize because the entitlement prerequisite cannot be met.
- The historical paths `docs/phase-reports/PHASE_8_RESOLVED_CONTRACT.md`
  and `docs/phase-reports/PHASE_8_FROZEN_REFERENCE.md` do not exist in the
  repository history. They were referenced by older test-file metadata;
  those references were corrected in PR #47. They are not active contract
  documents or a current test-manifest dependency.

## Required implementation constraints

- A line may be allocated across multiple warehouses; the sum of allocations must equal the invoice-line quantity before finalization can post COGS.
- Warehouse availability, cost layer/valuation, and account mapping must be validated under appropriate row locks in the same atomic transaction as finalization.
- Reject incomplete, duplicate, over-allocated, under-allocated, inactive-warehouse, missing-cost, or unreconstructable-history cases safely.
- COGS must be posted exactly once per invoice allocation. Retries must be idempotent.
- Warehouse Check may be partial or repeated, but may not change the already-posted invoice COGS or company inventory valuation a second time.
- Transit COGS is Dr `5100` / Cr `1430` at invoice finalization using the specific lot's applicable unit cost. Physical receipt must not post the same transit COGS again.
- Later transit landed-cost/final-loss corrections must use only the existing approved and guarded adjustment/reversal paths. If a guard rejects the correction, fail closed under Decision A1.
- Existing posted sales and warehouse checks must not be silently rewritten by a migration. Any legacy transition needs an explicit, auditable compatibility or reconciliation strategy.

## Required regression evidence

1. One line allocated to one warehouse: correct COGS and inventory account at invoice finalization; Warehouse Check adds no second COGS/stock issue.
2. One line split across two warehouses with distinct inventory accounts/costs: allocation sum, per-warehouse credits, and COGS are correct.
3. Missing/invalid allocation or insufficient/unknown valuation: finalization rolls back all journals and state.
4. Repeated finalization is idempotent.
5. Partial and repeated Warehouse Checks record custody/release only and never duplicate COGS.
6. Transit-lot sale preserves lot-specific cost, posts Dr 5100 / Cr 1430 at invoice finalization, and does not consume ordinary warehouse stock.
7. A safe correction with no later dependent activity follows the approved reversal/repost path. A correction blocked by downstream activity fails closed atomically; no new general replay engine is implied.
8. Sales returns, check cancellation, concurrent finalization, PostgreSQL locking, SQLite, and PostgreSQL regression suites remain correct.
9. Existing legacy records are reconciled safely and explicitly.
10. CI evidence must correspond to the exact proposed head SHA; passing CI alone does not constitute accounting-contract approval.

## Historical baseline (pre-implementation)

At the reviewed Phase 11 head, ordinary warehouse-stock COGS was posted
during Warehouse Check, while transit COGS was posted at invoice
finalization. SaleLine had no authoritative warehouse allocation.

## Implemented behavior (PR #40)

- `SaleLineWarehouseAllocation` records explicit immutable allocation
  intents at sale creation (multi-warehouse, sum == line quantity);
  queryset update/delete/bulk paths are guarded, with finalize_sale's
  one-time completion of an unissued intent as the only queryset write.
- `finalize_sale` issues stock per allocation (warehouse AVCO; existing
  negative-stock acknowledgement/temporary-cost policy) and posts
  Dr 5100 / Cr mapped warehouse inventory account once per allocation.
  `NegativeCOGSObligation` links the allocation (legacy rows keep the
  warehouse_check link; a DB XOR constraint enforces exactly one source).
- Warehouse Check for allocated sales is custody-only with a
  per-warehouse allocation guard; legacy checks keep the legacy path.
  Cancellation is blocked by unresolved negative-COGS obligations and
  by return history on the allocation's issue.
- Custody placement remains a Warehouse-Check-time event from the
  unallocated ownership pool, bounded by the allocated quantity for
  that warehouse (audited invariant; checks against non-allocated
  warehouses or beyond allocated quantity are rejected).

## Verified evidence

Exact-head local SQLite/PostgreSQL suites, migration checks, and CI
evidence are recorded in PR #40's evidence comment. Revalidate the
exact current head before release; CI green alone is not accounting
approval.

## Decision status and release gate

- Decision A: **RESOLVED — A1 selected by owner on 2026-10-24.**
- Decision B: **RESOLVED — B1 selected by owner on 2026-10-24.**
- The PR #38 → #39/#40 implementation stack has since been integrated into
  `main`; PR #46 is also merged. Those integrations do not by themselves
  freeze Phase 8.
- Phase 8 remains open until its separately gated fulfillment, FUTURE-sale
  COGS, custody-accounting, cancellation/reversal, return, and release
  authorization/printing work is resolved, implemented, tested, and
  reviewed under the applicable contracts.
