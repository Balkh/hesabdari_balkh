# Phase 11 — Transit-Loss Valuation Replay: Exact Formula & Journal Design

**Status:** Implemented on `phase/11-transit-loss-valuation`
(base: PR #38 head `ca663164ff83e4e22a40bafac8adbb833e4e5b7b`; `main` = `a0d570e`).
Local evidence only — see §10. Not approved, not frozen.
**Workflow:** INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → FROZEN.
This document records the design decision required by the handoff. It does not
claim implementation, test success, approval, or freeze.

## 1. Problem

PR #38 adds immutable `TransitLossEvent` evidence and fail-closed guards: once a
loss exists, landed-cost posting, transit receipts/transfers, transit sales and
transit sales-returns are all blocked because `_good_quantity_for_line()` raises.
No purchase-wide valuation replay exists, so a confirmed loss can never be
finalized. This design adds that replay, reusing the existing AVCO replay in
`purchases/landed_cost_posting.py` (`_simulate_product`, `_extra_cost_map`).

## 2. Definitions (per purchase line / transit lot)

- `N` = lot `original_quantity` = purchase-line quantity (asserted equal).
- `L` = confirmed loss quantity (single final event; service requires
  `L == lot.remaining_quantity` at recording, `0 < L < N`).
- `G = N − L` = good quantity.
- Base pool (transaction currency) = line `net_total + freight_allocated`;
  `lot.unit_cost = q4(base_pool / N)` (existing snapshot, never rewritten).
- Base pool (AFN) per unit `old_base_afn = q4(lot.unit_cost × lot.rate)`
  (matches `StockMovement.unit_cost_afn` of transit receipts).
- Landed pool (AFN) = Σ `afn_amount` of posted, non-reversed
  `LandedCostAllocation`s for this line.
  `old_landed_afn_per_unit = q4(landed_pool_afn / N)` (existing convention:
  sum exact AFN first, round once per unit at 4dp).
- `old_unit_afn = old_base_afn + old_landed_afn_per_unit`
- `new_unit_afn = q4((old_base_afn × N + landed_pool_afn) / G)` — i.e. the
  whole AFN cost pool (invoice-backed base cost + all posted direct costs)
  divided by good quantity. Equivalent form used for the replay delta:
  `delta_per_unit_afn = new_unit_afn − old_unit_afn` (4dp).
- Example (contract): 10,000 bbl; pool $173,000 (170,000 + 3,000 direct);
  L=30, G=9,970 → final unit = 173,000 / 9,970 ≈ $17.3521 (in AFN terms the
  same formula with AFN pool). No-loss case: L=0 is rejected as an event;
  denominator stays N (existing behaviour).

## 3. Accounting identity (per lot, AFN)

Before loss, 1430 holds `old_unit_afn × L` for the lost units (receipts and
transit sales already credited 1430 at the old unit; remaining before loss is
exactly L by the service rule, and lot is closed to 0 at recording).
After finalization every surviving unit carries `new_unit_afn`, so:

```
Σ Dr destinations  =  delta_per_unit_afn × G   (≈ old_unit_afn × L, ±rounding)
Cr 1430            =  Σ Dr destinations          (residual rule §5)
1430 balance for lot after posting = 0
```

No new money is created: the lost units' cost is absorbed by surviving units.
There is **no** separate loss-expense (e.g. 5xxx wastage) journal — the
approved contract capitalizes total cost over good units only.

## 4. Destinations of the delta (compensating journals only)

All journals are AFN (base currency, rate 1), source
`TRANSIT_LOSS_VALUATION_ADJUSTMENT`, anchored to a new immutable
`TransitLossValuationAdjustment` row (loss event FK, type, movement FK,
amount_afn, journal OneToOne) — the durable anchor the handoff requires,
mirroring `LandedCostValuationAdjustment` (which cannot be reused because it
requires a `LandedCostDocument` parent that a loss does not have).

| Destination | Journal | Computed by |
|---|---|---|
| Warehouse stock still on hand | Dr warehouse acct / Cr 1430 | AVCO replay ending-basis delta per warehouse |
| Warehouse sales already issued | Dr 5100 COGS / Cr warehouse acct | AVCO replay relief delta per SALES_ISSUE |
| Transfers | Dr in-warehouse / Cr out-warehouse | AVCO replay relief delta per TRANSFER_OUT |
| Sales returns (warehouse) | Dr warehouse / Cr 5100 | AVCO replay inbound delta per SALES_RETURN |
| Purchase returns | supplier-claim vs inventory split, COGS variance plug | same rule as `_post_purchase_return_adjustment`, anchored to loss event |
| Transit sales (no movement) | Dr 5100 / Cr 1430 | `q2(delta_per_unit × allocated qty)` per `TransitSaleAllocation` |
| Transit sales returns | Dr warehouse / Cr 5100 | their return movement carries the virtual layer in `_extra_cost_map`; AVCO SALES_RETURN delta covers it |
| Negative-stock obligations resolved by a transit receipt | Dr 5100 / Cr 1430 | `NegativeCOGSReceiptAllocation` qty × delta, as in landed-cost code |
| Customer custody (sold transit goods physically arrived) | no company journal | custody goods are customer-owned; their cost already left 1430 via transit-sale COGS, adjusted by the Transit-sale row above |
| Remaining transit | none | remaining is 0 after the loss event by construction |

Replay mechanics: build `baseline_extra` with denominator N for this line and
`revised_extra` with the loss delta layer added on exactly the movements
`_extra_cost_map` already targets (transit receipt movements + transit
sales-return movements), then run the existing `_simulate_product` for the
product. This keeps one valuation engine.

## 5. Rounding / residual

Per-unit values are 4dp HALF_UP; journal amounts 2dp. The identity in §3 is
enforced exactly: total Dr to destinations is computed from the replay, and a
single `ROUNDING_RESIDUAL` adjustment (Dr/Cr 5100 vs 1430, visible, anchored)
absorbs any cent residual so Cr 1430 equals the pre-loss 1430 lot remainder
`q2(old_unit_afn × L)` traced from journals. If the residual cannot be placed
(no destination), fail closed and roll back.

## 6. Atomicity, idempotency, guards, periods

- `record_transit_loss()` stays the single entry point: validation → event →
  lot closure → valuation replay → audit, all in one transaction. Any replay
  failure rolls back event, closure, journals, adjustments and audit.
- Exact retry (same key + same payload) returns the existing event without
  reposting, even if the period later closed; same key/different payload
  rejects (existing behaviour, preserved).
- New loss posting requires the loss date in an open fiscal period (existing
  gate); replay journals post on the loss date.
- `TransitLossEvent` gains `valuation_status` (`PENDING`→`POSTED`),
  `good_quantity`, `final_unit_cost_afn`, `valuation_posted_at`.
  Guards (landed cost, receipt, transfer, transit sale, transit return) block
  only while a loss is `PENDING`; after `POSTED`, `_good_quantity_for_line`
  returns G so later landed costs divide by G and their own replay builds on
  the loss-adjusted basis (baseline includes the loss layer — see §7).
- Posted journals/movements are never edited; correction is reversal-only
  (out of scope here; a wrong loss remains fail-closed for manual review).

## 7. Interaction with later landed costs

`_extra_cost_map` must include the posted loss layer in both baseline and
revised maps for any later landed-cost posting touching this product:
receipt/return movements of a loss-finalized lot get
`loss_delta_per_unit_afn` (recomputable deterministically from the posted
event + posted landed allocations **at loss time** — therefore the event
persists `landed_pool_afn_at_valuation` snapshot so later recomputation is
stable even after new landed costs arrive; new landed costs then divide by G
via `_good_quantity_for_line`).

## 8. Scenario → expected result (tests must prove each)

1. No receipt/sale yet, loss = all remaining (requires prior accounting of
   other units, so this reduces to: receipts only) — covered by 2–4.
2. Loss after partial receipts, goods on hand: Dr warehouse / Cr 1430;
   1430 lot balance → 0; ending AVCO = new unit.
3. Loss after warehouse sale: COGS increased for sold qty; on-hand for rest.
4. Loss after transit sale: Dr 5100 / Cr 1430 for sold qty; custody arrival
   creates no company stock value.
5. Loss with prior landed cost: pool includes it; later landed cost divides
   by G, no double count.
6. Sales return / purchase return / transfer before loss: replay deltas per §4.
7. Rejections: zero/over loss, loss ≥ N, duplicate/conflicting key, closed
   period, temporary-cost or negative-stock ambiguity in replay → whole
   transaction rolls back (no event, lot unchanged, no journals).
8. Purchase isolation: loss on lot A does not change lot B (same product)
   denominators; product-level AVCO replay still pools warehouse stock as
   existing rules require.
9. No loss: unchanged behaviour (denominator N everywhere).

## 9. Out of scope / fail-closed

- Multiple loss events per lot (service already rejects).
- Loss while `remaining_quantity` still contains unarrived company goods
  not yet accounted (service rule L == remaining is retained).
- Reversal of a posted loss valuation (reversal-only framework extension is
  a separate reviewed change; until then a posted loss is immutable).

## 10. Implementation & local evidence (2026-10-17)

Implemented: `TransitLossEvent` valuation snapshot fields +
`TransitLossValuationAdjustment` anchor (migration
`goods_in_transit/0004_transit_loss_valuation`), `post_transit_loss_valuation()`
reusing `_simulate_product`/`_extra_cost_map`, atomic call from
`record_transit_loss()`, guards narrowed to *unvalued* losses only,
`_good_quantity_for_line()` returns G after posting.

Local evidence on this branch (SQLite, Python 3.13):
- New `goods_in_transit/transit_loss_valuation_tests.py`: receipt-only,
  transit-sale, warehouse-sale, transfer, sales-return, landed-cost
  before/after loss, exact retry, rollback-on-failure, no-loss — all exact
  AFN balances for 1430 / warehouse accounts / 5100 asserted.
- Full backend pytest: **873 passed, 4 skipped** (before this change the
  focused baseline on PR #38 head was 250 passed / 4 skipped).
- `manage.py check`: no issues. `makemigrations --check`: no changes.
- Frontend: `npm run build` OK, `npm test` OK (no frontend changes).

Limitations / still fail-closed:
- Direct transit purchase returns on the lot block loss valuation.
- Loss of customer-owned (already transit-sold) units is outside the
  retained service rule `L == remaining company-owned quantity`.
- No PostgreSQL or GitHub CI evidence for this branch's exact head yet;
  no reversal flow for a posted loss valuation.
- PR #19 (`phase/8-sales`, merge-base at Phase 4 merge `e65a73a`) is a
  divergent historical Sales implementation already superseded on `main`;
  recommendation: do not merge. PR #36 (`phase/8-sales-api-foundation`)
  merged cleanly into current `main` in a local scratch worktree and its
  sales tests passed locally (33 passed, 1 skipped); it remains a Draft
  and needs fresh exact-head CI + contract review before any merge.

## 11. Verification round 2 (master execution prompt)

- Added master scenarios: 10,000 units / 5 trips / loss 30 (denominator
  9,970 — caught and fixed a ROUNDING_RESIDUAL debit/credit direction bug
  for negative residuals), posted-history immutability snapshot,
  closed-period rejection with rollback, failure-then-retry.
- PostgreSQL (real server, `config.settings.postgres`): full backend
  **899 passed, 0 skipped**, including new PG-only concurrency tests in
  `goods_in_transit/transit_loss_concurrency_tests.py` (same-key duplicate
  finalization posts once and returns the same event; conflicting keys
  produce exactly one event/journal set).
- SQLite: **893 passed, 6 skipped** (the 6 skips are PostgreSQL-only
  concurrency tests, by design).
- Fresh-database PostgreSQL `migrate` + `migrate --check`: clean.
- Frontend build/tests pass; Tauri cargo check unavailable in this
  environment (no Tauri files changed).
- Draft PR text: `PHASE_11_TRANSIT_LOSS_PR_DESCRIPTION.md`.
- Still no GitHub CI evidence for this head: the authoring environment
  cannot push. Ready for owner review once pushed and exact-head CI runs.

## 12. Security-hardening round (Findings A & B)

**Finding A — fabricated POSTED snapshot (REPRODUCED, FIXED).**
Reproduction on `bdceee5`: `event.save(update_fields=[...])` accepted
`good_quantity=1, final_unit_cost_afn=99999` with zero journals, and
`QuerySet.update()` bypassed `save()` entirely. Root cause: the model
allowed *any subset* of valuation fields from *any* caller, and no
queryset guard existed. Fix:
- `TransitLossEvent.save()` now permits exactly one write after creation:
  the complete `VALUATION_UPDATE_FIELDS` set, targeting POSTED, with all
  snapshot fields present and consistent (`good == lot.original − loss`,
  non-negative costs, timestamp), and only when the posting service set
  the private per-instance `_valuation_posting_authorized` flag.
- `TransitLossEventQuerySet` closes `update`/`bulk_update`/`delete`.
- Creating an event already POSTED is rejected.
- Migration `0005_transit_loss_snapshot_constraints`: DB CHECK
  constraints (POSTED ⇒ complete snapshot; PENDING ⇒ no posted
  timestamp; positivity). Cross-table quantity consistency stays in the
  posting transaction (CHECK cannot join the lot table) — documented
  boundary.
- `TransitLossValuationAdjustment.save()` now refuses any journal that
  is not a posted `TRANSIT_LOSS_VALUATION_ADJUSTMENT` entry linked to
  the same loss event: no evidence row without its journal.

**Finding B — unbounded ROUNDING_RESIDUAL (REPRODUCED, FIXED).**
Reproduction: with a transit-sale allocation missing during valuation,
an 81.63 AFN discrepancy (40 units, not rounding) was silently posted
to COGS and the event marked POSTED. Root cause: residual had no bound
and no destination-side verification. Fix:
- `_loss_rounding_tolerance_afn(G, terms) = 0.0001*G + 0.005*terms +
  0.005` AFN, derived from the precision contract (two 4dp roundings
  per unit; one 2dp rounding per summed amount and for the expected
  value). Beyond tolerance → `LandedCostPostingError`, full rollback.
- After posting, destination-side reconciliation is recomputed from
  actual journal lines: journals balance, no shared journal between
  adjustments, net credit out of 1430 == net debit into destinations
  == `old_unit × L`.

**Related-issue classification (§6 of the hardening prompt):**
- Fixed here: fabricated POSTED, queryset bypass, adjustment-without-
  journal, unbounded residual, destination reconciliation.
- Already safely handled (regression-tested previously): duplicate /
  conflicting idempotency keys, concurrent finalization on PostgreSQL,
  closed-period rejection, atomic rollback, posted-history immutability,
  purchase-lot isolation, landed costs before/after loss.
- Deliberately fail-closed: direct transit purchase returns on the lot;
  loss of already transit-sold (customer-owned) units.
- Unresolved / owner decision: reversal flow for a posted loss
  valuation; CI on exact head (workflow triggers exclude stacked base).

**Evidence (this round):** SQLite full **923 passed, 6 skipped**
(PostgreSQL-only concurrency skips by design); PostgreSQL full
**929 passed, 0 skipped** incl. concurrency tests; fresh-PG migration
clean; `makemigrations --check` clean; Django check clean.
