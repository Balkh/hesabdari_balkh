# Draft PR — Phase 11: Transit loss valuation replay (purchase-wide final costing)

**Branch:** `phase/11-transit-loss-valuation` (based on PR #38 head
`ca663164ff83e4e22a40bafac8adbb833e4e5b7b`; `main` = `a0d570e`)
**Relationship to #38:** continues #38 — keeps its loss-evidence model and
fail-closed guards, adds the missing purchase-wide valuation replay.
**Status:** Draft. Do not merge without owner review. Not frozen.

## Problem
PR #38 records immutable transit-loss evidence but every downstream flow
stays blocked forever (`PENDING_PURCHASE_WIDE_REPLAY`): no replay ever
revalues surviving units, so a confirmed loss can never be finalized and
account 1430 keeps the lost units' cost.

## Accounting / quantity invariants
- `G = N − L` per purchase line/lot; never blended across purchases.
- Final unit (AFN) = (invoice base AFN pool + posted landed AFN pool) / G,
  4dp HALF_UP, journals at 2dp — existing money contract.
- Lost units' AFN cost leaves 1430 and is absorbed by surviving units:
  warehouse stock (AVCO replay), COGS 5100, transfers, sales/purchase
  returns; visible `ROUNDING_RESIDUAL` absorbs 4dp/2dp remainder so
  total credited from 1430 equals `old_unit × L` exactly.
- No new accounts, no fabricated landed-cost document: journals anchor to
  the new immutable `TransitLossValuationAdjustment` (loss-event FK).
- Posted journals/movements are never edited; compensating journals only.

## Implementation summary
- `post_transit_loss_valuation()` in `purchases/landed_cost_posting.py`
  reuses `_simulate_product` / `_extra_cost_map` (no second engine).
- `record_transit_loss()` posts evidence + lot closure + replay in one
  transaction; failure rolls everything back.
- Guards block only *unvalued* losses; after posting,
  `_good_quantity_for_line()` returns G for later landed costs.
- Residual direction bug found by the 10,000-unit test fixed and covered.

## Migration summary
`goods_in_transit/0004_transit_loss_valuation.py`: valuation snapshot
fields on `TransitLossEvent` (all nullable/defaulted — safe for existing
rows) + new `TransitLossValuationAdjustment` table. `makemigrations
--check` clean; full `migrate` verified on a fresh PostgreSQL database.

## Tests and actual results (local, tied to this branch head)
- SQLite full backend: **893 passed, 6 skipped** (PG-only tests skip).
- PostgreSQL full backend (`config.settings.postgres`, real PG server):
  **899 passed, 0 skipped** — including new PG-only concurrency tests
  (duplicate same-key finalization posts once; conflicting keys: one
  success, one safe rejection, one event).
- Focused new scenarios: 10,000 units in 5 trips with loss 30
  (denominator 9,970), transit sale, warehouse sale, transfer, sales
  return, landed costs before/after loss, exact retry, rollback,
  failure-then-retry, closed-period rejection, posted-history immutability.
- Frontend `npm run build` + `npm test` pass. Tauri `cargo check` not
  run — cargo unavailable in this environment (no Tauri files changed).

## Known limitations
- Direct transit purchase returns on the lot fail closed before loss.
- Loss of already transit-sold (customer-owned) units is outside the
  retained rule `L == remaining company-owned quantity`.
- No reversal flow for a posted loss valuation; no GitHub CI run for this
  head yet (branch not pushed from the authoring environment).

## Owner / accountant review checklist
- [ ] Confirm loss cost is capitalized over good units (no loss-expense account).
- [ ] Confirm residual-to-COGS treatment at 4dp/2dp rounding.
- [ ] Confirm fail-closed stance on transit purchase returns.
- [ ] Review exact-head CI (Backend, PostgreSQL, Frontend, Tauri) after push.
- [ ] Decide PR #19 (superseded; recommendation: close unmerged) and
      PR #36 (Draft sales API; locally merge-tested, needs fresh CI).
