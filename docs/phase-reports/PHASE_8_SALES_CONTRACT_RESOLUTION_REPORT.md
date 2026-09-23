# Phase 8 — Sales Contract Resolution Report

**Mode:** Discovery + Contract Resolution Only  
**Implementation:** Not performed  
**Status:** Contract discovery complete — user decisions still required  
**Branch:** `phase/4`  
**HEAD:** `692e2735234e2d123625bc2dc9a2f15be9c0e564`  
**Phase 7 freeze:** `692e273 — freeze phase 7`

---

## 1. Executive Summary

Phase 8 is the next roadmap capability after the frozen Purchase workflow. The repository identifies Phase 8 as Sales, but it does not contain a Sales Invoice domain or a detailed Sales implementation contract.

The business requirements now establish several authoritative rules:

- ownership is associated with finalized Sales, not payment;
- payment status does not determine ownership;
- goods may remain physically in the company warehouse after ownership transfers to the customer;
- warehouse location is not ownership;
- one Sales Invoice may contain lines from multiple warehouses;
- Sales and physical Warehouse Release are separate concepts;
- partial release is required;
- a customer-to-company transaction is a new Purchase, not a Sales Return;
- goods unavailable at the time of sale may be sold as a future fulfillment obligation;
- later obtained goods must first enter company inventory through the existing Purchase/receipt process before fulfillment.

The current Product + Warehouse StockMovement identity must remain protected. The recommended contract direction is therefore:

```text
Sales
  → ownership / entitlement
  → warehouse release authorization
  → physical release / issue
  → custody and fulfillment reporting
```

with physical inventory continuing to use the existing Product + Warehouse foundation.

The accounting bridge for customer-owned goods remaining physically in company warehouses is not fully defined by the existing repository contract and requires explicit accounting approval before implementation.

---

## 2. Repository Baseline

### Current state

```text
Branch: phase/4
HEAD:   692e2735234e2d123625bc2dc9a2f15be9c0e564
Freeze: 692e273 — freeze phase 7
```

The working tree is not clean:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
```

No production or test files were modified during this discovery.

### Phase 7 baseline issue

The current working tree contains the `purchases` application registration in `backend/config/settings/base.py`, but the committed Phase 7 freeze commit does not contain that registration.

Therefore:

```text
Committed Phase 7 snapshot ≠ current working-tree Phase 7 runtime configuration
```

This must be resolved or explicitly documented before using a clean Phase 7 checkout as the implementation baseline.

Classification:

```text
HIGH — Phase 7 baseline integrity issue
```

### GitHub status

Local remote-tracking references exist, but no usable remote URL was available through the current Git configuration. The GitHub branch containing the approved freeze could not be independently verified.

Classification:

```text
EVIDENCE DEBT
```

---

## 3. Protected Phase 0–7 Systems

The following systems are protected during Phase 8:

- Accounting Core and Chart of Accounts;
- `JournalEntry`, `JournalLine`, and `post_journal()`;
- money precision and currency helpers;
- fiscal-period enforcement;
- Party and customer/supplier roles;
- PartyLedgerAttribution and balance derivation;
- StockMovement;
- Product + Warehouse stock identity;
- `receive_stock()` and `issue_stock()`;
- AVCO;
- transfers, adjustments, waste, shortage, and returns;
- inventory idempotency and concurrency controls;
- Purchase and PurchaseLine;
- Purchase posting, payable, receipt, and posted immutability;
- existing audit and idempotency conventions.

No ownership dimension should be added to StockMovement as a shortcut for the Sales custody problem.

---

## 4. Existing Sales-Related Contracts

### Existing roadmap contract

The Phase 2 roadmap identifies:

```text
Phase 8 — Sales
Phase 9 — Payments
Phase 10 — Returns
Phase 11 — Cash and Exchange House
```

Conceptual Sales capabilities include:

- Sales Invoice;
- Inventory Issue;
- COGS;
- revenue;
- customer receivable;
- gross profit.

### Existing implementation

The repository does not contain:

- Sales model;
- SalesLine model;
- Sales service;
- Sales lifecycle;
- Sales posting service;
- Sales API;
- Sales UI;
- Sales-specific audit;
- Sales-specific idempotency;
- Sales-specific immutability;
- Delivery model;
- Warehouse Release model;
- Custody or ownership-entitlement model.

The current Sales directory contains only a placeholder:

```text
backend/sales/.gitkeep
```

### Existing related capabilities

The repository does contain:

- Party customer role;
- customer receivable and customer-credit ledger categories;
- `issue_stock()`;
- `SALES_ISSUE` StockMovement;
- AVCO;
- Sales Return inventory primitives;
- revenue, receivable, COGS, cash, exchange-house, and FX accounts;
- journal, audit, fiscal, and idempotency primitives.

These are reusable foundations, not a Sales implementation.

---

## 5. Existing Accounting Primitives

The canonical COA contains:

| Account | Meaning | Role |
|---|---|---|
| `1310` | Trade Receivables | Posting receivable account |
| `2200` | Customer Advances / Credits | Posting liability account |
| `4110` | Wholesale Sales | Posting revenue account |
| `4120` | Retail Sales | Posting revenue account |
| `4200` | Sales Returns | Posting contra-revenue account |
| `5100` | COGS | Posting expense account |
| `1110` | Cash in Hand | Posting cash account |
| `1210`, `1220` | Exchange Houses | Posting exchange-house accounts |
| `8100` | Foreign Exchange Gain | Posting FX account |
| `8200` | Foreign Exchange Loss | Posting FX account |

The existing accounting patterns conceptually support:

### Credit Sale

```text
Dr 1310 Trade Receivables
Cr 4110 Wholesale Sales or 4120 Retail Sales
```

### Cash Sale

```text
Dr Cash
Cr Sales Revenue
```

### COGS

```text
Dr 5100 COGS
Cr Inventory
```

The repository does not define:

- the operational selection rule for `4110` versus `4120`;
- whether revenue is posted at Sales finalization or release;
- how customer-owned custody affects company inventory accounting;
- how future fulfillment is represented in the ledger.

No account numbers should be invented.

---

## 6. Existing Inventory Primitives

The current inventory engine provides:

```text
receive_stock()
issue_stock()
StockMovement
stock_for()
avco_for()
Purchase Return
Sales Return
```

The current physical stock identity is:

```text
Product + Warehouse
```

StockMovement preserves:

- Product;
- Warehouse;
- signed quantity;
- movement type;
- movement date;
- currency;
- unit cost;
- historical rate;
- rate date;
- AFN unit cost;
- source party where applicable;
- reference;
- audit and idempotency context.

This model represents physical stock events. It does not represent:

- economic ownership;
- customer entitlement;
- custody quantity;
- unreleased sold quantity;
- future fulfillment obligation.

The existing `issue_stock()` primitive should be reused for physical issue only after the Sales/Release contract determines that a physical issue is actually occurring.

---

## 7. Existing Purchase / Return Primitives

Purchase is frozen as:

```text
Purchase
  → PurchaseLine
  → post_journal()
  → 2110 Trade Payables
  → PartyLedgerAttribution
  → receive_stock()
  → StockMovement / AVCO
```

Purchase Return is a separate immutable inventory event based on the original Purchase receipt cost.

A later transaction of:

```text
Customer → Company
```

is a new Purchase, not a Sales Return.

Existing Sales Return is an inventory-side return of a prior Sales Issue and must not be used to simulate a later customer-to-company Purchase.

---

## 8. Confirmed Business Rules

The following are treated as user-provided authoritative requirements:

1. A finalized ordinary Sales transaction transfers ownership to the buyer.
2. Payment status does not determine ownership.
3. Credit, unpaid, and partially paid Sales may transfer ownership.
4. Customer-owned goods may remain physically in a company warehouse.
5. Physical warehouse location is not economic ownership.
6. Company-owned and customer-owned goods may coexist physically.
7. A Sales Invoice may contain lines from multiple warehouses.
8. Sales and physical Warehouse Release are separate concepts.
9. Partial release is required.
10. Warehouse staff must receive an authoritative release/check instruction.
11. Goods unavailable at the time of sale may create a future fulfillment obligation.
12. Future obtained goods first enter company inventory through the existing Purchase/receipt process.
13. A customer-to-company transaction is a new Purchase, not a Sales Return.
14. Rare custody and future-fulfillment scenarios must not make ordinary Sales unnecessarily complex.

These rules do not yet fully define the accounting treatment of customer-owned goods held in company custody.

---

## 9. Normal Sales Workflow

The proposed normal conceptual flow is:

```text
Sales Draft
    ↓
Validated Sales Lines
    ↓
Sales Finalization
    ↓
Customer Ownership / Sales Entitlement
    ↓
Receivable or payment state
    ↓
Warehouse Release Authorization
    ↓
Physical Warehouse Release
    ↓
Physical Issue / customer receipt
```

The following concepts must remain separate:

```text
Sale
Payment
Ownership
Custody
Warehouse
Release
Physical Issue
Fulfillment
Purchase
Sales Return
```

A Sales Invoice may exist with:

```text
Released = 0
```

or:

```text
Released < Sold
```

or:

```text
Released = Sold
```

---

## 10. Ownership Model

### Confirmed ownership rule

For ordinary finalized Sales:

```text
Ownership transfers at Sales finalization.
```

This transfer is independent of payment and physical release.

### Consequence

A customer may own goods that are:

- not yet paid for;
- not yet released;
- physically held in a company warehouse.

### Required distinction

```text
Economic ownership ≠ payment
Economic ownership ≠ physical location
Economic ownership ≠ physical release
```

### Accounting qualification

The business ownership rule is confirmed. The accounting bridge for removing customer-owned goods from company-owned inventory valuation while they remain physically present is not fully defined by the existing accounting contract.

Classification:

```text
UNRESOLVED ACCOUNTING DECISION
```

No accounting entry is invented in this discovery.

---

## 11. Customer Custody Model

### Required scenario

```text
Sold:       2,000 barrels
Released:     200 barrels
Customer-owned custody: 1,800 barrels
```

Later:

```text
Additional release: 300
Total released:     500
Remaining custody:  1,500
```

### Recommended conceptual separation

The existing physical inventory remains:

```text
Product + Warehouse
```

A separate commercial ownership/entitlement/custody layer should conceptually track:

```text
Sales Transaction
Sales Line
Customer Owner
Product
Warehouse Custody Location
Sold Quantity
Custody Quantity
Released Quantity
Remaining Entitlement
```

This is a contract recommendation only. No model or service was created.

### Why a separate layer is required

Adding Owner directly to StockMovement would change:

- stock identity;
- AVCO grouping;
- physical stock totals;
- Purchase behavior;
- Sales Return behavior;
- transfer behavior;
- adjustment behavior;
- concurrency locking;
- existing Phase 6 reports and invariants.

A separate custody/entitlement layer is therefore the smallest candidate architecture that preserves Phase 6 physical inventory semantics while representing customer ownership.

This recommendation remains subject to user approval and accounting resolution.

---

## 12. Warehouse Release / Check Model

### Functional contract

Every finalized Sales Invoice must be capable of generating an authoritative release/check instruction containing at least:

```text
Customer
Sales Invoice
Sales Line
Product
Warehouse
Quantity
Unit
Release status
```

The release process must prevent:

- release above sold quantity;
- release above authorized quantity;
- duplicate release;
- wrong warehouse release;
- wrong Product release;
- release after cancellation or reversal;
- release without a valid Sales source.

### Recommended document boundary

The recommended minimal conceptual structure is:

```text
Sales Invoice
  → Warehouse Release Authorization
      → Warehouse Release Lines
```

A release authorization may group lines by warehouse while preserving each SalesLine identity.

For printing:

- one parent release authorization preserves the complete transaction;
- one printable warehouse-specific release sheet can be generated for each warehouse;
- each sheet contains only its warehouse’s release lines;
- a line may be printed independently when operationally necessary;
- printing does not create a new financial or inventory event;
- printing the same release twice must not create duplicate release.

This is a proposed contract, not an implementation.

---

## 13. Multi-Warehouse Sales

A single Sales Invoice must support multiple Sales Lines with different warehouses:

```text
Invoice S-001

Line 1:
Oil 10L — Warehouse Umar Rahimi — 100 barrels

Line 2:
Liquid Oil 5L — Warehouse Mohib — 50 cartons

Line 3:
Sugar — Warehouse Sadaqat — 20 sacks
```

Warehouse selection belongs to the Sales Line, not only the Sales header.

The release contract must preserve:

```text
Sales Invoice
Sales Line
Warehouse
Product
Quantity
Customer
```

The recommended release grouping is by warehouse for warehouse operations, while maintaining line-level traceability.

A single warehouse field on the Sales header is insufficient.

---

## 14. Partial Release Model

The required quantities are distinct:

| Quantity | Meaning | Authority |
|---|---|---|
| Contracted/Sold Quantity | Quantity finalized in the Sales transaction | SalesLine |
| Physically Available Quantity | Physical Product + Warehouse quantity | StockMovement-derived inventory |
| Released Quantity | Quantity physically handed over | Release records / physical issue events |
| Customer Custody Quantity | Customer-owned quantity still physically held by company | Ownership/custody entitlement layer |
| Remaining Fulfillment Quantity | Sold quantity not yet obtained, allocated, or fulfilled | Sales fulfillment derivation |

The system must not use one number for all five meanings.

For an available sale:

```text
Sold:       2,000
Released:     200
Custody:    1,800
```

For a future sale where physical stock is zero:

```text
Sold:                    5,000
Released:                    0
Customer custody:            0
Remaining fulfillment:   5,000
```

The future-sale case must not fabricate physical inventory.

---

## 15. Future Sales / Fulfillment Model

Required scenario:

```text
Sales finalized: 5,000 barrels
Physical stock:  0
Company obligation: obtain and fulfill 5,000 barrels
```

The conceptual flow is:

```text
Sales obligation
    ↓
No fabricated StockMovement
    ↓
Later Purchase / Receipt
    ↓
Company inventory receives actual cost
    ↓
Goods allocated to the Sales obligation
    ↓
Custody or release according to the approved Sales contract
```

The later Purchase must first enter company inventory through the existing Purchase foundation.

No direct customer-owned receipt may bypass:

- Purchase;
- `receive_stock()`;
- actual cost determination;
- inventory history.

The repository does not yet define the exact fulfillment-allocation accounting bridge.

Classification:

```text
USER DECISION REQUIRED
```

---

## 16. Customer-to-Company Purchase Model

A later transaction where a customer sells goods to the company is:

```text
Customer → Company
= New Purchase
```

It is not automatically:

```text
Sales Return
```

Sales Return remains reserved for returns against an original Sales transaction according to the approved Sales Return contract.

---

## 17. Payment Boundary

Sales and Payment remain separate:

```text
Sales
  ↓
Receivable / payment state
  ↓
Later Payment
```

Payment does not determine ownership under the confirmed business rule.

### Classification

| Capability | Boundary |
|---|---|
| Sales commercial document | Phase 8 |
| Sales ownership entitlement | Phase 8 contract / new custody layer |
| Customer receivable | Phase 8 accounting integration, subject to contract |
| Cash sale | User decision / Payment boundary |
| Customer payment | Phase 9 |
| Partial payment | Phase 9 |
| Customer advance | Phase 9 or later |
| Overpayment | Phase 9 |
| Cross-currency payment | Settlement scope |
| Exchange-house payment | Payment / Exchange House scope |
| Realized settlement FX | Settlement scope |
| Payment allocation | Phase 9 |

Payment must not be used as a hidden ownership trigger.

---

## 18. Accounting Boundary

| Event | Inventory Effect | Ownership Effect | Receivable Effect | Revenue Effect | COGS Effect |
|---|---|---|---|---|---|
| Sales finalization | Must not fabricate physical stock; ordinary physical issue timing remains contract-dependent. | Buyer ownership is established under the confirmed business rule. | Credit Sales may create receivable. | Revenue timing requires final accounting approval, but Phase 0 provides the Sales pattern. | COGS timing is unresolved where sale and physical release are separate. |
| Payment | No direct inventory effect. | Does not determine ownership. | Reduces receivable or creates credit/advance according to Payment contract. | No new revenue. | No COGS. |
| Warehouse Release | Operational authorization and physical release. | Does not independently transfer ownership if ownership already transferred at Sales finalization. | No new receivable. | No new revenue. | May trigger physical issue/COGS if the approved accounting boundary requires it. |
| Physical Issue | Reduces physical stock through `issue_stock()`. | Represents release/fulfillment, not necessarily ownership transfer. | No direct receivable effect. | No direct revenue effect. | May create COGS through future Sales integration. |
| Customer Custody | Physical goods may remain in the warehouse. | Customer remains owner. | No payment effect. | No additional revenue. | Company inventory valuation treatment requires accounting decision. |
| Future Fulfillment Purchase | Goods first enter company inventory at actual cost. | Ownership/entitlement allocation follows Sales contract. | No automatic new receivable. | No new Sales revenue. | Purchase cost remains governed by Purchase and inventory contracts. |
| Customer-to-Company Purchase | New Purchase receipt and inventory effect. | Company becomes buyer/owner according to Purchase contract. | Supplier payable according to Purchase. | No Sales revenue. | Purchase cost follows Purchase/AVCO. |
| Sales Return | Inventory return uses existing return primitive and original cost basis. | Ownership/entitlement is reduced or reversed according to Sales Return contract. | Receivable or customer credit effect depends on payment state. | Sales Returns account `4200` may be involved. | COGS reversal requires Sales accounting contract. |

The table identifies boundaries; it does not authorize journal implementation.

---

## 19. Sales Lifecycle

### Recommended primary Sales lifecycle

```text
DRAFT
  ↓
FINALIZED / POSTED
```

A finalized Sales document should be immutable for commercial fields:

- customer;
- SalesLine Product;
- SalesLine Warehouse;
- quantity;
- price;
- currency;
- rate;
- discounts;
- totals;
- ownership entitlement.

Cancellation, reversal, and correction must use future controlled contracts and should not be invented in this discovery.

### Separate derived/operational states

Sales should not collapse all concepts into one status field.

Separate concepts should exist conceptually for:

```text
Sales status:
DRAFT / FINALIZED

Release state:
NOT_AUTHORIZED / AUTHORIZED / PARTIALLY_RELEASED / RELEASED

Fulfillment state:
NOT_FULFILLED / PARTIALLY_FULFILLED / FULFILLED

Custody state:
NO_CUSTODY / CUSTOMER_CUSTODY / FULLY_RELEASED

Payment state:
UNPAID / PARTIALLY_PAID / PAID / CREDIT_OR_ADVANCE
```

Payment state belongs to the Payment domain and should not control ownership.

---

## 20. Quantity Model

The authoritative conceptual quantities are:

```text
Contracted/Sold Quantity
Physically Available Quantity
Released Quantity
Customer Custody Quantity
Remaining Fulfillment Quantity
```

### Derived relationships

For available goods:

```text
Customer Custody Quantity
= Sold Quantity − Released Quantity
```

provided the sold quantity has been allocated/obtained and remains physically held by the company.

For future sales:

```text
Sold Quantity = 5,000
Released Quantity = 0
Customer Custody Quantity = 0
Remaining Fulfillment Quantity = 5,000
```

The exact fulfillment-allocation rule remains an unresolved contract item.

Ownership must never be derived solely from current physical stock.

---

## 21. Printing Contract

Printing is not implemented in Phase 8 discovery.

The operational contract requires warehouse-facing instructions containing:

```text
Customer
Sales Invoice
Sales Line
Warehouse
Product
Quantity
Unit
Release status
```

Recommended model:

```text
One parent Warehouse Release Authorization
  → warehouse-grouped release lines
  → independently printable warehouse release sheets
```

A printed document is not a new financial event and not a new release event.

Duplicate printing must not duplicate warehouse release.

Partial release requires reprinting or generating a new authorization for only the remaining authorized quantity, according to the later release contract.

---

## 22. Architectural Options

### Option A — Modify Inventory Identity

```text
Product + Warehouse + Owner
```

Advantages:

- direct owner-specific physical stock queries;
- direct separation of owner quantities.

Risks:

- changes Phase 6 stock identity;
- affects AVCO, transfers, returns, adjustments, Purchase, concurrency, and reports;
- high migration and compatibility risk;
- violates the protected-baseline principle unless separately approved.

### Option B — Independent Ownership/Custody Domain

Keep:

```text
Product + Warehouse
```

as physical inventory identity and add a separate entitlement/custody layer.

Advantages:

- preserves Phase 6;
- represents ownership independently from physical location;
- supports multiple owners and customer custody.

Risks:

- requires reconciliation between physical StockMovement and ownership entitlement;
- requires accounting treatment for customer-owned goods;
- requires release and fulfillment rules.

### Option C — Sales/Release Entitlement Layer

Sales owns the commercial entitlement and release relationship, while Inventory remains physical-stock oriented.

Advantages:

- directly supports partial release;
- supports multi-warehouse Sales Lines;
- preserves existing StockMovement identity;
- keeps normal Sales relatively simple.

Risks:

- requires careful entitlement and custody accounting;
- future fulfillment allocation must be defined;
- Sales Return must reference entitlement and release history.

### Option D — Separate Customer-Custody Inventory Subsystem

Customer-owned goods are represented outside ordinary company-owned inventory.

Advantages:

- clear ownership separation;
- useful for reporting and custody obligations.

Risks:

- additional domain complexity;
- risk of duplicating stock/AVCO logic;
- requires explicit reconciliation and transfer rules.

---

## 23. Selected / Recommended Architecture

### Recommendation

The recommended contract direction is:

```text
Keep Phase 6 physical inventory unchanged:
Product + Warehouse

Add a minimal independent Sales Ownership / Entitlement / Custody layer:
Sales + SalesLine + Customer + Product + Warehouse + quantities

Add a Warehouse Release Authorization layer:
SalesLine → Release Authorization → Release Line → physical issue
```

This is an architectural recommendation, not an implementation.

### Reasons

- preserves the frozen Phase 6 StockMovement identity;
- supports multiple owners in one physical warehouse;
- supports ownership transfer independent of payment;
- supports partial release;
- supports goods remaining in company custody;
- supports Sales Lines from multiple warehouses;
- supports future fulfillment without fabricating inventory;
- keeps ordinary Sales simpler than modifying every Phase 6 inventory primitive.

### Important unresolved boundary

The accounting treatment of goods that are customer-owned but physically located in company warehouses remains unresolved.

Before implementation, the contract must define whether such goods:

- leave company inventory valuation at Sales finalization;
- remain in physical stock but are excluded from company-owned reporting;
- require an accounting reclassification;
- are represented through an entitlement-only layer with separate reporting.

No journal entries are invented here.

---

## 24. Decision Matrix

| ID | Decision | Current Evidence | Business Rule | Status | Required Action |
|---|---|---|---|---|---|
| PH8-001 | Ownership transfer | User requires ownership after finalized Sale, independent of payment. | Payment does not control ownership. | CONFIRMED | Preserve in Sales contract. |
| PH8-002 | Customer custody | Customer-owned goods may remain physically in company warehouse. | Custody is separate from company inventory. | USER DECISION REQUIRED | Approve custody/entitlement representation. |
| PH8-003 | Sale vs physical release | User explicitly separates Sale and Warehouse Release. | Sale may exist while release is zero or partial. | CONFIRMED | Define separate release contract. |
| PH8-004 | Payment boundary | Roadmap places Payment after Sales. | Payment is separate from ownership. | CONFIRMED | Keep Payment outside initial Sales implementation. |
| PH8-005 | Revenue account selection | `4110` and `4120` exist; operational rule is absent. | One approved rule must select the account. | USER DECISION REQUIRED | Define Sale Type or other selection rule. |
| PH8-006 | Partial release | User requires 200 then 300 release from 2,000 sold. | Released and custody quantities must be separate. | CONFIRMED | Define release quantity and authorization rules. |
| PH8-007 | Sales Return timing | Inventory-side Sales Return exists; financial Sales does not. | Return depends on Sales, release, payment, and ownership. | USER DECISION REQUIRED | Define integrated Sales Return boundary. |
| PH8-008 | Phase 7 baseline integrity | Purchases registration is in working tree but absent from freeze commit. | Frozen baseline must be reproducible. | HIGH | Resolve or explicitly approve baseline correction. |
| PH8-009 | GitHub baseline verification | No usable remote URL available locally. | Official Phase 7 baseline must be externally identifiable. | EVIDENCE DEBT | Provide/verify authoritative remote. |
| PH8-010 | Company inventory vs custody | User says customer-owned custody is not company-owned inventory. | Physical presence does not imply company ownership. | USER DECISION REQUIRED | Approve accounting and reporting treatment. |
| PH8-011 | Payment vs ownership | User explicitly separates payment and ownership. | Unpaid/partial-paid customers may own goods. | CONFIRMED | Do not use payment as ownership trigger. |
| PH8-012 | Release vs ownership | Ownership occurs at finalized Sale; release is operational. | Release does not independently determine ownership. | CONFIRMED | Keep release separate. |
| PH8-013 | Warehouse at Sales Line level | User requires multiple warehouses on one invoice. | Warehouse belongs to SalesLine. | CONFIRMED | Preserve line-level warehouse. |
| PH8-014 | Multi-warehouse invoice | One invoice may contain multiple warehouse lines. | Release authorization must group or route by warehouse. | CONFIRMED | Define warehouse-grouped release lines. |
| PH8-015 | Release / Check model | Warehouse requires authoritative instruction. | Release must identify customer, invoice, line, Product, Warehouse, quantity, unit. | PROPOSED | Approve parent authorization plus release lines. |
| PH8-016 | Independent item printing | Warehouse action must be possible per item/warehouse. | Printing must not create duplicate release. | PROPOSED | Approve warehouse-grouped printable sheets with line traceability. |
| PH8-017 | Future Sales | Sale may occur with physical stock zero. | No inventory may be fabricated. | CONFIRMED | Define Sales obligation and fulfillment quantities. |
| PH8-018 | Future fulfillment | Later Purchase first enters company inventory at actual cost. | Fulfillment cannot bypass Purchase/receipt. | CONFIRMED | Define allocation bridge. |
| PH8-019 | Customer-to-company Purchase | Customer selling goods to company is a new Purchase. | Do not use Sales Return as substitute. | CONFIRMED | Preserve Purchase boundary. |
| PH8-020 | Fulfillment vs physical inventory | Sold quantity and available quantity are different. | Future obligation must be separately tracked. | USER DECISION REQUIRED | Define fulfillment allocation semantics. |
| PH8-021 | Ownership/custody architecture | Phase 6 has no ownership dimension. | Custody must not rewrite StockMovement identity. | PROPOSED | Approve independent entitlement/custody layer. |
| PH8-022 | Sales lifecycle | Purchase pattern provides DRAFT/POSTED precedent. | Sales finalization should become immutable. | PROPOSED | Approve DRAFT → FINALIZED/POSTED lifecycle. |
| PH8-023 | Finalization immutability | Phase 0 requires posted history immutability. | Finalized Sales commercial facts cannot be rewritten. | CONFIRMED | Reuse existing immutability philosophy. |
| PH8-024 | Sales idempotency | Existing core idempotency is reusable. | Finalization, release, fulfillment, and payment need distinct boundaries. | PROPOSED | Define separate keys per business event. |
| PH8-025 | Custody accounting bridge | Existing contract does not specify journals for customer-owned custody. | No accounting entry may be invented. | UNRESOLVED ACCOUNTING DECISION | Accounting owner must define treatment. |
| PH8-026 | COGS timing | Ownership occurs at finalization, but physical release is separate. | COGS cannot be assumed at payment or release without contract. | UNRESOLVED ACCOUNTING DECISION | Define revenue/COGS timing. |

---

## 25. Stage Plan

The following is a proposed dependency-aware plan, not an approved implementation schedule.

### Stage 8.1 — Sales Commercial Foundation

Scope:

- Sales and SalesLine contract;
- customer validation;
- line-level Product and Warehouse;
- currency/rate context;
- totals and discount rules;
- DRAFT editing;
- finalization boundary;
- audit and idempotency contract.

Prerequisites:

- PH8-005 revenue selection if financial posting is included;
- PH8-022 lifecycle approval;
- PH8-023 immutability confirmation.

Out of scope:

- payment;
- delivery;
- physical issue;
- custody accounting;
- Sales Return accounting.

### Stage 8.2 — Ownership / Entitlement / Custody Contract Layer

Scope:

- customer ownership entitlement;
- customer custody quantities;
- multi-owner warehouse representation;
- future obligation quantities;
- reconciliation with physical stock.

Prerequisites:

- PH8-002;
- PH8-010;
- PH8-021;
- PH8-025.

### Stage 8.3 — Financial Sales Posting

Scope:

- receivable or approved cash boundary;
- revenue account selection;
- historical currency/rate context;
- audit and attribution;
- atomic posting.

Prerequisites:

- PH8-004;
- PH8-005;
- PH8-025;
- PH8-026.

### Stage 8.4 — Warehouse Release Authorization

Scope:

- line-level warehouse release instructions;
- multi-warehouse grouping;
- authorization quantity;
- duplicate-release prevention;
- printable release contract.

Prerequisites:

- PH8-003;
- PH8-006;
- PH8-014;
- PH8-015;
- PH8-016.

### Stage 8.5 — Physical Issue / Fulfillment

Scope:

- physical release;
- `issue_stock()` integration;
- release quantity reconciliation;
- COGS timing if approved;
- fulfillment status.

Prerequisites:

- PH8-003;
- PH8-006;
- PH8-018;
- PH8-020;
- PH8-026.

### Stage 8.6 — Future Fulfillment

Scope:

- Sales obligation with zero current stock;
- later Purchase allocation;
- actual cost preservation;
- fulfillment without fabricated inventory.

Prerequisites:

- PH8-017;
- PH8-018;
- PH8-020.

### Stage 8.7 — Sales Return Integration

Scope:

- original Sales reference;
- released and unreleased quantities;
- custody entitlement;
- receivable/customer-credit effects;
- COGS and original-cost treatment.

Prerequisites:

- PH8-007;
- PH8-011;
- PH8-012;
- payment contract.

### Stage 8.8 — Payment and Settlement

Scope:

- customer payment;
- allocation;
- advances;
- overpayment;
- cash/exchange-house payment;
- realized FX.

This belongs to the later Payment boundary and should not be silently included in Sales.

---

## 26. Validation / Adversarial Scenarios

| Scenario | Contract-level result |
|---|---|
| A. Normal cash sale | Sales finalizes ownership; cash/payment remains separate; immediate release creates physical issue when authorized. |
| B. Normal credit sale | Customer owns goods despite unpaid receivable; payment does not control ownership. |
| C. Customer leaves goods | Sold goods become customer-owned custody; physical location remains company warehouse; custody quantity is separately tracked. |
| D. Multiple warehouses | SalesLine carries Warehouse; release authorization groups lines by warehouse. |
| E. Partial release | Sold 2,000, release 200, later 300; custody/remaining quantities derive from release history, not current stock alone. |
| F. Future sale | Sales obligation exists with physical stock zero; no fabricated StockMovement. |
| G. Future fulfillment | Later Purchase enters company inventory first, cost is determined, then goods are allocated to the Sales obligation. |
| H. Customer sells to company | New Purchase, not Sales Return. |
| I. Multiple owners in one warehouse | Physical inventory and ownership/custody reporting remain separate. |
| J. Partial payment | Customer ownership remains governed by finalized Sales, not payment percentage; receivable remains. |
| K. Multi-warehouse printing | One parent release authorization with warehouse-specific, independently printable release sheets. |

### Negative / abuse cases

The future contract must reject or prevent:

- duplicate Warehouse Release;
- release above sold quantity;
- release above authorized quantity;
- release from the wrong Warehouse;
- release of the wrong Product;
- release after cancellation or controlled reversal;
- editing finalized SalesLine Warehouse;
- editing quantity after release;
- duplicate future fulfillment;
- fulfillment above contracted quantity;
- mixing customer-owned custody with company-owned inventory;
- using Sales Return to simulate a Purchase;
- treating payment as ownership transfer;
- treating physical location as ownership;
- fabricating inventory for an unavailable future sale.

---

## 27. Implementation Gate

```text
IMPLEMENTATION PERFORMED: NO
```

Confirmed:

- no models were added;
- no migrations were created;
- no services were modified;
- no APIs were created;
- no frontend code was added;
- no tests were added or modified;
- no accounting logic was modified;
- no inventory logic was modified;
- no settings were modified;
- no dependencies were changed;
- no commit was created;
- no branch was created;
- no push was performed.

A discovery report was created as the requested contract artifact only.

---

## 28. Evidence

### Repository evidence

```text
Branch: phase/4
HEAD: 692e2735234e2d123625bc2dc9a2f15be9c0e564
Latest Phase 7 freeze: 692e273
Working tree: not clean
```

### Existing directories inspected

```text
backend/accounting/
backend/cash_accounts/
backend/exchange_houses/
backend/fiscal_periods/
backend/inventory/
backend/parties/
backend/party_ledger/
backend/payments/
backend/purchases/
backend/returns/
backend/sales/
backend/purchasing/
backend/remittance/
backend/reporting/
```

### Baseline tests

The current SQLite baseline was executed:

```text
$ cd backend && .venv/bin/pytest -q

723 passed, 2 skipped in 77.50s
```

The two skipped tests are PostgreSQL-dependent Phase 6 concurrency tests.

### PostgreSQL

```text
POSTGRESQL VERIFICATION: BLOCKED
Reason: PostgreSQL was unavailable at 127.0.0.1:5432.
```

No PostgreSQL verification is claimed.

No tests were added or modified.

---

## 29. Remaining User Decisions

Before implementation, the user must resolve:

1. accounting treatment of customer-owned custody goods;
2. revenue recognition and COGS timing when finalization and release are separate;
3. `4110` versus `4120` selection rule;
4. exact custody/entitlement architecture;
5. release authorization and printable document structure;
6. fulfillment allocation for future Sales;
7. Sales Return treatment across unpaid, partially paid, fully paid, custody, and partially released Sales;
8. official Phase 7 baseline registration;
9. GitHub authoritative baseline verification.

---

## 30. Final Recommendation

The recommended contract direction is:

```text
Keep Phase 6 physical inventory unchanged:
Product + Warehouse

Add a minimal independent Sales ownership / entitlement / custody layer.

Add a Warehouse Release Authorization layer with line-level traceability.

Use existing accounting, Party Ledger, fiscal, money, audit, idempotency,
and inventory primitives rather than creating duplicate engines.
```

The normal Sales workflow should remain simple:

```text
Sales Draft
  → Finalized Sale / Customer Ownership
  → Receivable or later Payment
  → Warehouse Release Authorization
  → Physical Release / Issue
  → Custody and Fulfillment Reconciliation
```

Rare scenarios such as future Sales, customer custody, multiple owners, and delayed fulfillment should be handled by explicit additional layers rather than by rewriting the frozen inventory identity.

The accounting treatment of customer-owned custody goods and the exact `4110`/`4120` selection rule must be resolved before financial Sales implementation.

---

## 31. STOP

Phase 8 Contract Discovery is complete.

No implementation was performed.

No code, tests, migrations, settings, accounting, inventory, Purchase, or Phase 0–7 systems were modified.

**STATUS: CONTRACT DISCOVERY COMPLETE — IMPLEMENTATION NOT PERFORMED — WAITING FOR USER REVIEW AND APPROVAL**
