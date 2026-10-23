# Phase 11 — Open Policy Decisions Memo (for owner/accountant)

**Status:** AWAITING OWNER DECISION. Nothing in this memo is implemented.
**Context:** PR #38 (head at time of writing includes the owner's
2026-10-23 addendum: loss cost is capitalized over good units; in-tolerance
rounding residual may go to 5100, out-of-tolerance rolls back) and PR #39
(transit-loss valuation replay, head `3b87f34`). Two matters were
explicitly **not** decided by that addendum. Both are currently
fail-closed in code. This memo states the facts, a concrete example, the
options, and the minimum decision needed for each.

---

## Decision A — Direct purchase returns / supplier claims while goods are in transit

### What exists today
- `post_transit_purchase_return()` (purchases/services.py) posts
  Dr 2110 (supplier payable) / Cr 1430 at the lot's *original* unit cost
  (`lot.unit_cost`), reduces `remaining_quantity`, and creates an
  immutable `PurchaseReturn(transit_lot=...)`. Supplier refunds against it
  settle through the existing supplier-refund implementation.
- Warehouse purchase returns (after physical receipt) already flow
  through the AVCO replay in landed-cost/loss valuation: the supplier
  claim is kept at source-receipt cost and the difference is an explicit
  COGS variance (`_post_loss_purchase_return_adjustment`). That path is
  supported and tested.
- **Blocked combination:** if a posted direct transit purchase return
  exists on the lot, `post_transit_loss_valuation()` raises
  *"Transit purchase returns must be resolved before transit loss
  valuation"* and `record_transit_loss()` rolls back completely (no loss
  event, lot unchanged, no journals). Regression test:
  `test_direct_transit_purchase_return_fails_closed_before_loss`.

### Why it is blocked (worked example)
Purchase 100 units × 100 AFN = 10,000 AFN (Dr 1430). Before final
reconciliation, 10 units are returned to the supplier directly from
transit: claim posted Dr 2110 / Cr 1430 = 1,000 AFN at the old unit cost.
The other 88 arrive, 2 are confirmed lost, 880 AFN of direct costs were
posted. Final unit cost = (10,000 + 880) / 98 = **111.0204 AFN** — but
which units does the claim cover?

- If the returned 10 units are valued at the final unit, the claim
  should be 1,110.20 AFN, not 1,000.00: a further Dr 2110 / Cr ? —
  110.20 AFN must come from somewhere (the surviving units' cost pool),
  and the good-quantity denominator changes meaning: is `G = 88`
  (survivors only) with the pool reduced by the final claim, or
  `G = 98` with the claim treated as one more "destination" of the pool
  (the same way warehouse purchase returns are handled in the replay)?
- The current contract defines `G = N − L` (98 here), which counts the
  returned units as "good". That is coherent **only if** the claim is
  simultaneously revalued to the final unit cost, mirroring the
  warehouse purchase-return treatment. Revaluing the claim without
  owner approval would invent a supplier-claim policy; not revaluing it
  would leave the claim understated by 110.20 AFN.

### Options for the owner
1. **Keep fail-closed (current behavior; zero accounting risk).** A lot
   with a direct transit return cannot finalize a loss until the return
   combination is decided. Operational workaround: reverse the transit
   purchase return (existing reversal restores the lot) before loss
   finalization, if business-correct.
2. **Mirror the warehouse contract:** denominator stays `G = N − L`;
   on loss finalization the transit claim is adjusted by a compensating
   journal Dr/Cr 2110 vs 1430/COGS variance so the claim equals
   returned-qty × final unit cost. Requires: approval of the claim
   revaluation rule, of the COGS-variance destination, and of behavior
   when a supplier refund was already settled at the old claim amount.
3. **Exclude returned units from the denominator** (`G = N − L − R`,
   pool reduced by the claim at *original* cost). Simpler claim story,
   but contradicts the addendum's `G = N − L` definition and changes the
   final unit cost for every other destination.

**Minimum decision needed:** choose option 1, 2, or 3; if 2, confirm the
claim-revaluation journal destinations (2110 vs 1430/5100) and the
already-settled-refund rule.

**Recommendation (non-binding):** option 2, because it reuses the exact
treatment already approved and tested for warehouse purchase returns in
the same replay engine, and keeps one denominator definition across the
project. Until decided, option 1 stays in force.

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
