# Draft PR — Phase 11: Transit loss valuation replay (purchase-wide final costing)

**Branch:** `phase/11-transit-loss-valuation`
**Current integration base:** PR #38 branch `phase/11-transit-final-unit-cost`, head `e1dd1eb9991a2ddbe03a95f632d066b312e6904c`.
**Integration commit:** `a080f395772f8d2f7d598deddd576c29cc095c24` (tree preserves the tested code; branch history now includes the current base).
**Status:** Draft. Do not merge without owner/accountant review. Not frozen.

## Problem
PR #38 records immutable transit-loss evidence but downstream flows need a purchase-wide replay to revalue surviving units, so a confirmed loss can be finalized without leaving the lost units' cost in account 1430.

## Accounting / quantity invariants
- `G = N − R − L` per purchase line/lot: original quantity minus posted supplier returns (R) and confirmed final loss (L); never blended across purchases.
- Final unit (AFN) = (invoice base AFN pool + posted landed AFN pool) / G, 4dp HALF_UP; journals at 2dp — existing money contract.
- Lost units' AFN cost leaves 1430 and is allocated to surviving units' destinations: warehouse stock (AVCO replay), COGS 5100, transfers, and supported returns; visible `ROUNDING_RESIDUAL` is bounded by a precision-derived tolerance and reconciled against actual journal lines.
- No new accounts or fabricated landed-cost document: journals anchor to immutable `TransitLossValuationAdjustment` rows linked to the loss event.
- Posted journals/movements are never edited; compensating journals only.

## Implementation summary
- `post_transit_loss_valuation()` in `backend/purchases/landed_cost_posting.py` reuses `_simulate_product` / `_extra_cost_map` (no second engine).
- `record_transit_loss()` posts evidence + lot closure + replay in one transaction; failure rolls everything back.
- Guards block only unvalued losses; after posting, `_good_quantity_for_line()` returns G for later landed costs.
- Hardening closes queryset mutation and `bulk_create` bypasses for transit-loss events; regression coverage was added.

## Migration summary
- `goods_in_transit/0004_transit_loss_valuation.py`: valuation snapshot fields and `TransitLossValuationAdjustment` table.
- `goods_in_transit/0005_transit_loss_snapshot_constraints.py`: database-level snapshot completeness constraints.
- Migration checks were reported clean on earlier commits; revalidate on the final exact head.

## Test evidence — historical evidence versus current CI
- Earlier local evidence documented on prior heads: SQLite 923 passed / 6 skipped and PostgreSQL 929 passed / 0 skipped. These figures are historical and are **not** a substitute for testing the current exact head.
- GitHub CI run 412 passed all four jobs (Backend, PostgreSQL, Frontend, Tauri) on commit `1386f6fc4f63e5942033c566c7af13bfd21e0b1f`.
- The integration commit above was created after that run. CI must be checked again on the final head after this documentation refresh; do not infer success from the earlier run.

## Known limitations (fail closed)
- Direct transit supplier returns reduce the base purchase pool at original invoice unit cost; incurred direct costs remain capitalized and are allocated over surviving good quantity. Regression coverage combines return + freight + final loss.
- Loss of already transit-sold (customer-owned) units is outside the current rule `L == remaining company-owned quantity`.
- No reversal flow for a posted loss valuation yet.

## Owner / accountant review checklist
- [ ] Confirm loss cost is capitalized over good units (no separate loss-expense account).
- [ ] Confirm bounded residual treatment and destination accounting at 4dp/2dp rounding.
- [x] Owner clarified transit-return + final-loss treatment on 2026-10-24; regression added. No-reversal limitation remains.
- [ ] Review exact-head CI (Backend, PostgreSQL, Frontend, Tauri) on the final commit.
- [ ] Decide disposition of PR #38, PR #19 (possibly superseded), and PR #36 (Draft Sales API).

Workflow: INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → FROZEN.
Not merged; awaiting owner/accountant review.
