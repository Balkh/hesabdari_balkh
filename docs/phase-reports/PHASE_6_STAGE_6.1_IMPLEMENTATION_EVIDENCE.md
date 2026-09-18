# PHASE 6 — STAGE 6.1 — INVENTORY FOUNDATION — IMPLEMENTATION EVIDENCE

## A. Repository State

```text
Branch:         phase/4
Starting HEAD:  2f65472 (Phase 5 FROZEN)
Ending:         uncommitted implementation on 2f65472 (NO commit per §41)
Working tree:   7 new inventory files + 1 one-line settings addition;
                untracked Phase-6 discovery doc untouched (still awaiting review)
origin/main:    unreachable from sandbox (no remote config); NOT frozen/merged/pushed
```

## B. Files Changed

| File | Why |
|---|---|
| `backend/inventory/__init__.py` | new app package (empty) |
| `backend/inventory/apps.py` | `InventoryConfig` (mirrors `PartyLedgerConfig`) |
| `backend/inventory/models.py` | `MovementType` (9 V1 types), `StockMovement`, `WarehouseInventoryAccount` |
| `backend/inventory/stock.py` | derivation ONLY: `movements_for`, `stock_for`, `avco_for` |
| `backend/inventory/services.py` | `receive_stock`, `issue_stock`, `open_stock`, mapping services |
| `backend/inventory/migrations/0001_initial.py` | schema (deps: accounting/currencies/products/warehouses) |
| `backend/inventory/inventory_tests.py` | 55 focused tests (§35) |
| `backend/inventory/.gitkeep` | deleted (replaced by the real app) |
| `backend/config/settings/base.py` | **one line**: `"inventory"` appended to `INSTALLED_APPS` (unavoidable app registration; additive, no behavior change) |

No other file changed. In particular: zero changes under `accounting`,
`fiscal_periods`, `categories`, `uom`, `products`, `parties`,
`warehouses`, `cash_accounts`, `exchange_houses`, `currencies`,
`core`, `security`, `documents`, `party_ledger`.

## C. Architecture

- **Entities**: `StockMovement` (immutable posted row: type/product/
  warehouse/signed-int-qty/date/currency/unit_cost-4dp/rate-4dp/
  rate_date/unit_cost_afn-4dp/temp-flag/qty_before/qty_after/reference/
  optional-journal/optional-idempotency-key) with 5 DB CHECKs (nonzero,
  direction-by-type, reference, cost≥0, rate>0); `WarehouseInventoryAccount`
  (explicit Warehouse→GL config, remappable, history untouched).
- **Movement model**: one table + 9-type family; 6.1 posts only OPENING,
  PURCHASE_RECEIPT, SALES_ISSUE. Signed qty: IN>0, OUT<0.
- **Stock derivation**: `SUM(quantity)` per (P,W); snapshots stored per row.
- **Cost model**: every row carries (currency, unit cost, rate, AFN unit
  cost). Issues at/above zero use running AVCO (AFN, rate 1); issues
  driven negative use a manually entered temp cost (any active currency).
  `unit_cost_afn = quantize_half_up(unit_cost × rate, 4)` via the ONE
  money engine (4dp = contract Unit-Price precision; `fx_equivalent` is
  2dp money and correctly NOT used for unit costs).
- **AVCO replay**: chronological; OUT legs relieve at running 4dp AVCO;
  touching zero discards the basis (mandatory reset); IN legs into
  negative stock fill the hole first, surplus establishes basis at the
  receipt's own cost; `None` when qty ≤ 0 (no basis → temp required).
- **Warehouse integration**: mapping lives in Inventory (Warehouse
  forbids the reverse ref); mapped account must be posting/active under
  1400; always read fresh (no stale cache); remap affects future only.
- **Accounting integration**: ONLY `open_stock` posts (Dr mapped-14xx /
  Cr 3900, source `OPENING_STOCK`, "JE" numbering) via frozen
  `post_journal`. `receive_stock`/`issue_stock` are movement-only
  (Purchase/Sales own their journals later).
- **Audit**: `record_audit_event` CREATE per movement (full snapshot in
  `new_state`; negative-ack text in `reason`); mapping CREATE/UPDATE
  (no-op → no audit, master convention).
- **Idempotency**: `idempotent_operation` + stored fingerprint for
  receive/issue (exact retry returns the original; mismatch rejected);
  `open_stock` rides the journal key and verifies the movement matches.

## D. Tests (executed commands, exact results)

```text
SQLite:
  pytest inventory/inventory_tests.py -q .... 55 passed (3.6s)
  pytest -q ............................. 627 passed (572 frozen + 55 new)
  manage.py test (test settings) ........ Ran 17, OK
  manage.py check ....................... 0 issues
  makemigrations --check --dry-run ...... No changes detected
  migrate fwd / inventory zero / fwd .... FWD-OK / REV-OK / FWD2-OK
PostgreSQL 17.11 (real server, postgres settings):
  pytest inventory/inventory_tests.py -q .... 55 passed
  pytest -q ............................. 627 passed (100s)
  manage.py test ........................ Ran 17, OK
  manage.py check ....................... 0 issues
  migrate inventory zero / fwd .......... PG-REV-OK / PG-FWD-OK
```

## E. Accounting Evidence (live demo, real output)

```text
JE JE-1404-00001 [OPENING_STOCK] 2026-01-15 USD rate=70.0000 afn_total=3850000.00
  Dr=55000.00 Cr=0.00 1410 Main Warehouse
  Dr=0.00 Cr=55000.00 3900 Opening Balance Equity
stock = 500 | avco = 7700.0000
```

No P&L account touched (test `test_no_pnl_accounts_in_opening` asserts
ASSET/EQUITY only). Warehouse-specific leaves proven by
`test_opening_is_warehouse_specific` (1410 vs 1420).

## F. Negative Stock Evidence

`test_negative_stock_allowed`: 0 − 1000 → **−1000**, temp 5.0000 AFN,
`is_temporary_cost=True`. `test_acknowledgement_enforced`: without the
flag the service raises `WARNING: this issue drives stock negative
(0 -> -10)` and posts nothing. `test_no_reference_price_substitution`:
product ref price 999 ignored — AVCO/temp used instead.
Demo: `after neg-issue: stock = -100 | temp = 7500.0000 AFN | avco = None`.

## G. AVCO Evidence

`test_avco_blend_four_decimals`: 100@10 + 50@20 → **13.3333**.
`test_zero_stock_cost_reset`: 100@110 exhausted → `avco None`; next
receipt @125 → **125.0000** (no carry). Demo blend: (500×7700+100×10)/600
→ **6418.3333**. `test_partial_hole_fill_establishes_receipt_basis`:
−100 then +150@10 → stock 50 @ **10.0000**.

## H. Atomicity Evidence

`test_failed_opening_leaves_no_partial_state`: `post_journal` mocked to
raise → `StockMovement` 0, `JournalEntry` 0, `AuditEvent` delta 0.
`test_receive_retry_returns_original`: same key twice → one movement,
audit delta 0 on retry.

## I. Idempotency Evidence

Receive/issue/opening exact retries return the ORIGINAL row (counts stay
1). Mismatches rejected: `test_receive_retry_mismatch_rejected`
(InventoryValidationError), `test_opening_retry_different_operation_rejected`
(JournalValidationError from the frozen fingerprint),
`test_opening_retry_different_product_rejected`
(InventoryValidationError from the movement-match check).

## J. Immutability Evidence

`test_posted_movement_cannot_be_updated_or_deleted`: `save()` and
`delete()` raise `PostedImmutabilityError` (reused); row unchanged.
`test_history_immutable_after_later_receipt`: stored cost/rate/AFN
byte-identical after later receipts.

## K. Frozen Surface Diff

Tracked diff = **2 files**: `base.py` one-line INSTALLED_APPS addition
(shown in §B) + `.gitkeep` deletion. All frozen behavior byte-identical;
627-test matrix green on both engines (572 pre-existing tests untouched
and passing). Single-engine proof: one `cogs` (money.py:47), one
`post_journal` (accounting/services.py:152), one `record_audit_event`,
one `idempotent_operation` — all reused, none duplicated. No new
money/currency/audit/idempotency/numbering/journal code exists under
`backend/inventory/`.

## L. Known Limitations (deferred to later stages)

Sales/purchase/transfer/adjustment/return workflows; shortage
settlement; COGS journals on issue; receipt journals; secondary-UOM
transactions (6.1 records primary-UOM quantities); movement numbering
(no prefix invented); report suite; APIs/UI/admin.

## M. Status

**IMPLEMENTATION COMPLETE → AWAITING USER REVIEW**
