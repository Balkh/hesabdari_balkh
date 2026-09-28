# Phase 8 — Sales Contract Resolution & Custody Discovery Report

**Status:** BLOCKED — USER DECISIONS REQUIRED  
**Mode:** Contract / Discovery Only  
**Implementation:** None  
**Branch:** `phase/4`  
**HEAD:** `692e2735234e2d123625bc2dc9a2f15be9c0e564`  
**Latest Phase 7 Freeze:** `692e273` — `freeze phase 7`

---

## 1. Discovery Scope

This report covers the Phase 8 Sales contract and business-semantics discovery, with particular attention to:

- Sales Invoice;
- ownership transfer;
- physical delivery and release;
- customer-owned goods remaining in company warehouses;
- partial release;
- receivables;
- revenue;
- COGS;
- payment boundaries;
- Sales Returns;
- coexistence of company-owned and customer-owned goods in one warehouse.

No models, migrations, services, APIs, tests, accounting code, inventory code, settings, commits, or architectural changes were created during this discovery.

---

## 2. Repository Baseline

### Git state

```text
Branch: phase/4
HEAD:   692e2735234e2d123625bc2dc9a2f15be9c0e564
```

The working tree is not clean and contains pre-existing changes:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
```

No changes were made during Phase 8 discovery.

### Phase 7 baseline inconsistency

The current working tree contains the Purchase application registration in:

```text
backend/config/settings/base.py
```

However, the committed Phase 7 freeze commit does not contain the `purchases` entry in `INSTALLED_APPS`.

Therefore, the current working tree and the committed Phase 7 snapshot are not identical.

Classification:

```text
HIGH — Phase 7 baseline integration inconsistency
```

This issue was not corrected during discovery.

### GitHub verification

The local repository contains remote-tracking references, but no usable remote URL was available through the current Git configuration. The GitHub branch containing the approved Phase 7 freeze could therefore not be independently verified.

Classification:

```text
EVIDENCE DEBT
```

---

## 3. Protected Phase 0–7 Baseline

The following systems remain protected:

### Accounting

- Chart of Accounts;
- JournalEntry and JournalLine;
- `post_journal()`;
- money precision;
- currency separation;
- historical exchange rates;
- realized FX;
- accounting idempotency;
- posted-history immutability.

### Fiscal Periods

- open/closed/locked periods;
- posting-date validation;
- historical protection;
- fiscal audit behavior.

### Party Ledger

- Party and customer/supplier roles;
- PartyLedgerAttribution;
- receivable and payable derivation;
- customer credit;
- supplier advances;
- currency-separated positions.

### Inventory

- Product + Warehouse stock identity;
- StockMovement;
- `receive_stock()`;
- `issue_stock()`;
- AVCO;
- transfers;
- adjustments;
- waste;
- shortage;
- Purchase Return;
- Sales Return;
- inventory idempotency;
- movement immutability;
- concurrency protections.

### Purchase

- Purchase and PurchaseLine;
- DRAFT/POSTED lifecycle;
- validated draft editing;
- final validation;
- supplier payable;
- inventory receipt;
- freight and discount rules;
- Purchase Return boundary;
- posted immutability;
- bulk ORM immutability.

No ownership dimension should be added to StockMovement during Phase 8 without a separate approved contract.

---

## 4. Authoritative Contracts Inspected

The following repository documents and implementation surfaces were inspected:

```text
docs/phase-0/PHASE_0_CONTRACT_V2.1.md
docs/phase-0/PHASE_2_PLAN.md
docs/phase-reports/PHASE_6_INVENTORY_ARCHITECTURE_DISCOVERY.md
docs/phase-reports/PHASE_6_STAGE_6.1_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.2_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.3_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.4_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.5_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.3_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.4_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.5_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.6_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.7_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_FIX_POSTED_PURCHASE_BULK_IMMUTABILITY_EVIDENCE.md
```

No dedicated authoritative Phase 8 specification was found.

The Phase 2 roadmap identifies the next broad capability as:

```text
Phase 8 — Sales
```

with the conceptual scope:

- Sales Invoice;
- Inventory Issue;
- COGS;
- Revenue;
- Customer Receivable;
- Gross Profit.

The repository does not contain a detailed Phase 8 contract covering ownership, custody, delivery, release, or payment timing.

---

## 5. Existing Sales Capability

The repository does not currently contain:

- Sales model;
- SalesLine model;
- Sales service;
- Sales posting workflow;
- Sales API;
- Sales serializer or view;
- Sales UI;
- Sales lifecycle;
- Sales-specific idempotency;
- Sales-specific audit;
- Sales-specific immutability.

The current Sales directory is only:

```text
backend/sales/.gitkeep
```

Existing reusable capabilities include:

- Party customer roles;
- customer receivable and customer-credit ledger types;
- `issue_stock()`;
- `SALES_ISSUE` StockMovement;
- AVCO;
- Sales Return inventory events;
- Sales revenue accounts;
- COGS account;
- cash accounts;
- exchange-house accounts;
- accounting journal primitives.

These are foundations, not a complete Sales workflow.

---

## 6. Sales Business Model

The Phase 0 contract conceptually defines:

### Credit sale

```text
Dr 1310 Trade Receivables
Cr 4110 Wholesale Sales or 4120 Retail Sales
```

### Cash sale

```text
Dr Cash
Cr Sales Revenue
```

### COGS

```text
Dr 5100 COGS
Cr Inventory
```

The repository does not yet define the operational rules for:

- Sales document lifecycle;
- revenue recognition timing;
- receivable creation timing;
- invoice versus delivery timing;
- ownership transfer;
- customer-owned custody;
- payment relationship;
- selection of `4110` versus `4120`.

The accounting primitives exist, but the complete Sales contract does not.

---

## 7. Mukhtar / Ahmad Ownership Scenario

The required business scenario is:

```text
Mukhtar owns 2,000 barrels.
Mukhtar sells all 2,000 barrels to Ahmad.
The goods remain physically inside the company warehouse.
```

After the transaction becomes legally/economically effective:

```text
Economic ownership: Ahmad
Physical custody:    Company warehouse
```

If Ahmad later requests a release:

```text
Originally sold:          2,000
Released:                   200
Remaining custody:        1,800
```

After another release:

```text
Additional release:        300
Total released:             500
Remaining custody:        1,500
```

The following concepts must remain separate:

```text
Economic ownership
Physical location
Customer entitlement
Physical release
Custody quantity
Financial settlement
```

The existing Phase 6 stock identity is:

```text
Product + Warehouse
```

It does not represent customer ownership or entitlement.

Classification:

```text
USER DECISION REQUIRED
```

---

## 8. Multiple Owners in One Warehouse

Required scenario:

```text
Warehouse A

Company-owned:  5,000 units
Ahmad-owned:    1,800 units
Mahmoud-owned:    700 units
Karim-owned:    1,200 units
```

The current Product + Warehouse stock identity cannot distinguish these positions by itself.

Possible conceptual approaches are:

### A. Ownership-aware inventory

```text
Product + Warehouse + Owner
```

Consequences:

- changes Phase 6 stock identity;
- affects stock aggregation;
- affects AVCO;
- affects transfers;
- affects returns;
- affects adjustments;
- affects concurrency locking;
- affects Purchase and Sales behavior.

### B. Separate custody or entitlement domain

Keep canonical stock as:

```text
Product + Warehouse
```

and maintain a separate immutable entitlement/custody layer.

Consequences:

- preserves Phase 6 stock semantics;
- requires reconciliation between physical stock and customer entitlements;
- requires release, return, and correction rules;
- requires explicit treatment of valuation and ownership.

### C. Sales and release layer

Track:

```text
Sold quantity
Released quantity
Remaining entitlement
```

above the existing inventory engine.

Consequences:

- invoice and release become separate concepts;
- `issue_stock()` may represent release rather than initial sale;
- partial release becomes traceable;
- ownership remains a commercial/entitlement concept.

### D. Separate custody inventory domain

Customer-owned goods are represented outside ordinary company-owned inventory.

Consequences:

- strongest separation between company inventory and custody goods;
- requires separate reconciliation and custody lifecycle rules;
- must not become a duplicate AVCO or stock engine.

No option is selected during discovery.

Classification:

```text
USER DECISION REQUIRED
```

---

## 9. Ownership Transfer Analysis

| Option | Ownership | Revenue / Receivable | COGS / Inventory | Partial Payment | Partial Release | Sales Return |
|---|---|---|---|---|---|---|
| A. At Sales Invoice | Customer owns goods when invoice posts. | Revenue and receivable may post at invoice. | COGS and inventory issue likely post at invoice. | Payment does not control ownership. | Release becomes physical custody only. | Return must address customer-owned goods and financial reversal. |
| B. After Full Payment | Ownership transfers only after settlement. | Invoice may create receivable before ownership transfers. | COGS timing becomes ambiguous until payment. | Partial payment does not transfer ownership. | Release before full payment needs special rules. | Return depends on ownership state. |
| C. Proportional to Payment | Ownership increases with payment. | Requires payment-to-quantity allocation. | COGS and ownership become proportional. | Requires precise allocation and rounding. | Release may differ from paid ownership. | Return requires proportional rules. |
| D. At Physical Release | Customer owns only released quantities. | Invoice may create receivable before ownership. | COGS and issue occur at release. | Payment remains separate. | Naturally supports 200 then 300 releases. | Return is tied to released quantities. |
| E. Separate Ownership Event | A separate approved event transfers ownership. | Timing must be defined relative to the event. | Custody and company stock can remain separate. | Payment may remain independent. | Release can be separate from ownership. | Return can reference ownership and release history. |

No option is selected.

Classification:

```text
USER DECISION REQUIRED
```

---

## 10. Invoice, Delivery, Release, and Custody

### Model 1 — One event

```text
Invoice = Sale + Delivery + Ownership Transfer
```

This is simple, but it cannot naturally support sold goods remaining in custody or delayed partial release.

### Model 2 — Two events

```text
Invoice
Delivery / Release
```

This supports partial release, but ownership timing remains unresolved.

### Model 3 — Three concepts

```text
Sale
Delivery / Release
Ownership / Entitlement
```

This most clearly represents the Mukhtar/Ahmad scenario, but requires additional approved domain contracts.

The repository does not determine which model is correct.

Classification:

```text
USER DECISION REQUIRED
```

---

## 11. Customer-Owned Custody and Accounting

The business must determine whether customer-owned goods physically held in the warehouse are treated as:

### Company inventory

Consequences may include:

- inclusion in inventory valuation;
- potential effect on AVCO;
- possible COGS implications;
- company warehouse reporting;
- possible balance-sheet recognition.

### Non-company custody / customer entitlement

Consequences may include:

- exclusion from company inventory valuation;
- separate customer entitlement reporting;
- separate custody quantity tracking;
- release and return tracking;
- reconciliation between physical custody and entitlement.

The repository does not decide this question.

Classification:

```text
USER DECISION REQUIRED
```

---

## 12. Payment Boundary

| Capability | Classification |
|---|---|
| Sales Invoice without payment | Phase 8 candidate |
| Credit sale | Phase 8 candidate, contract details required |
| Cash sale | User decision / possible Phase 9 boundary |
| Customer payment | Phase 9 |
| Partial payment | Phase 9 |
| Customer advance | Phase 9 or later |
| Customer overpayment | Phase 9 |
| Cross-currency payment | Settlement scope |
| Exchange-house payment | Payment / Exchange House scope |
| Realized settlement FX | Settlement scope |
| Payment allocation | Phase 9 |
| Customer credit creation | Phase 9 or Returns integration |

The Phase 2 roadmap places Payments after Sales:

```text
Phase 8 — Sales
Phase 9 — Payments
Phase 10 — Returns
Phase 11 — Cash and Exchange House
```

Payment and settlement should not be silently included in the first Sales implementation.

---

## 13. Revenue Mapping

The existing COA contains:

```text
4110 Wholesale Sales
4120 Retail Sales
```

Both are posting accounts, but the operational selection rule is not defined.

Possible rules include:

- explicit Sale Type;
- customer classification;
- pricing classification;
- product classification;
- another approved master-data rule.

No existing rule conclusively selects `4110` versus `4120`.

Classification:

```text
4110 / 4120 selection = USER DECISION REQUIRED
```

---

## 14. Sales Return Boundary

Phase 6 already provides inventory-side Sales Return behavior based on the original source movement and original recorded cost.

Full Sales Return integration still depends on:

- original Sales Invoice;
- receivable state;
- payment state;
- customer credit;
- proportional settlement;
- COGS reversal;
- Sales Returns account `4200`.

The following cases remain unresolved:

- unpaid sale;
- partially paid sale;
- fully paid sale;
- sale with customer-owned custody goods;
- sale where only part of the quantity was released.

No Sales Return accounting should be implemented before these dependencies are contractually defined.

---

## 15. Partial Release

The repository has no primitive that independently tracks:

```text
Sold quantity
Released quantity
Remaining entitlement
Physical warehouse quantity
Custody quantity
```

Existing `StockMovement` can represent a physical issue, but it does not represent commercial entitlement or customer ownership.

Classification:

```text
USER DECISION REQUIRED
```

---

## 16. Reusable Primitives

Future Sales work should reuse:

```text
Party customer role
Product
Warehouse
Currency
core.money
post_journal()
attribute_journal_line()
PartyLedgerAttribution
issue_stock()
StockMovement
AVCO
assert_posting_date_open()
record_audit_event()
core.idempotency
```

No second accounting, inventory, AVCO, Party Ledger, FX, audit, or idempotency engine should be created.

A separate custody or entitlement domain may be necessary because the existing Product + Warehouse stock identity cannot represent customer ownership. That domain requires an approved contract before implementation.

---

## 17. Phase 8 Stage Options

### Sequence A

```text
8.1 Sales Draft
8.2 Sales Posting
8.3 Inventory / COGS
8.4 Delivery / Release
8.5 Custody
```

Risk: Sales posting may be implemented before ownership and delivery semantics are settled.

### Sequence B

```text
8.1 Sales Contract
8.2 Sales + Accounting
8.3 Sales + Inventory
8.4 Delivery / Custody
```

Risk: financial posting may still depend on unresolved ownership and release timing.

### Sequence C

```text
8.1 Sales Commercial Foundation
8.2 Ownership / Entitlement Contract
8.3 Financial Sales Posting
8.4 Physical Release
```

Benefit: ownership and custody semantics are resolved before financial integration.

No sequence is selected during discovery.

---

## 18. User Decision Matrix

| ID | Decision | Why it matters | Options | Blocking? |
|---|---|---|---|---|
| PH8-001 | Ownership transfer point | Determines ownership, revenue, receivable, COGS, inventory, and return timing. | Invoice; full payment; proportional payment; physical release; separate event. | Yes |
| PH8-002 | Custody representation | Current Product + Warehouse identity cannot distinguish owners. | Entitlement domain; ownership-aware inventory; release layer; separate custody domain. | Yes |
| PH8-003 | Invoice versus delivery | Determines when inventory and COGS are posted. | One event; invoice plus delivery; sale plus delivery plus entitlement. | Yes |
| PH8-004 | Payment scope | Determines whether Sales includes cash and settlement behavior. | Sales only; credit sale; cash sale; defer payments to Phase 9. | Yes |
| PH8-005 | Revenue account selection | Determines use of `4110` versus `4120`. | Sale Type; customer classification; pricing classification; other approved rule. | Yes |
| PH8-006 | Partial release | Determines how sold, released, custody, and remaining quantities are tracked. | Release document; fulfillment quantities; entitlement-linked issue; other mechanism. | Yes |
| PH8-007 | Sales Return timing | Depends on invoice, release, payment, and ownership. | Define with Sales; defer to Payment; inventory-only first; other sequence. | Yes |
| PH8-008 | Phase 7 baseline registration | `purchases` registration exists in the working tree but not in the freeze commit. | Correct official baseline; explicitly exclude; separate approved correction. | Yes for clean baseline |
| PH8-009 | GitHub baseline verification | Current remote configuration cannot independently confirm the pushed freeze. | Provide authoritative remote; confirm local commit; other verification. | Yes for external baseline |
| PH8-010 | Company inventory versus custody | Determines valuation, COGS, gross profit, and reporting. | Company inventory; non-company custody; separate event treatment. | Yes |
| PH8-011 | Payment and ownership relationship | Determines whether non-payment delays or reverses ownership. | Independent; ownership after payment; proportional; other. | Yes |
| PH8-012 | Release and ownership relationship | Determines whether release is physical delivery, ownership transfer, or both. | Release transfers ownership; release follows ownership; separate event. | Yes |

---

## 19. Proposed Initial Phase 8 Boundary

A safe first stage cannot yet include integrated Sales financial posting because ownership, custody, delivery, release, and payment semantics remain unresolved.

A possible bounded first stage after the required decisions is:

### Phase 8 Stage 8.1 — Sales Commercial Foundation

Potential scope:

- Sales and SalesLine contract;
- customer validation through existing Party roles;
- Product and Warehouse validation;
- currency and historical-rate context;
- DRAFT lifecycle;
- validated draft editing;
- deterministic totals;
- discount rules;
- CREATE and UPDATE audit;
- final validation;
- no financial or inventory effects before an approved posting contract.

Explicitly out of scope for this candidate:

- ownership transfer;
- customer-owned custody;
- payment;
- settlement;
- cash sale;
- receivable posting;
- revenue posting;
- COGS;
- inventory issue;
- delivery;
- release;
- Sales Return accounting.

If the first stage must include actual Sales posting, PH8-001 through PH8-007 must be resolved first.

---

## 20. Evidence

### Existing files and code inspected

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
docs/phase-0/PHASE_0_CONTRACT_V2.1.md
docs/phase-0/PHASE_2_PLAN.md
docs/phase-reports/PHASE_6_INVENTORY_ARCHITECTURE_DISCOVERY.md
docs/phase-reports/PHASE_6_STAGE_6.1_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.2_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.3_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.4_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.5_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.3_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.4_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.5_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.6_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_STAGE_7.7_IMPLEMENTATION_EVIDENCE.md
docs/phase-reports/PHASE_7_FIX_POSTED_PURCHASE_BULK_IMMUTABILITY_EVIDENCE.md
```

### Baseline test

The current SQLite baseline was executed:

```text
$ cd backend && .venv/bin/pytest -q

723 passed, 2 skipped in 77.50s
```

The two skipped tests are PostgreSQL-dependent Phase 6 concurrency tests.

No Phase 8 tests were added or modified.

### Existing relevant test suites

```text
backend/accounting/coa_tests.py
backend/accounting/golden_tests.py
backend/accounting/fx_tests.py
backend/accounting/integrity_tests.py
backend/accounting/journal_tests.py
backend/currencies/tests.py
backend/cash_accounts/cashaccount_tests.py
backend/exchange_houses/exchangehouse_tests.py
backend/fiscal_periods/period_tests.py
backend/fiscal_periods/period_golden_tests.py
backend/inventory/inventory_tests.py
backend/parties/party_tests.py
backend/party_ledger/ledger_tests.py
backend/products/product_tests.py
backend/purchases/purchase_tests.py
```

These suites provide reusable patterns for journal posting, receivables, revenue, COGS, FX, Party Ledger attribution, inventory issue, AVCO, returns, fiscal gates, idempotency, rollback, and immutability.

### PostgreSQL

```text
PostgreSQL verification: BLOCKED / NOT EXECUTED
Reason: PostgreSQL was unavailable at 127.0.0.1:5432.
```

SQLite evidence is not treated as PostgreSQL evidence.

---

## 21. Findings Classification

| Finding | Classification |
|---|---|
| No dedicated authoritative Phase 8 specification exists. | EVIDENCE DEBT |
| Sales is identified as the next roadmap capability. | NO FINDING |
| Full Sales Invoice workflow does not exist. | INTENTIONAL FUTURE SCOPE |
| Payment and settlement workflows do not exist. | INTENTIONAL FUTURE SCOPE |
| Customer-owned custody semantics are not defined. | USER DECISION REQUIRED |
| Ownership transfer timing is not defined. | USER DECISION REQUIRED |
| Invoice versus delivery timing is not defined. | USER DECISION REQUIRED |
| Product + Warehouse stock identity must not be silently extended with ownership. | NO FINDING |
| Existing COA supports receivables, revenue, COGS, returns, cash, and FX concepts. | NO FINDING |
| Phase 7 freeze commit and current working tree differ regarding Purchase app registration. | HIGH |
| GitHub branch containing the approved freeze could not be independently verified. | EVIDENCE DEBT |
| Existing Phase 6 and Phase 7 protected surfaces remain reusable. | NO FINDING |

---

## 22. Final Status

```text
BLOCKED — USER DECISIONS REQUIRED
```

Phase 8 Sales implementation must not begin until the ownership, custody, delivery, release, payment, revenue-account, and baseline questions are resolved.

No implementation was performed.

**STOP — USER REVIEW REQUIRED.**
