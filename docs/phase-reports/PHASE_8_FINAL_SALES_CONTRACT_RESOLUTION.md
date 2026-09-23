# Phase 8 — Final Sales Contract Resolution Report

**Repository:** `Balkh/hesabdari_balkh`  
**Mode:** Contract lock discovery — no implementation  
**Report artifact:** Created for this discovery task only  
**Final status:** Contract resolved at the business/architecture boundary; accounting and baseline evidence decisions remain explicit gates.

---

## 1. Executive Summary

Phase 8 Sales does not yet have an implementation or an authoritative dedicated Sales contract in the repository. Phase 0–7 accounting, fiscal, Party, inventory, and Purchase foundations are protected.

The authoritative Sales contract established by the business is:

```text
Sales finalization
    → buyer ownership
    → receivable/payment state is separate
    → release authorization
    → physical release / issue
    → custody and fulfillment reconciliation
```

The following are separate concepts:

```text
Sale
Payment
Economic ownership
Physical location
Customer custody
Warehouse release authorization
Physical issue
Fulfillment
Purchase
Sales Return
```

The recommended architecture is:

```text
Existing physical inventory: Product + Warehouse
        +
Independent Sales ownership / entitlement / custody layer
        +
Warehouse Release Authorization and Release Lines
        +
Fulfillment Allocation for future Sales
```

The existing Phase 6 `StockMovement` identity must not be changed to `Product + Warehouse + Owner` during Phase 8 discovery or implementation planning.

Two accounting matters are not evidenced by the repository and must not be invented:

1. how customer-owned goods physically held in company warehouses are treated in company inventory valuation and financial reporting;
2. the exact revenue/COGS timing and the `4110` versus `4120` Sales selection rule.

Those are explicit implementation gates, not silent assumptions.

---

## 2. Repository Baseline

### 2.1 Current repository state

Inspection recorded:

```text
Branch: phase/4
HEAD:   692e2735234e2d123625bc2dc9a2f15be9c0e564
HEAD message: freeze phase 7 purchase workflow
```

The working tree was already dirty before this report:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_CUSTODY_DISCOVERY.md
?? docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_REPORT.md
```

The two tracked modifications and the earlier Phase 8 report artifacts were not overwritten or cleaned.

### 2.2 Current settings

The working tree contains `purchases` in `INSTALLED_APPS`:

```text
..., "inventory", "purchases",
```

The committed HEAD version of `backend/config/settings/base.py` does not contain that registration.

### 2.3 Remotes / GitHub

No usable Git remote URL is configured in the inspected repository. Independent GitHub `main` or approved Phase 7 verification was therefore not possible.

No GitHub verification is claimed.

### 2.4 Baseline suitability

The working tree is **not a clean Phase 8 implementation baseline** because:

- the Phase 7 Purchase registration differs between the working tree and HEAD;
- unrelated tracked documentation is modified;
- no usable remote is configured for independent baseline comparison.

The repository remains suitable for contract discovery, but not as an unqualified implementation baseline until PH8-008 and PH8-009 are resolved.

---

## 3. Phase 7 Baseline Integrity

### 3.1 Discrepancy

The discrepancy still exists:

```text
Working tree: purchases registered
HEAD:         purchases not registered
```

The working-tree diff is limited to adding `"purchases"` to the Django application list. The current evidence is consistent with an uncommitted Phase 7 integration correction, but the correction is not present in the Phase 7 freeze commit.

### 3.2 Consequence

The freeze commit cannot be treated as the same runtime baseline as the current working tree without an explicit decision. Whether the committed snapshot is runnable as a Purchase-integrated baseline was not independently established in this task.

### 3.3 Classification

```text
PH8-008: HIGH — Phase 7 baseline integrity decision required
PH8-009: EVIDENCE DEBT — GitHub baseline unavailable
```

No fix was applied.

---

## 4. Protected Phase 0–7 Systems

The following remain protected:

- domain and accounting contracts;
- `JournalEntry`, `JournalLine`, `post_journal()`, and reversal/immutability rules;
- money precision, currency, rate, and rate-date behavior;
- fiscal-period posting gates;
- Party and Party roles;
- PartyLedgerAttribution and receivable/payable derivation;
- Product and Warehouse;
- `StockMovement`;
- Product + Warehouse physical stock identity;
- `receive_stock()` and `issue_stock()`;
- AVCO and inventory cost history;
- inventory idempotency and concurrency protection;
- Purchase and PurchaseLine;
- Purchase posting and receipt;
- Purchase posted immutability;
- existing return primitives;
- audit conventions.

No Phase 6 system is to be rewritten to make Sales ownership fit.

---

## 5. Existing Sales/Accounting/Inventory Contracts

### 5.1 Sales

The Sales application is currently a placeholder (`backend/sales/.gitkeep`). There is no Sales Invoice, SalesLine, Sales posting workflow, Warehouse Release document, custody domain, fulfillment allocation, Sales API, or Sales UI.

### 5.2 Payment and Returns

`backend/payments/` and `backend/returns/` are placeholders. Payment and integrated Sales Return workflows are not implemented.

The existence of an `inventory` Sales Return primitive does not establish the full financial or ownership contract for Sales Return.

### 5.3 Accounting

The repository provides the canonical posting path and account masters. Relevant accounts are:

| Code | Existing meaning | Evidence classification |
|---|---|---|
| `1310` | Trade Receivables | Existing COA contract |
| `4110` | Wholesale Sales | Existing COA contract and generic posting/test usage |
| `4120` | Retail Sales | Existing COA contract and targeted posting/test usage |
| `4200` | Sales Returns | Existing COA contract |
| `5100` | COGS | Existing COA contract |

The repository demonstrates that `4110` is used by generic revenue and FX-related posting tests, and that `4120` is a valid posting account. It does not establish the Sales business rule that selects one for a particular invoice.

### 5.4 Inventory

Inventory represents physical events using:

```text
Product + Warehouse
```

`StockMovement` supports movement types including `SALES_ISSUE` and `SALES_RETURN`; `receive_stock()` and `issue_stock()` are existing physical inventory primitives. The inventory foundation does not model customer economic ownership, customer custody, unreleased Sales, or future Sales obligations.

### 5.5 Purchase

Purchase follows the protected pattern:

```text
Purchase
  → PurchaseLine
  → journal posting / payable
  → Party Ledger attribution
  → receive_stock()
  → physical inventory and AVCO
```

This is the required entry path for goods obtained later to fulfill a future Sale.

---

## 6. Confirmed Business Rules

The following are authoritative user requirements, not inferred implementation rules:

1. Finalizing a Sales Invoice transfers ownership to the buyer.
2. Cash, credit, partial-payment, and no-payment Sales all follow that ownership rule.
3. Payment is not an ownership trigger.
4. Customer-owned goods may remain in company physical custody with no required collection deadline.
5. A Warehouse is a physical location, not an owner boundary.
6. Multiple customer owners and company-owned stock may coexist in one Warehouse.
7. Warehouse belongs to SalesLine, not only to the Sales header.
8. One invoice may contain lines from multiple Warehouses.
9. Sale and physical Warehouse Release are separate events.
10. Partial Release and release history are mandatory.
11. A Sale may be finalized when physical stock is zero.
12. Such a Sale creates a commercial fulfillment obligation, not fake inventory.
13. Later goods must first pass through Purchase and `receive_stock()` before fulfillment.
14. Customer → Company is a new Purchase, not a generic Sales Return.
15. Printing is operational and non-financial; printing twice must not release twice.

---

## 7. Normal Sales Contract

The normal contract is:

```text
DRAFT
  ↓
FINALIZED / POSTED
  ↓
Buyer ownership established
  ↓
Receivable or payment state
  ↓
Warehouse Release Authorization
  ↓
Physical Release / Issue
```

A finalized Sale may have zero, partial, or complete release:

```text
Released = 0
Released < Sold
Released = Sold
```

Finalization freezes commercial facts. The later Release process records operational fulfillment and must not rewrite the finalized SalesLine.

A normal Sale must not require a fixed custody expiry date.

---

## 8. Ownership Contract

### 8.1 Trigger

Ownership transfers at Sales finalization.

```text
Ownership ≠ Payment
Ownership ≠ Physical Release
Ownership ≠ Physical Location
```

### 8.2 Immutability

After finalization, these commercial facts must be immutable under the existing posted-history principle:

- customer;
- Product;
- SalesLine Warehouse;
- quantity;
- unit;
- price;
- discount;
- currency;
- exchange rate and rate date;
- totals;
- ownership entitlement basis.

Any cancellation, reversal, correction, or return must be a controlled future contract, not an edit to posted history.

### 8.3 Accounting qualification

The ownership rule is resolved as a business rule. The repository does not establish whether the associated accounting treatment is:

- an immediate company-inventory reduction;
- a custody reclassification;
- an entitlement-only reporting treatment;
- another approved treatment.

No journal entry is selected here.

---

## 9. Customer Custody Contract

Customer custody means:

```text
Customer owns the goods
Company physically holds the goods
Release date is unknown or later
```

For available goods:

```text
Sold:       2,000
Released:     200
Custody:    1,800
```

After another 300 release:

```text
Sold:       2,000
Released:     500 cumulative
Custody:    1,500
```

Custody must be represented independently from physical StockMovement. A custody record must be traceable to the SalesLine and retain Product, customer owner, Warehouse custody location, and quantity history conceptually.

Custody is open-ended. No artificial expiry date is permitted by this contract.

The physical Warehouse report and customer-ownership/custody report are different information products.

---

## 10. Multi-Warehouse Sales

The minimum Sales structure must support:

```text
Sales Invoice S-001
  ├── SalesLine 1 → Product A → Warehouse A
  ├── SalesLine 2 → Product B → Warehouse B
  └── SalesLine 3 → Product C → Warehouse C
```

The Sales header may identify the customer and commercial context, but it must not be the only source of Warehouse selection.

Every release and fulfillment event must retain the originating SalesLine so that a multi-Warehouse invoice cannot lose line-level identity.

---

## 11. Warehouse Release Contract

### 11.1 Purpose

A finalized Sale containing releasable goods must be capable of producing an authoritative Warehouse instruction. Warehouse staff must not infer release facts from a journal entry.

The instruction must identify:

```text
Customer
Sales Invoice
SalesLine
Product
Warehouse
Quantity
Unit
Release status
```

### 11.2 Recommended document boundary

The minimal recommended conceptual boundary is:

```text
Sales Invoice
  → Warehouse Release Authorization
      → Warehouse Release Lines
```

A parent authorization preserves the invoice-level operation. Release Lines preserve SalesLine, Product, Warehouse, and quantity identity. Operational print views may group those lines by Warehouse.

### 11.3 Integrity rules

The future implementation must reject:

- release greater than sold;
- release greater than authorized;
- release greater than fulfilled/available under the approved fulfillment rule;
- wrong Product;
- wrong Warehouse;
- wrong SalesLine;
- duplicate release;
- release against an invalidated/reversed Sale;
- release after finalization facts have been altered.

Authorization is not physical release. It does not itself prove that goods left the Warehouse.

---

## 12. Partial Release Contract

Every physical release is an event in a traceable history:

```text
SalesLine
  ├── Release #1
  ├── Release #2
  └── Release #3
```

The cumulative Released Quantity is derived from valid release events, not from overwriting a single unexplained counter.

For ordinary available goods:

```text
Customer Custody Quantity = Sold Quantity − cumulative Released Quantity
```

This relationship applies only to quantity already obtained/allocated and physically held by the company. It does not turn a future Sale with zero stock into physical custody.

---

## 13. Future Sales Contract

A Sale may be finalized even when stock is unavailable:

```text
Sold / Contracted:     5,000
Physical Available:        0
Released:                  0
Customer Custody:          0
Remaining Fulfillment: 5,000
```

The Sale records the commercial obligation. It must not create StockMovement or claim that physical inventory exists.

Ownership still follows the authoritative finalization rule; physical possession/custody does not exist until goods are actually obtained and held.

---

## 14. Fulfillment Contract

Future fulfillment is a distinct chain:

```text
Purchase
  → PurchaseLine
  → receive_stock()
  → company physical inventory with actual cost
  → Sales fulfillment allocation
  → custody and/or physical release
```

The future contract must distinguish:

- Purchase receipt;
- physical inventory availability;
- allocation to a SalesLine;
- customer custody;
- physical release.

It must prevent:

- fulfilled quantity greater than sold;
- allocated quantity greater than sold;
- released quantity greater than fulfilled/available quantity under the approved rule;
- duplicate allocation of the same Purchase quantity;
- fabricated inventory;
- reusing one inventory quantity for multiple Sales obligations.

The exact accounting bridge for allocation after Purchase is unresolved and cannot be invented.

---

## 15. Customer-to-Company Purchase Boundary

The following is a new Purchase:

```text
Customer → Company
```

It must use the Purchase contract, including receipt, cost determination, inventory history, and payable treatment as applicable.

It is not a Sales Return merely because the Product was previously sold by the company.

Sales Return is reserved for a later contract that explicitly reverses or returns an original Sales transaction and can identify the original Sales, SalesLine, release history, custody, payment state, ownership, and original inventory cost.

---

## 16. Payment Boundary

Payment remains separate:

```text
Sales
  → receivable / commercial obligation
  → later Payment
```

Payment may be cash, credit, partial, unpaid, or later settled. Payment does not establish or revoke ownership.

The initial Sales contract must reuse the existing receivable, Party Ledger, money, currency, fiscal, posting, and idempotency foundations. It must not create a Payment Engine inside Sales.

Payment allocation, advances, overpayments, settlement FX, and exchange-house settlement belong to the later Payment/Settlement boundary.

---

## 17. Accounting Boundary

| Event | Inventory effect | Ownership effect | Receivable effect | Revenue effect | COGS effect |
|---|---|---|---|---|---|
| Sales finalization | Must not fabricate stock. Exact inventory valuation treatment is unresolved. | Buyer ownership established. | Credit Sale may create receivable using existing Party Ledger boundary. | Timing not established for the separated release case. | Timing not established. |
| Payment | None directly. | None; payment is not ownership. | Reduces/settles receivable under Payment contract. | None. | None. |
| Release Authorization | None; authorization is operational. | None; ownership already transferred. | None. | None. | None. |
| Physical Release / Issue | Physical inventory event only when approved and physically performed; reuse `issue_stock()`. | Release does not independently transfer ownership. | None directly. | None directly. | May connect to COGS under approved timing. |
| Customer Custody | Goods remain physically located in company Warehouse, but ownership is customer’s. | Customer remains owner. | None. | None. | Inventory valuation/reporting treatment unresolved. |
| Future Purchase/Receipt | Actual goods enter company inventory at actual cost through Purchase. | No invented customer stock. | Purchase payable as applicable. | None. | Cost governed by Purchase/AVCO. |
| Fulfillment Allocation | Allocates existing physical availability; must not fabricate stock. | Connects existing Sale entitlement to obtained goods. | None directly. | None directly. | Allocation/COGS treatment unresolved. |
| Customer-to-Company Purchase | Normal Purchase receipt and inventory effect. | Company ownership under Purchase. | Supplier payable as applicable. | None. | Purchase/AVCO. |
| Sales Return | Existing return primitives may reverse physical issue; integrated scope unresolved. | Requires original ownership/custody contract. | Depends on payment state. | `4200` exists, but timing and use require Sales Return contract. | Original-cost/COGS reversal requires contract. |

No journal entry is authorized by this table where the repository contract is silent.

---

## 18. Revenue / COGS Timing

### 18.1 Revenue accounts

`4110 Wholesale Sales` and `4120 Retail Sales` are both existing posting accounts. Existing tests prove that both can be posted to; they do not prove a Sales document selection rule.

Minimum required decision before financial Sales implementation:

```text
Which business attribute selects 4110 versus 4120?
```

A possible proposal is:

```text
WHOLESALE → 4110
RETAIL    → 4120
```

but this remains a proposal until the business approves that the Sale Type is authoritative.

### 18.2 Timing

The repository does not establish whether revenue and COGS occur at:

- Sales finalization;
- Release Authorization;
- physical issue;
- future fulfillment;
- another controlled event.

Because ownership transfers at finalization while release may be delayed, timing is an explicit accounting decision. It must not be derived from payment or chosen merely because `issue_stock()` exists.

---

## 19. Quantity Model

The contract distinguishes five quantities:

| Quantity | Meaning | Conceptual authority |
|---|---|---|
| Sold / Contracted | Finalized SalesLine quantity | SalesLine; immutable after finalization |
| Physical Available | Actual Product + Warehouse physical availability | StockMovement/AVCO-derived inventory |
| Released | Quantity physically handed over | Release event history; cumulative derived value |
| Customer Custody | Customer-owned quantity still physically held by company | Ownership/custody event layer |
| Remaining Fulfillment | Sold quantity not yet obtained/allocated/fulfilled | Fulfillment allocation derivation |

### Storage and derivation rules

- Sold is a finalized SalesLine fact.
- Physical Available is inventory-derived, not Sales-derived.
- Released is event-based and cumulative.
- Customer Custody is derived from ownership/fulfillment/release events according to the approved custody bridge.
- Remaining Fulfillment is derived from Sold minus valid fulfillment allocation.
- No single mutable quantity may stand for all five meanings.

For available goods:

```text
Sold = 2,000
Released = 200
Customer Custody = 1,800
```

For future goods:

```text
Sold = 5,000
Released = 0
Customer Custody = 0
Remaining Fulfillment = 5,000
```

---

## 20. Printing Contract

Printing is operational only:

```text
Sales Invoice
  → Warehouse Release Authorization
      → Warehouse-specific printable document(s)
```

A multi-Warehouse invoice may produce multiple Warehouse sheets. Each sheet must show at least:

```text
Customer
Invoice
SalesLine
Warehouse
Product
Quantity
Unit
Release status
```

The recommended form is one parent authorization with Warehouse-grouped Release Lines. A line remains independently identifiable and may be independently rendered/printed without duplicating the business event.

Printing is:

```text
Non-financial
Non-inventory
Idempotent
```

Printing twice does not authorize twice and does not release twice.

---

## 21. Sales Return Boundary

Existing inventory Sales Return capability is not sufficient evidence for a complete financial Sales Return contract.

A future integrated Sales Return must know, at minimum:

- original Sales;
- original SalesLine;
- released quantity;
- unreleased quantity;
- customer custody quantity;
- payment state;
- ownership state;
- original inventory cost;
- whether the event is a true return or a new Purchase.

Sales Return implementation is deferred until these relationships and the accounting treatment are approved.

---

## 22. Architecture Comparison

| Option | Phase 6 compatibility | AVCO / Purchase impact | Multi-owner support | Future fulfillment | Complexity / risk | Assessment |
|---|---|---|---|---|---|---|
| A. Product + Warehouse + Owner in StockMovement | Low; changes protected identity | High; changes AVCO, Purchase, transfers, adjustments, returns, and concurrency | Direct | Possible but invasive | Very high migration and compatibility risk | Not recommended for Phase 8 |
| B. Independent ownership/custody layer | High; physical identity unchanged | Low-to-moderate bridge/reconciliation work | Strong | Strong | Moderate; accounting bridge required | Recommended foundation |
| C. Sales entitlement/release layer over physical Inventory | High | Low; reuses `receive_stock()`/`issue_stock()` | Strong through SalesLine entitlement | Strong | Lowest footprint if custody is included explicitly | Recommended operational shape |
| D. Separate customer-custody inventory subsystem | Medium; risk of duplicate inventory logic | High risk of duplicate quantity/valuation logic | Strong | Strong | High; reconciliation and duplicate-engine risk | Not recommended as a second inventory engine |

---

## 23. Recommended Architecture

The recommended architecture is a combination of B and C:

```text
Physical Inventory
  = existing Product + Warehouse StockMovement / AVCO

Sales Commercial Layer
  = Sales + SalesLine, with Warehouse on every line

Ownership / Entitlement / Custody Layer
  = customer ownership, custody location, quantities, and history

Release Layer
  = Warehouse Release Authorization + Release Lines

Fulfillment Layer
  = allocation from actual Purchase/Inventory sources to SalesLines
```

### Explicit non-goals

- no Owner field in StockMovement;
- no second inventory engine;
- no second AVCO;
- no Payment Engine inside Sales;
- no duplicate Party, Ledger, Money, Currency, Audit, or Idempotency framework;
- no invented custody account;
- no fabricated future inventory.

### Why this is the smallest safe direction

It preserves Phase 6 while supporting:

- ownership independent of payment;
- multiple owners in one Warehouse;
- line-level multi-Warehouse invoices;
- open-ended custody;
- release history;
- future Sales with zero stock;
- later Purchase-fed fulfillment;
- customer-to-company Purchase as a distinct event.

The accounting bridge remains a gate before financial implementation.

---

## 24. Normal vs Rare Scenarios

### Normal cash

```text
Sale → ownership → cash/payment state → release → physical issue
```

### Normal credit

```text
Sale → ownership → receivable → release → later payment
```

### Customer custody

```text
Sale → ownership → goods remain in company Warehouse → later release
```

### Partial release

```text
2,000 sold → 200 released → 1,800 custody
          → 300 later released → 1,500 custody
```

### Future Sale

```text
5,000 sold → stock unavailable → fulfillment obligation
           → later Purchase → receipt → allocation → release
```

### Customer sells to company

```text
Customer → new Purchase → receive_stock() → company inventory
```

It is not Sales Return.

---

## 25. Adversarial Scenario Matrix

| # | Scenario | Expected business state | Inventory state | Ownership | Custody | Release | Fulfillment | Accounting state |
|---:|---|---|---|---|---|---|---|---|
| 1 | Cash sale | Finalized Sale | Existing physical stock only | Buyer | Zero or remaining | Immediate/authorized | Available | Revenue/COGS timing requires approved rule |
| 2 | Credit sale | Finalized Sale + receivable | No fake change from credit | Buyer | Based on physical holding | May be zero/partial/full | Available if sourced | Receivable supported; timing unresolved |
| 3 | Zero-payment finalized | Finalized Sale | No payment-driven inventory event | Buyer | Based on physical holding | Independent | Available or obligation | Payment does not determine accounting ownership; timing unresolved |
| 4 | Partial payment | Sale finalized, balance remains | Physical inventory independent | Buyer | Based on release | Independent | Independent | Payment allocation later |
| 5 | 2,000 / 200 release | Finalized Sale | Physical issue only if actually released | Buyer | 1,800 | One release event | At least 200 fulfilled | COGS timing unresolved |
| 6 | 2,000 / 200 + 300 | Two release events preserved | Two physical issue events if performed | Buyer | 1,500 | Cumulative 500 | At least 500 fulfilled | COGS timing unresolved |
| 7 | Unknown custody duration | Customer-owned custody open-ended | Physical goods remain location-based | Buyer | Custody remains until release | No expiry assumption | Obtained/held | Custody valuation/reporting unresolved |
| 8 | Multiple customers in one Warehouse | Separate entitlements | Physical stock remains Product + Warehouse | Each customer by entitlement | Separately attributable | Independent | Independent | Company-vs-custody accounting unresolved |
| 9 | Multiple Warehouses in invoice | One Sale, many SalesLines | Per-line Product + Warehouse | Buyer | Per-line custody | Grouped by Warehouse | Per-line | Revenue selection unresolved |
| 10 | Future Sale, stock zero | Commercial obligation | No StockMovement fabricated | Buyer under Sale contract | Zero | Zero | 5,000 remaining | Revenue/COGS/obligation timing unresolved |
| 11 | Future Sale then Purchase | Obligation later supplied | Purchase receipt enters inventory | Buyer entitlement exists | After allocation/holding | Later release | Allocation increases fulfillment | Purchase accounting known; allocation bridge unresolved |
| 12 | Same Purchase allocated twice | Second allocation rejected | One physical quantity only | No duplicate entitlement | No duplicate custody | No duplicate release | Allocation idempotency required | No duplicate posting |
| 13 | Release above sold | Rejected | No extra issue | Unchanged | Unchanged | Rejected | Unchanged | No posting |
| 14 | Wrong Warehouse release | Rejected | No issue from wrong Warehouse | Unchanged | Unchanged | Rejected | Unchanged | No posting |
| 15 | Wrong Product release | Rejected | No wrong Product issue | Unchanged | Unchanged | Rejected | Unchanged | No posting |
| 16 | Duplicate release request | Same idempotent result or rejection | One physical event | Unchanged | Unchanged | No duplicate | Unchanged | No duplicate journal |
| 17 | Finalized line edited after release | Edit rejected | Existing history preserved | Existing owner | Existing custody | Existing history | Existing allocation | Posted history protected |
| 18 | Customer sells to company | New Purchase | Purchase receipt path | Company under Purchase | Not Sales custody | No Sales release | Not Sales fulfillment | Payable/Purchase contract |
| 19 | Actual Sales Return | Return references original Sale/Line | Existing return primitive subject to integration | Reversal/return rule required | Custody rule required | Return quantity bounded | Original cost required | `4200`/COGS/payment treatment unresolved |
| 20 | Print twice | Same operational document | No inventory change | No ownership change | No custody change | No new release | No change | No accounting |
| 21 | Partial release then another | New release event | New physical issue if performed | Same buyer | Reduced custody | History preserved | Increased fulfillment | Timing unresolved |
| 22 | Unavailable quantity becomes available | Existing future obligation | Actual receipt only | Existing entitlement | Allocation-dependent | Release still authorized separately | Fulfillment increases | Allocation accounting unresolved |
| 23 | Sale cancelled/reversed before release | Controlled future cancellation/reversal | No unauthorized issue | Controlled reversal rule required | No release | Release blocked | Obligation treatment required | Reversal journal rule required |
| 24 | Mixed Warehouse lines | One invoice, line-level operations | Per-line inventory | Same buyer | Per-line custody | Warehouse-grouped | Per-line | Account rule unresolved |
| 25 | Customer owns stored goods | Ownership and physical location differ | Physical stock report separate | Customer | Company custody | Release later | Fulfilled if obtained | Custody valuation/reporting unresolved |

---

## 26. Decision Matrix

| ID | Decision | User Rule | Repository Evidence | Status | Contract Consequence | Implementation Gate |
|---|---|---|---|---|---|---|
| PH8-001 | Ownership transfer | Finalized Sale transfers ownership | User directive; no Sales implementation | RESOLVED | Ownership at finalization | Must be encoded; no payment trigger |
| PH8-002 | Customer custody | Customer-owned goods may remain in company Warehouse indefinitely | No existing custody domain | RESOLVED BUSINESS / ACCOUNTING OPEN | Independent custody history | Custody accounting approval required |
| PH8-003 | Sale vs release | Separate events | Inventory has issue primitive; no Sales release model | RESOLVED | Release layer required | Authorization and issue boundaries |
| PH8-004 | Payment boundary | Payment separate; ownership independent | Payments placeholder; Party Ledger exists | RESOLVED | Later Payment domain | No hidden Payment Engine |
| PH8-005 | Revenue account | Do not invent `4110`/`4120` rule | Both accounts exist; no Sales selector | UNRESOLVED | Must select by approved business attribute | Financial posting blocked |
| PH8-006 | Partial release | Release history required | `SALES_ISSUE` primitive exists | RESOLVED | Event-based release quantities | Idempotency and bounds required |
| PH8-007 | Sales Return | Must distinguish true return from Purchase | Inventory return primitives exist; Sales absent | UNRESOLVED | Later integrated Return contract | Defer implementation |
| PH8-008 | Phase 7 baseline | Freeze must be reproducible | Working tree registers purchases; HEAD does not | BLOCKED | Baseline qualification required | Do not implement on ambiguous baseline |
| PH8-009 | GitHub baseline | Verify official state if possible | No usable remote configured | BLOCKED EVIDENCE | External baseline unavailable | Provide remote/authority |
| PH8-010 | Company inventory vs custody | Customer custody is not company-owned goods | No custody accounting contract | UNRESOLVED | Separate reports and accounting decision | Financial implementation blocked |
| PH8-011 | Payment vs ownership | Payment never triggers ownership | User directive | RESOLVED | Payment state independent | Must test unpaid/partial cases |
| PH8-012 | Release vs ownership | Release does not trigger ownership | User directive | RESOLVED | Ownership exists before release | No release-based ownership rule |
| PH8-013 | Warehouse at SalesLine | Warehouse belongs on each line | Product/Warehouse inventory primitives | RESOLVED | Line-level Warehouse mandatory | Header-only Warehouse forbidden |
| PH8-014 | Multi-Warehouse invoice | One invoice may span Warehouses | No Sales model yet | RESOLVED | Group release operationally, retain line trace | Required from foundation |
| PH8-015 | Release authorization | Warehouse needs authoritative instruction | No existing document | PROPOSED / USER APPROVAL | Parent authorization plus ReleaseLines | Approve before implementation |
| PH8-016 | Printing | Warehouse-specific sheets; printing non-financial | No printing implementation | PROPOSED / USER APPROVAL | Print projection, not event | Approve document boundary |
| PH8-017 | Future Sales | Sale allowed with zero physical stock | Inventory cannot represent fake stock | RESOLVED | Sales obligation separate from inventory | No StockMovement on Sale alone |
| PH8-018 | Future fulfillment | Purchase/receipt precedes fulfillment | Purchase and `receive_stock()` exist | RESOLVED | Allocation from actual inventory | Allocation contract required |
| PH8-019 | Customer-to-company Purchase | New Purchase, not Return | Purchase and return primitives separate | RESOLVED | Use Purchase boundary | No Return shortcut |
| PH8-020 | Fulfillment allocation | No double allocation or fabrication | No allocation model exists | UNRESOLVED | Need source-to-SalesLine allocation rules | Required before future fulfillment |
| PH8-021 | Architecture | Preserve Product + Warehouse identity | Phase 6 contract | RESOLVED RECOMMENDATION | Independent custody/entitlement layer | User approval required |
| PH8-022 | Sales lifecycle | Draft then finalization; separate operational states | Purchase/posting immutability precedent | PROPOSED | DRAFT → FINALIZED/POSTED | Approve cancellation/reversal policy |
| PH8-023 | Immutability | Finalized facts cannot be edited | Existing posted immutability | RESOLVED PRINCIPLE | Protect line, Warehouse, quantity, price | Reuse core conventions |
| PH8-024 | Idempotency | Business events need duplicate protection | Existing journal/inventory idempotency | PROPOSED | Separate finalization, release, allocation keys | Define event keys |
| PH8-025 | Custody accounting | Do not invent treatment | No existing contract found | BLOCKING UNRESOLVED | Define valuation/reporting/journal boundary | Accounting approval required |
| PH8-026 | Revenue/COGS timing | Must be explicitly resolved | Existing accounts/primitives do not decide event timing | BLOCKING UNRESOLVED | Define finalization/release/issue/fulfillment timing | Accounting approval required |
| PH8-027 | Currency/totals | Reuse existing money/FX conventions | Accounting `post_journal()` and currency contracts exist | PROPOSED | No duplicate money engine | Inspect exact Sales fields before implementation |
| PH8-028 | Cancellation/reversal | Must not release invalidated Sale | Existing reversal/immutability principles | UNRESOLVED | Controlled lifecycle contract required | Define before release implementation |

---

## 27. Dependency-Safe Stage Plan

### Phase 8 — Sales and release foundation

#### 8.1 Sales Commercial Foundation

Scope:

- Sales and SalesLine commercial contract;
- customer, currency, rate, Product, and line-level Warehouse;
- quantities, prices, discounts, totals, and immutable finalization;
- reuse existing Money, Party, fiscal, audit, and idempotency foundations.

Prerequisites:

- PH8-008 baseline qualification;
- PH8-022 lifecycle approval;
- PH8-023 immutability confirmation;
- PH8-027 exact money/totals contract.

Out of scope:

- Payment Engine;
- custody accounting;
- physical issue;
- Sales Return.

#### 8.2 Ownership / Entitlement / Custody

Scope:

- buyer ownership at finalization;
- customer custody and Warehouse location;
- open-ended custody;
- multi-owner reporting semantics;
- ownership/release history.

Prerequisites:

- PH8-002;
- PH8-010;
- PH8-021;
- PH8-025.

#### 8.3 Financial Sales Posting

Scope:

- receivable/commercial posting;
- approved revenue account selection;
- approved revenue and COGS timing;
- Party Ledger attribution and immutable journal source.

Prerequisites:

- PH8-005;
- PH8-025;
- PH8-026.

#### 8.4 Warehouse Release Authorization

Scope:

- parent authorization;
- Warehouse-grouped ReleaseLines;
- quantity bounds;
- duplicate protection;
- operational print projection.

Prerequisites:

- PH8-003;
- PH8-006;
- PH8-015;
- PH8-016.

#### 8.5 Physical Release / Issue

Scope:

- physical warehouse event;
- approved `issue_stock()` integration;
- release history and reconciliation;
- COGS only under approved accounting timing.

Prerequisites:

- valid fulfillment/availability rule;
- PH8-020;
- PH8-026;
- PostgreSQL/concurrency qualification where applicable.

### Phase 9 — Payment / Settlement

Scope:

- customer payment;
- allocation to receivable;
- partial payment, advances, overpayment;
- cash/exchange-house settlement;
- realized FX.

Payment must remain independent of ownership.

### Phase 10 — Returns

Scope:

- true Sales Return;
- original Sales/Line reference;
- custody/release/ownership reversal;
- original cost and COGS treatment;
- customer credit/refund boundary.

A customer-to-company Purchase is not part of this Return scope.

### Later / dependent work

- future fulfillment allocation from Purchase receipts;
- customer custody and ownership reporting;
- Warehouse printing/reporting;
- delivery workflows;
- advanced reconciliation.

Future fulfillment may be staged with Phase 8 only after the allocation and accounting contracts are approved; it must not be silently assumed to be part of normal Sales.

---

## 28. Remaining Blocking Decisions

The following prevent an implementation-ready financial contract:

1. select the authoritative `4110` versus `4120` rule;
2. define revenue recognition timing;
3. define COGS and inventory reduction timing when ownership and physical release differ;
4. define financial inventory valuation/reporting for customer-owned custody;
5. approve the custody/entitlement representation and reconciliation authority;
6. define fulfillment allocation semantics and cost/source locking;
7. approve the Warehouse Release Authorization and printing boundary;
8. define controlled Sales cancellation/reversal rules;
9. qualify the Phase 7 baseline discrepancy;
10. provide or verify the authoritative GitHub baseline.

These are not implementation details. They are contract decisions.

---

## 29. Evidence

### Repository evidence

```text
Branch: phase/4
HEAD: 692e2735234e2d123625bc2dc9a2f15be9c0e564
Phase 7 freeze: 692e273 — freeze phase 7 purchase workflow
Remote: no usable configured remote URL
```

### Relevant evidence paths

```text
backend/config/settings/base.py
backend/sales/.gitkeep
backend/payments/.gitkeep
backend/returns/.gitkeep
backend/accounting/coa.py
backend/accounting/services.py
backend/accounting/fx.py
backend/inventory/models.py
backend/inventory/services.py
backend/inventory/inventory_tests.py
backend/purchases/
docs/phase-0/PHASE_0_CONTRACT_V2.1.md
docs/phase-0/PHASE_2_PLAN.md
docs/phase-reports/PHASE_6_INVENTORY_ARCHITECTURE_DISCOVERY.md
docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md through PHASE_7_STAGE_7.7_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_FIX_POSTED_PURCHASE_BULK_IMMUTABILITY_EVIDENCE.md
```

### Test evidence

The previously established non-mutating SQLite baseline was:

```text
723 passed, 2 skipped in 77.50s
```

The skipped tests were PostgreSQL-specific concurrency tests.

```text
POSTGRESQL VERIFICATION: BLOCKED
Reason: PostgreSQL was unavailable at 127.0.0.1:5432.
```

No Phase 8 tests were added or modified. No PostgreSQL verification is claimed.

---

## 30. Implementation Gate

```text
IMPLEMENTATION PERFORMED: NO
CODE MODIFIED: NO
TESTS MODIFIED: NO
MIGRATIONS CREATED: NO
ACCOUNTING MODIFIED: NO
INVENTORY MODIFIED: NO
PURCHASE MODIFIED: NO
SETTINGS MODIFIED: NO
DEPENDENCIES MODIFIED: NO
COMMIT CREATED: NO
PUSH PERFORMED: NO
```

The only artifact produced for this task is this contract-resolution report. Existing dirty tracked files and earlier untracked discovery reports were not cleaned, repaired, or overwritten.

---

## 31. Final Recommendation

Approve the following as the Phase 8 architectural contract direction:

```text
Sales finalization establishes buyer ownership.
Payment remains separate.
Warehouse belongs to SalesLine.
Sale is separate from Release and Physical Issue.
Release history is event-based and traceable.
Customer custody is independent from Product + Warehouse physical inventory.
Future Sales create obligations, not fake stock.
Future goods first enter company inventory through Purchase/receive_stock().
Customer → Company is Purchase, not Sales Return.
```

Preserve the frozen Phase 6 physical identity:

```text
Product + Warehouse
```

Use a minimal independent ownership/entitlement/custody layer plus a Warehouse Release Authorization layer. Do not implement financial Sales until the revenue account, revenue/COGS timing, custody accounting, and Phase 7 baseline decisions are approved.

---

## 32. STOP

```text
IMPLEMENTATION PERFORMED: NO
CODE MODIFIED: NO
TESTS MODIFIED: NO
MIGRATIONS CREATED: NO
ACCOUNTING MODIFIED: NO
INVENTORY MODIFIED: NO
PURCHASE MODIFIED: NO
SETTINGS MODIFIED: NO
DEPENDENCIES MODIFIED: NO
COMMIT CREATED: NO
PUSH PERFORMED: NO
```

```text
STATUS:
PHASE 8 CONTRACT RESOLUTION COMPLETE
IMPLEMENTATION NOT PERFORMED
WAITING FOR USER REVIEW AND APPROVAL
```
