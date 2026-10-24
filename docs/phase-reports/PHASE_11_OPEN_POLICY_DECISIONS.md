# Phase 11 — Open Policy Decisions Memo (for owner/accountant)

**Status:** Decision A resolved by owner clarification (2026-10-24); Decision B remains open. Phase 11 changes are not merged/frozen until exact-head CI and user review.
**Context:** PR #38 (head at time of writing includes the owner's
2026-10-23 addendum: loss cost is capitalized over good units; in-tolerance
rounding residual may go to 5100, out-of-tolerance rolls back) and PR #39
(transit-loss valuation replay, head `3b87f34`). Decision A is now resolved by the owner's 2026-10-24 clarification. Decision B remains open. This memo states the facts, a concrete example, the
options, and the minimum decision needed for each.

---

## Decision A — Direct purchase returns / supplier claims while goods are in transit

**Resolved by owner clarification on 2026-10-24; implementation added to PR #39 and awaiting exact-head CI.**

### Approved operating rule
- A posted supplier return reduces the purchased quantity and the purchase-invoice base value by the returned quantity at the original invoice unit cost. Its existing journal remains Dr 2110 / Cr 1430; posted history is never rewritten.
- A quantity still held by the supplier is not a warehouse receipt. It becomes received only when the physical receipt is recorded.
- Final wastage is determined after all purchase-wide trips/receipts have been accounted for. Returned quantity is not wastage.
- Final good quantity is **G = N − R − L**, where N is original purchase quantity, R is posted supplier-return quantity, and L is the final confirmed transit loss. The base-cost pool is reduced by R at the original purchase unit cost. Direct costs already incurred remain capitalized and are allocated over G.
- Transit completion reconciliation is **received quantity + posted supplier-return quantity + remaining owned Transit quantity = original quantity**.
- The posted loss valuation replays existing receipt/sale/warehouse destinations using compensating journals. No posted journal or stock movement is edited; account 1430 and destination accounts must reconcile, with the existing precision-derived residual tolerance unchanged.
- A return is not revalued as though the returned units were retained good inventory. The supplier claim remains at the original invoice unit cost under the owner’s stated rule; landed costs already incurred are allocated to surviving good units.

### Implementation / regression evidence
PR #39 removes the fail-closed return blocker and adds a regression scenario combining 100 purchased units, 980 AFN freight, 10 units returned, 88 physically received and 2 units lost. Expected good quantity is 88; final cost is (9,000 + 980) / 88 = 113.4091 AFN/unit (4dp HALF_UP); account 1430 should reconcile to zero and warehouse inventory to 9,980 AFN, subject to exact-head CI.

**Status:** owner policy resolved; technical approval remains gated on CI and review of the exact diff.

---

## Decision B — Reversal of an already-posted transit-loss valuation

### What exists today
- The general correction principle is reversal-only: `reverse_journal()`
  posts a compensating entry; `LandedCostReversal` reverses a landed-cost
  source journal and each of its valuation adjustments with linked
  `LandedCostReversalAdjustment` rows. Posted originals stay immutable.
- A posted `TransitLossEvent` valuation is intentionally **not**
  reversible: the snapshot is immutable (model + queryset + DB
  constraints), and `record_transit_loss()` cannot be "undone". A wrong
  loss report today has no in-system correction path; that is a control
  strength (no silent restatement) and an operational gap (a genuinely
  mistaken loss blocks the lot).

### What a reversal would have to decide
Reversing `k` compensating journals is the easy part. The hard parts:

1. **Lot state:** the loss consumed the remaining transit quantity and
   closed the lot (`remaining = 0`). Reversal must restore `remaining`
   to the pre-loss value and reopen the lot — a state transition the
   lot's immutability rules currently allow only for receipt/disposition
   events.
2. **Completion evidence:** the `TransitPurchaseCompletion` that gated
   the loss stays on record; a re-loss after reversal needs a rule on
   whether the same completion can gate a *corrected* second loss event
   (currently the model allows only one loss event per lot, enforced in
   service and model save).
3. **Subsequent activity:** landed costs or sales posted *after* the
   loss used denominator `G`. Reversing the loss changes their basis;
   the contract must state whether reversal is forbidden once dependent
   postings exist (recommended), or cascades into their replays.
4. **Periods:** reversal journals post on the reversal date under the
   usual open-period rules; the original loss date is untouched.

### Options for the owner
1. **Keep blocked (current).** Mistaken losses are corrected outside the
   lot workflow (e.g., owner-approved manual compensating journals via
   existing journal services, fully audited). No code change.
2. **Implement a governed reversal** modeled exactly on
   `LandedCostReversal`: a `TransitLossValuationReversal` record (date,
   reason, actor, idempotency), one compensating journal per original
   adjustment, lot quantity/status restored, event marked superseded
   (new status value, never deleted), reversal forbidden if any later
   posting depended on `G`, and a corrected new loss only under a fresh
   completion/loss cycle approved by the owner.
3. **Allow journal-only reversal** (reverse the compensating journals
   but leave the event POSTED and the lot closed). **Not recommended:**
   GL and quantity state would contradict each other.

**Minimum decision needed:** choose option 1 or 2; if 2, confirm the
"no reversal after dependent postings" rule and whether a corrected
second loss event on the same lot is acceptable.

**Recommendation (non-binding):** option 2 with the dependent-posting
guard, implemented as a separate reviewed PR. Until decided, option 1
stays in force.

---

## Also reviewed and confirmed (no decision needed)
- Loss of goods **already sold in transit / customer-owned**: the loss
  service requires `L == remaining company-owned quantity`, and purchase
  completion requires sold goods to be physically received first, so
  customer-owned quantity can never absorb company loss cost. Fail-closed
  and tested (`0be2296`).
- Sale before receipt, partial/multiple trips, transfers, sales returns,
  landed costs before/after loss: implemented and covered by the test
  suite on SQLite and PostgreSQL (see PR #39 evidence).

*This memo records unresolved policy only. PRs #38/#39 remain
unmerged and Phase 11 remains AWAITING USER REVIEW / NOT FROZEN.*
