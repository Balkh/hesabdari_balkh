# PHASE 6 — INVENTORY ARCHITECTURE DISCOVERY (FINALIZED, NO IMPLEMENTATION)

**Status:** DISCOVERY FINALIZATION COMPLETE → AWAITING USER REVIEW.
No models, migrations, services, APIs, serializers, views, URLs,
frontend, UI, admin, engine, or report code created or modified.
No commit, merge, or push. No production file touched.
**Method:** contract section + line, or repo path + line, for every
claim. Contract: `docs/phase-0/PHASE_0_CONTRACT_V2.1.md` (3510 lines).
Finalization incorporates the user's confirmed business rules; anything
neither in the contract nor in the confirmed rules is an OPEN question.

---

## 1. REPOSITORY BASELINE (inspected, not remembered)

```text
Branch: phase/4 — HEAD: 2f65472 (Phase 5 FROZEN, user-approved)
Working tree: clean except this untracked discovery doc (tracked diff 0 lines)
Remote: origin unreachable from sandbox (no remote config, no credentials);
  local origin/main ref 646e35e is STALE (last fetch 2026-09-15) and NOT
  presented as current state.
backend/inventory/ = .gitkeep ONLY. No movement/stock/Kardex/AVCO engine
  anywhere (mention-only hits: money.py cogs() + G08/G09 goldens, Product
  docstring "No stock, no valuation, no AVCO/COGS, no movements, no
  postings." products/models.py:9, Warehouse docstring). No inventory
  migrations, APIs, or frontend. Django check 0 issues; P5 golden 12/12.
```

## 2. CONTRACT REFERENCES (inventory-complete)

§4.1 master L914–930 · §4.2 price supremacy L932–936 · §4.3 smart
pricing L938–946 · §4.4 warehouse stock L954–956 · §4.5 equation
L958–971 · §4.6 AFN valuation L973–985 · §4.7 AVCO L989–1016 · §4.8
hist. COGS L1019–1023 · §4.9 negative L1025–1033 · §4.10 temp cost
L1035–1046 · §4.11 later receipt L1048–1058 · §4.12 multi-negative
L1060–1068 · §4.13 return basis L1070–1082 · §4.14 types L1084–1097 ·
§4.15 Kardex L1099–1113 · §4.16 goldens L1115–1135 · §3.11/3.12
precision L826–855 · §5.2 effects L1158–1169 · §5.4 freight L1202–1210
· §6.4/6.5/6.6 L1320–1357 · §8.4–8.7 returns L1573–1630 · §13.4/13.5
audit+approval L2588–2605 · §15.7–15.9 recon+rollback L2795–2858 ·
decisions L2963–2983 · roadmap L3160–3167.

## 3. FROZEN SURFACES (untouched, tracked diff 0 lines)

Phase 1 baseline · Phase 2 Accounting Core (JE/JL/post/reverse/
balances/FX/money/idempotency/audit/period gates/COA) · Phase 3 Fiscal
Periods · Phase 4.1 Categories/UOM/Products · Phase 4.2 Party Master ·
Phase 4.3 Warehouses · Phase 4.4 Cash Accounts + Exchange Houses ·
Phase 5 Party Ledger Attribution (FROZEN @ 2f65472). One environment
artifact found and restored: executable bit on scripts/verify_*.sh
(snapshot-restore mode drift, zero content lines). No other drift.

## 4. EXISTING INVENTORY-RELATED CODE

`backend/inventory/` = `.gitkeep` ONLY. `core/money.py` = ONE rounding
engine (Half-Up; 2dp money, 4dp rate; `cogs(qty,avco)` money.py:47;
NO `avco()` helper yet — the single justified addition at
implementation). Reuse map: Product/Warehouse/UOM/Party/Currency/
ExchangeRate masters, `post_journal` (accounting/services.py:152),
`record_audit_event` (security/services.py:6), `core/idempotency.py`,
`next_document_number`. No duplicate money/currency/audit/idempotency
files exist (verified by search).

## 5. PRODUCT ANALYSIS (§6 classes)

Identity: `code` unique + row. Master config: primary/secondary UOM +
factor (4dp, >0), min (3dp, ≥0), max/reorder (3dp, nullable, inert).
Inert reference: ref prices (4dp, nullable, NO currency), barcode,
brand, description. Future behavior: NONE in master (min/max/reorder
have zero behavioral spec). Transactional behavior MUST NOT move into
Product. Conversion at transaction time is new-but-necessary (no
helper exists; `resolve_uom` reused for lookups).

## 6. WAREHOUSE ANALYSIS

Flat master (id/name/name_fa/active/created_at). §4.4: independent
stock per warehouse. Business rule: warehouse = physical storage
location, NOT owner; goods stay business property in any warehouse
(Mohib / Mal Hassan / Omar Rahimi / other). NO location/bin (zero
evidence). NO warehouse↔GL mapping anywhere (see ID-6-15).

## 7. QUANTITY / UOM POLICY (user-confirmed — supersedes ID-6-04 draft)

V1 stock quantity is an INTEGER count of discrete stockable units
(sacks, barrels/drums, cartons). Never `498.6 sacks`. Fractional units
require a future contract/discovery decision. Design consequences:
canonical stock qty = integer in the stocking unit; movement rows
snapshot UOM pair + factor for history (§1.12/G6); V1-valid
conversions MUST yield integer stock counts (implementation validation
rule — follows from the integer rule + 4dp factor with no other
consistent reading). No second UOM engine; frozen masters untouched.

## 8. STOCK-SOURCE ANALYSIS

§4.5 equation DERIVES stock from immutable event classes; G3/G6 forbid
a second truth. Materialized balances rejected. Equation terms map
1:1 to the §14 movement family (Opening + 4 IN − 4 OUT).

## 9. MOVEMENT MODEL (user-confirmed taxonomy)

One canonical StockMovement concept + explicit type. Family:
PURCHASE_RECEIPT, SALES_ISSUE, SALES_RETURN, PURCHASE_RETURN,
TRANSFER_IN, TRANSFER_OUT, ADJUSTMENT_IN, ADJUSTMENT_OUT, OPENING.
Business documents (future) generate rows. Reference context preserved
per row: source document + receipt/check serial where applicable (§10
Gadam workflow: supplier context, warehouse, date, serial, received
qty, waste) + party linkage where the report set requires it (§25
dispatch/return reports, §9 traceability). Warehouse Receipt/Issue,
Stock Transfer, Inventory Adjustment, Physical Count exist ONLY as
doc-type/golden mentions (L1259/L1983–1988/L2256) — no semantics
specified; numbering prefixes for them are NOT yet specified.

## 10. TRANSFER MODEL (mechanics confirmed; one sub-question open)

Internal movement only: OUR Warehouse A → OUR Warehouse B (§15, §28).
Atomic IN+OUT pair, same qty, same cost basis; no purchase/sale/
revenue/expense/COGS/profit/loss; reject same-warehouse; no partial
edits of posted transfer; correction via controlled reversal.
Settlement-by-goods (paying a party with goods) is NOT a transfer —
future Party/Settlement layer. OPEN sub-question: GL legs (see
ID-6-06 — new evidence §29 lists transfer WITHOUT accounting while
receipt/issue/return pair WITH accounting; still not explicit).

## 11. ADJUSTMENT MODEL

Types exist; authorization = audited + V1-simplifiable approval
(§13.4/13.5: no approval workflow required in V1 single-user).
Unspecified: IN cost basis + GL offset account (COA has NO
shrinkage/gain account — any new account touches the frozen COA).
Waste and shortage are NOT one generic adjustment (see §13/§14).
See ID-6-08 (OPEN core).

## 12. OPENING STOCK MODEL (shape confirmed; counter-account open)

No lot-level reconstruction (§16). Captures per (P,W): current qty
(integer) + approximate current cost + currency + historical/manual
rate context + date. From go-live, receipts carry actual cost basis.
Counter-account: 3900 specified ONLY for party balances (§2.12) →
inventory use is inference, NOT text. See ID-6-07 (OPEN core).

## 13. ACTUAL-COST PRINCIPLE (user-confirmed)

Purchase Price + Transportation + Loading/Unloading + Waste + Misc =
Actual Cost of Goods. AFN-paid legs may carry a MANUAL shipment/
transaction rate; historical rates preserved, never rewritten by
current global rates (§1.12). No second currency engine (reuse
Currency/ExchangeRate/money). Boundary: the landed-cost ALLOCATION
engine itself is out of scope — the formula is the business principle;
receipt cost aggregation lives in the future Purchase domain and calls
inventory receive() with the resulting unit cost.

## 14. WASTE VS SHORTAGE (user-confirmed distinction — never collapse)

Waste (receipt-time): gross received − usable = waste; shipment cost
allocated over NET usable qty: `Total Shipment Cost ÷ Net Usable Qty
= Actual Cost per Usable Unit` (e.g. $200,000 ÷ 1,997). Waste raises
unit cost; it is not a note. Shortage (later): expected usable −
physical count; responsibility valued at CURRENT/DAY MARKET RATE, not
inventory cost. NEW GAP: no market-rate source exists (ref prices are
inert, undated, currency-less). Smallest proposal for review:
user-entered rate captured at shortage-claim time; inventory movement
(if any) stays at AVCO, responsibility value computed at report/claim
time. No new master without approval.

## 15. AVCO ANALYSIS (confirmed + zero-reset)

Literal formulas (§4.7): AVCO = Total AFN Cost ÷ Total Qty (4dp);
receipt: (prevCost + newCost)/(prevQty + newQty); COGS = Qty × AVCO@post
(2dp, `cogs()` reused). AFN-authoritative (§4.6/L2977); original
currency/amount/rate/AFN-equiv preserved per movement. Changes on:
receipt, opening (prev=0 reduces to unit cost), transfer-IN (dest
formula), adjustment-IN (per ID-6-08 cost), sales return (original
basis §4.13). Issues/consumptions never change AVCO. ZERO-RESET
(mandatory, §19/§21): at true zero, the next receipt starts from its
own cost ($23.90, not carried $24.00) — exact-then-round per money
contract, no remainder tracking. Discount-net vs gross for cost: NOT
specified (PI Discount is a field only) — minor noted sub-point.

## 16. RETURN-COST DECISIONS

Sales return: ORIGINAL recorded cost basis, never today's AVCO;
temp-corrected sales → controlled historical cost-basis record
(§4.13/L2983) — SETTLED. Purchase return: SETTLED by user rule —
original purchase/receipt cost basis (200 × $110 = $22,000), traceable
to supplier/product/invoice/qty/cost/warehouse; never market/AVCO/new-
rate/estimated; no over-return beyond the referenced receipt (exact
cap rule belongs to the eventual purchase/return contract).

## 17. MULTI-CURRENCY (confirmed)

Per-movement where applicable: txn currency + unit cost + historical
rate + AFN equivalent (§4.6 + PI Currency/Rate/RateDate L1184–1186).
AFN-authoritative valuation; no restatement (§1.12). No new FX.

## 18. RECONCILIATION (concept confirmed; mapping open)

Operational truth (P,W: what/where/how-much/at-what-value) vs
financial truth (GL authoritative). Recon invariants: (a) stock = Σ
posted movements per (P,W); (b) every qty on exactly one (P,W);
(c) value = AVCO result; (d) "Inventory ledger ↔ inventory account"
(L2833); (e) "COGS ↔ inventory movement" (L2838); (f) "COGS Report =
COGS Ledger" (L2817). Future recon report shows operational value,
accounting value, difference, traceability, WH/product context.
Differences are EXPOSED for investigation — never silently journaled,
never hidden. Per-warehouse recon needs the ID-6-15 mapping (OPEN).

## 19. REPORTING (first-class; read-layer only)

Six views minimum + drill-down `Warehouse → Product → Stock →
Movements → Source Document → Customer/Supplier`: Warehouse Stock,
Product Kardex (opening/receipts/issues/returns/transfers/adjustments/
closing), Stock Movement, Customer Dispatch, Supplier Purchase Return,
Warehouse Detail. Must answer e.g. "How much 10L Sar Khord oil is in
Omar Rahimi warehouse? Which customers received it?" Reports query
canonical inventory/accounting/business truth — no second balance/
ledger/AVCO/accounting engine. Implication: movements + documents must
preserve the reference chains these views traverse.

## 20. EXPLICIT DECISIONS (format §25; F = finalization ruling applied)

```text
ID-6-01 | identity (P,W); no owner dimension; WH≠owner | F: CONFIRMED business rule | SETTLED.
ID-6-02 | stock derived from immutable movements; no balance table | F: CONFIRMED equation | SETTLED.
ID-6-03 | single StockMovement + 9-type family (§9 list) | F: CONFIRMED taxonomy | SETTLED.
ID-6-04 | SUPERSEDED: integer stock qty for discrete units; snapshot UOM+factor; V1 conversions must yield integer counts | F: user rule §11 | SETTLED (fractional = future decision).
ID-6-05 | snapshot factor+UOMs per movement; master edits never rewrite (G6) | SETTLED.
ID-6-06 | transfer mechanics CONFIRMED (§10); settlement-by-goods excluded (§28) | OPEN sub-q: GL legs — (a) qty-only vs (b) P&L-neutral reclass Dr-dest/Cr-source at AVCO; new evidence: §29 pairs transfer WITHOUT accounting (soft toward (a), not explicit). Recommend user rules explicitly.
ID-6-07 | opening shape CONFIRMED (§12) | OPEN: counter-account — 3900-reuse (only opening account in COA) vs separate account (COA change). Recommend 3900; user rules.
ID-6-08 | adjustment audited, V1 approval simplifiable | OPEN core: IN-cost {explicit input / AVCO-neutral / zero} + offset account {existing 6100? / new = COA decision}; shortage flavor kept distinct (§14). User rules.
ID-6-09 | AVCO literal + zero-reset + exact-then-round, no remainder | F: CONFIRMED (§15); avco() helper = single justified addition at implementation | SETTLED (discount-net minor note carried).
ID-6-10 | negative allowed w/ warning + ack + full audit context (product/WH/before/out/result/datetime/user/reason) | F: CONFIRMED (§20) | OPEN: "standard cost" source (L1042 undefined; ladder step-2 unimplementable as written) — options {ref_purchase_price proxy / 0 / reject-when-no-history}; reason form: free-text ("reason/description where applicable"). User rules source.
ID-6-11 | SUPERSEDED → SETTLED: true zero breaks the cycle; next receipt starts fresh (§19/§21). No carry, ever.
ID-6-12 | SUPERSEDED → SETTLED: original purchase/receipt cost basis + full traceability + no over-return (§9/§16).
ID-6-13 | sales return = original recorded basis; corrected-temp → historical record (§4.13) | SETTLED.
ID-6-14 | per-movement (ccy, unit cost, rate, AFN cost); AFN valuation; no restatement | F: CONFIRMED | SETTLED.
ID-6-15 | recon concept CONFIRMED (expose, never hide/balance) | OPEN core: per-warehouse recon + posting-leaf resolution need a warehouse↔account mapping living in Phase 6 (frozen Warehouse untouched) vs 1400-total recon only. User rules.
ID-6-16 | movements immutable; reverse-transfer/adjustment/COGS-adjustment correct; pre-post cancel = doc concern | F: CONFIRMED | SETTLED.
ID-6-17 | primitives atomic w/ related ops (receipt+acct, issue+COGS, In+Out, return+acct); ROLLBACK ALL | F: CONFIRMED | SETTLED.
ID-6-18 | reuse core idempotency; caller-owned keys; no second framework | F: CONFIRMED | SETTLED.
ID-6-19 | reuse record_audit_event; existing actions only (CREATE precedent); no-op convention kept | F: CONFIRMED | SETTLED.
ID-6-20 | boundaries: Purchase/Sales/Returns own docs, call receive()/issue()/transfer()/adjust()/open()/queries/cost lookups (§33) | F: CONFIRMED | SETTLED.
NEW-GAP | shortage day-market-rate source: no infrastructure exists | smallest proposal: user-entered rate at claim time; inventory leg (if any) at AVCO. User rules.
```

## 21. OUT-OF-SCOPE LIST

§36 list (models/migrations/services/APIs/UI/admin/purchase/sales/
payment/returns UI/cash/EH/remittance/settlement/printing/licensing/
production/landed-cost allocation engine/approval workflow/lot-batch-
serial/materialized balances/new accounting-currency-audit-idempotency-
numbering engines) + dimensions (batch/lot/serial/expiry/bin),
approval workflows (V1-simplified), freight capitalization (freight =
expense §5.4).

## 22. DISCOVERY CONCLUSION + IMPLEMENTATION GATE

V1 inventory = integer (P,W) stock derived from 9-type immutable
movements + AFN AVCO (4dp, zero-reset) + actual-cost receipts
(waste÷usable) + original-basis returns + controlled negatives +
atomic/audited primitives + read-layer reporting — with 6 rulings
outstanding (ID-6-06 GL legs, ID-6-07 counter-account, ID-6-08 cost+
offset, ID-6-10 standard-cost source, ID-6-15 mapping, shortage rate
source). GATE: no production implementation until the user reviews
this finalization and rules the OPEN items. Awaiting user review.
