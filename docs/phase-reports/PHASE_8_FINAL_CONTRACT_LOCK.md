# Phase 8 — Final Sales Contract Lock

**Repository:** `Balkh/hesabdari_balkh`  
**Mode:** Discovery / contract lock only  
**Implementation:** Not performed  
**Classification:** `PHASE 8 CONTRACT LOCK PREPARED — IMPLEMENTATION NOT PERFORMED — WAITING FOR USER REVIEW AND APPROVAL`

This report supersedes the earlier Phase 8 discovery wording where necessary. In particular, it incorporates the authoritative distinction between **Type A Available/Ordinary Sale** and **Type B Future/Forward Sale**.

Every conclusion is classified as one of:

```text
USER DIRECTIVE
REPOSITORY FACT
TEST EVIDENCE
ARCHITECTURAL PROPOSAL
UNRESOLVED DECISION
```

---

## A. Repository Baseline

### A.1 Branch and HEAD

```text
Branch: phase/4
HEAD:   692e2735234e2d123625bc2dc9a2f15be9c0e564
HEAD message: freeze phase 7 purchase workflow
```

**Classification:** `REPOSITORY FACT`

### A.2 Working-tree status

At inspection time:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_8_FINAL_SALES_CONTRACT_RESOLUTION.md
?? docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_CUSTODY_DISCOVERY.md
?? docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_REPORT.md
```

This discovery did not clean, discard, or overwrite those changes.

**Classification:** `REPOSITORY FACT`

### A.3 Exact relevant diff

The tracked settings diff is exactly the Purchase application registration:

```diff
- "party_ledger", "inventory",
+ "party_ledger", "inventory", "purchases",
```

The other tracked working-tree change is in:

```text
docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
```

Its diff is documentation-only and was not modified during this lock task.

**Classification:** `REPOSITORY FACT`

### A.4 Remote/GitHub status

No usable Git remote URL is configured in the inspected repository. Therefore:

```text
GITHUB BASELINE VERIFICATION: BLOCKED / NOT AVAILABLE
```

No GitHub branch, main branch, merge commit, or remote Phase 7 baseline is claimed as verified.

**Classification:** `REPOSITORY FACT / BLOCKED — BASELINE EVIDENCE`

### A.5 Relevant repository areas

```text
backend/accounting/
backend/currencies/
backend/inventory/
backend/parties/
backend/party_ledger/
backend/purchases/
backend/sales/.gitkeep
backend/payments/.gitkeep
backend/returns/.gitkeep
backend/reporting/.gitkeep
backend/config/settings/base.py
docs/phase-0/
docs/phase-reports/
```

Sales, Payments, Returns, and Reporting are placeholders; Purchase, accounting, Party Ledger, currencies, and inventory contain the protected foundations.

**Classification:** `REPOSITORY FACT`

---

## B. Protected Contracts

The following must remain untouched by Phase 8 unless a later, explicit Phase 6/7 change is approved:

- Phase 0 domain and accounting contracts;
- `JournalEntry` and `JournalLine`;
- `post_journal()` and reversal/posted-history rules;
- money precision and rounding;
- Currency, Exchange Rate, and Rate Date behavior;
- fiscal-period validation and posting gates;
- Party and Party roles;
- PartyLedgerAttribution and receivable/payable derivation;
- Product and Warehouse;
- `StockMovement`;
- Product + Warehouse physical stock identity;
- `receive_stock()`;
- `issue_stock()`;
- AVCO and inventory cost history;
- inventory idempotency and concurrency protection;
- Purchase and PurchaseLine;
- Purchase posting and Purchase receipt;
- Purchase immutability;
- existing return primitives;
- audit conventions.

### Absolute inventory protection

The protected physical identity remains:

```text
Product + Warehouse
```

Phase 8 must not change it to:

```text
Product + Warehouse + Owner
```

and must not introduce a second inventory or AVCO engine.

**Classification:** `USER DIRECTIVE + REPOSITORY FACT`

---

## C. Sales Domain Contract

### C.1 Sales

A Sales document is the commercial transaction between the company and a customer. It contains:

- customer Party;
- currency;
- exchange rate and rate date where required by existing money/FX conventions;
- Sale Type;
- SalesLines;
- totals according to the existing money/precision conventions;
- lifecycle state;
- audit and idempotency identity.

A Sales document is not a Payment, Warehouse Release, physical issue, fulfillment allocation, or Sales Return.

### C.2 SalesLine

Each SalesLine contains, conceptually:

- Product;
- Warehouse;
- unit;
- contracted/sold quantity;
- unit price;
- discount according to the existing totals contract;
- line total;
- ownership/entitlement relationship;
- release and fulfillment references.

Warehouse is mandatory at line level. A header-only Warehouse is prohibited.

### C.3 Commercial lifecycle

The minimum commercial lifecycle is:

```text
DRAFT → FINALIZED
```

`FINALIZED` is the commercial Sales state. It is not silently replaced with `POSTED`, because financial posting timing remains an accounting decision and must not be conflated with ownership or physical release.

If a later financial contract requires a posting state, that state must be separate or explicitly mapped to the existing journal lifecycle. This report does not select that mapping.

After finalization, commercial facts are immutable:

- Customer;
- Product;
- Warehouse;
- quantity;
- unit;
- price;
- discount;
- currency;
- exchange rate;
- rate date;
- totals;
- Sale Type;
- ownership/entitlement basis.

**Classification:** `USER DIRECTIVE + ARCHITECTURAL PROPOSAL`

---

## D. Sale Types

The final contract must distinguish two business modes. A conceptual Sale Type discriminator is required; a literal field name such as `sale_type` is an implementation choice and is not created here.

### D.1 Type A — Available / Ordinary Sale

Definition:

```text
Goods physically exist and are available/obtained at Sale finalization.
```

Conceptual flow:

```text
Sales Finalization
  → buyer ownership
  → immediate customer collection OR company custody
  → later Warehouse Release
```

Rules:

- payment does not transfer ownership;
- physical release does not transfer ownership;
- finalization transfers ownership;
- customer may leave goods in company custody indefinitely;
- partial and multiple releases are allowed;
- customer-owned goods may coexist with company-owned goods in one Warehouse.

### D.2 Type B — Future / Forward Sale

Definition:

```text
A commercial Sale/obligation is finalized before the physical goods exist in company inventory.
```

At finalization:

```text
Commercial entitlement exists
Physical stock does not exist
Physical custody does not exist
Physical release has not occurred
```

Rules:

- no StockMovement is fabricated;
- the customer has a contractual/commercial entitlement;
- the customer is not automatically treated as physical owner of nonexistent goods;
- later Purchase and receipt must create actual company inventory first;
- allocation must identify the actual inventory source;
- after actual goods are obtained and the authoritative Warehouse Release Authorization / Warehouse Issue Check is issued, physical-goods ownership transfers according to this Future Sale rule;
- physical release remains separate from authorization.

The Type B ownership rule is intentionally different from Type A.

**Classification:** `USER DIRECTIVE`

### D.3 Is a Sale Type distinction necessary?

Yes, conceptually. Type A and Type B have different ownership triggers and different quantity/custody semantics. A single undifferentiated Sale contract would silently produce a contradiction:

```text
Type A: finalization → ownership
Type B: finalization → commercial entitlement only;
        authorization after actual fulfillment → physical ownership
```

A future implementation may represent this with the smallest explicit discriminator that does not duplicate existing domain concepts.

**Classification:** `ARCHITECTURAL PROPOSAL grounded in USER DIRECTIVE`

---

## E. Ownership Contract

### E.1 Type A ownership

For an Available/Ordinary Sale:

```text
Sales Finalization → buyer owns the goods
```

This applies to:

```text
Cash Sale
Credit Sale
Partial Payment
Zero Payment
```

Payment is never the trigger. Physical release is never the trigger.

### E.2 Type B ownership

For a Future/Forward Sale:

```text
Sales Finalization → commercial entitlement only
Purchase/receipt → actual company inventory
Allocation → identifies the actual goods for the obligation
Warehouse Release Authorization / Warehouse Issue Check
             → physical-goods ownership transfers according to the Future Sale rule
```

The authorization event transfers ownership for the actual allocated physical goods. Physical release remains a separate operational event.

If allocated goods remain physically in the company Warehouse after authorization but before collection, they are customer-owned custody goods under the custody contract.

### E.3 Ownership is not payment, location, or release

```text
Ownership ≠ Payment
Ownership ≠ Physical Location
Ownership ≠ Physical Release
```

The Type A and Type B triggers are not to be collapsed.

**Classification:** `USER DIRECTIVE`

---

## F. Custody Contract

Customer custody means:

```text
Customer owns actual goods
Company physically holds those goods
Collection date is unknown, later, or open-ended
```

Custody is possible:

- for Type A after finalization and before physical release;
- for Type B after actual receipt, allocation, and Warehouse Release Authorization, if the goods remain physically held by the company.

No artificial expiry date may be imposed.

Custody must be traceable to:

- Sales;
- SalesLine;
- Product;
- Customer;
- Warehouse;
- quantity;
- ownership transition event;
- release history.

A Warehouse is a location, not an owner. Physical Warehouse reports and ownership/custody reports are separate reporting questions.

### F.1 Multiple owners

A Warehouse may contain simultaneously:

```text
Company-owned stock
Ahmad-owned custody stock
Mahmoud-owned custody stock
Karim-owned custody stock
```

This is represented above the protected physical inventory identity, not by changing StockMovement.

**Classification:** `USER DIRECTIVE + ARCHITECTURAL PROPOSAL`

---

## G. Warehouse Contract

A Warehouse is a physical location used by:

- physical inventory;
- SalesLine sourcing;
- custody location;
- release authorization;
- physical issue.

Warehouse ownership is not implied by the Warehouse master. A Warehouse must not be treated as an ownership boundary.

Warehouse selection is mandatory at SalesLine level. The Sales header must not override a line’s Warehouse.

**Classification:** `USER DIRECTIVE`

---

## H. Multi-Warehouse Sales

A Sales Invoice may contain any number of lines and any number of Warehouses:

```text
Sales Invoice S-001
  ├── Line 1 → Oil 10L → Warehouse Umar Rahimi → 100 barrels
  ├── Line 2 → Liquid Oil 5L → Warehouse Mohib → 50 cartons
  └── Line 3 → Sugar → Warehouse Sadaqat → 20 sacks
```

Every ReleaseLine, fulfillment allocation, custody record, and physical issue reference must preserve the originating SalesLine.

Operational grouping by Warehouse is allowed for release work and printing. Grouping must not destroy SalesLine identity.

**Classification:** `USER DIRECTIVE`

---

## I. Warehouse Release Authorization

### I.1 Meaning

The business term “check” means a warehouse authorization. It is not:

- a bank cheque;
- a payment instrument;
- financial settlement;
- cash.

The standardized conceptual name is:

```text
Warehouse Release Authorization
```

A later implementation may display “Warehouse Issue Check” as an operational label if approved.

### I.2 Structure

```text
Sales
  ↓
Warehouse Release Authorization
  ↓
Release Lines
```

Each ReleaseLine preserves:

- SalesLine;
- Product;
- Warehouse;
- quantity;
- unit;
- release status;
- source Sale;
- source customer.

A parent authorization may contain Warehouse-grouped lines. A multi-Warehouse invoice may therefore produce multiple operational sheets while retaining one traceable parent transaction.

### I.3 Authorization versus physical release

```text
Printing authorization ≠ authorization itself
Authorization ≠ physical release
Physical release ≠ Type A ownership transfer
```

For Type B only:

```text
Authorization after actual fulfillment → physical-goods ownership transfer
```

For both types, physical release remains the warehouse operation that may create the approved physical inventory event.

### I.4 Integrity

The future contract must reject:

- Release > Sold;
- Release > authorized quantity;
- Release > available/fulfilled quantity under the approved source rule;
- wrong Product;
- wrong Warehouse;
- wrong SalesLine;
- duplicate release;
- release against invalidated/reversed Sale;
- release after immutable facts were edited.

**Classification:** `USER DIRECTIVE + ARCHITECTURAL PROPOSAL`

---

## J. Physical Release

Physical Release means the actual warehouse operation in which goods leave company physical custody or otherwise undergo the approved physical issue event.

It is not:

- Sale finalization;
- payment;
- printing;
- authorization alone;
- allocation alone.

When physical inventory is actually issued, the future implementation must reuse the protected `issue_stock()` and existing StockMovement/idempotency/concurrency rules. It must not create a second inventory path.

For Type A:

```text
Finalization → ownership
Physical Release → physical handover / issue
```

For Type B:

```text
Authorization after actual fulfillment → physical-goods ownership
Physical Release → physical handover / issue
```

**Classification:** `USER DIRECTIVE + REPOSITORY FACT for reuse of issue_stock()`

---

## K. Fulfillment Allocation

Fulfillment is the link between a Sale obligation and actual obtained goods. It is not the same as:

- Purchase receipt;
- inventory availability;
- ownership;
- custody;
- physical release.

Required Type B chain:

```text
Future Sale
  → Purchase
  → PurchaseLine / receipt
  → receive_stock()
  → actual Product + Warehouse inventory and cost
  → allocation to SalesLine
  → Warehouse Release Authorization
  → physical release
```

Allocation must identify an actual source quantity and must prevent:

- double allocation;
- over-allocation;
- over-fulfillment;
- allocation from nonexistent stock;
- one physical quantity allocated to multiple obligations;
- fabricated StockMovement.

For Type B, ownership of actual physical goods does not transfer at mere Purchase receipt or mere allocation. It transfers at the subsequent authoritative Release Authorization, according to the explicit Future Sale rule.

**Classification:** `USER DIRECTIVE`

---

## L. Quantity Model

The contract distinguishes six quantities.

| Quantity | Meaning | Authority / nature |
|---|---|---|
| Sold / Contracted | Quantity fixed by finalized SalesLine | Sales fact; immutable after finalization |
| Physical Available | Actual Product + Warehouse stock | Inventory-derived from StockMovement/AVCO |
| Allocated / Fulfilled | Actual obtained quantity assigned to a SalesLine | Fulfillment event-derived |
| Released | Quantity physically released | Release event history; cumulative derived |
| Customer Custody | Actual customer-owned goods still physically held by company | Ownership/custody event-derived |
| Remaining Fulfillment | Contracted quantity not yet allocated/fulfilled | Sales/fulfillment-derived |

### L.1 Type A quantity example

Assuming 2,000 goods were actually obtained/available:

```text
Sold = 2,000
Allocated/Fulfilled = 2,000
Release #1 = 200
Released cumulative = 200
Customer Custody = 1,800
Remaining Fulfillment = 0
```

After another 300:

```text
Released cumulative = 500
Customer Custody = 1,500
```

### L.2 Type B quantity example

At finalization:

```text
Contracted = 5,000
Physical Available = 0
Allocated/Fulfilled = 0
Released = 0
Customer Custody = 0
Remaining Fulfillment = 5,000
```

After Purchase and actual receipt, but before allocation:

```text
Physical Available = actual received quantity
Allocated/Fulfilled = 0
Remaining Fulfillment = 5,000
```

After allocation of 5,000:

```text
Allocated/Fulfilled = 5,000
Remaining Fulfillment = 0
Released = 0
Customer Custody = 0 until the Type B ownership authorization occurs
```

After the authoritative Warehouse Release Authorization:

```text
Allocated/Fulfilled = 5,000
Customer physical ownership = 5,000
Customer Custody = 5,000 if still physically held by company
```

After physical release:

```text
Released = 5,000
Customer Custody = 0
```

No single mutable field may represent all six meanings.

**Classification:** `USER DIRECTIVE + ARCHITECTURAL PROPOSAL`

---

## M. Payment Boundary

Sales may establish a commercial receivable using the existing Party Ledger/accounting foundation, subject to the unresolved financial Sales rules.

Payment remains a separate later domain:

```text
Sale → receivable/payment state → later Payment/Settlement
```

Payment may be:

- full;
- partial;
- zero;
- credit;
- later settled.

Payment does not trigger Type A ownership and does not trigger Type B physical-goods ownership.

No Payment Engine is created inside Sales.

**Classification:** `USER DIRECTIVE + REPOSITORY FACT`

---

## N. Accounting Boundary

Existing accounts are repository facts:

```text
1310 Trade Receivables
4110 Wholesale Sales
4120 Retail Sales
4200 Sales Returns
5100 COGS
```

Their existence does not by itself define Sales posting rules.

| Event | Inventory | Ownership | Receivable | Revenue | COGS |
|---|---|---|---|---|---|
| Type A finalization | Must not fabricate stock; exact valuation event unresolved | Buyer owns actual goods | May create receivable if financial contract approves | Unresolved timing | Unresolved timing |
| Type B finalization | No StockMovement; no physical stock claimed | Commercial entitlement only; no physical-goods ownership | May create commercial receivable if approved | Unresolved timing | Unresolved |
| Purchase/receipt for Type B | Actual inventory enters through Purchase and `receive_stock()` | Company holds physical goods before Type B authorization | Purchase payable per Purchase contract | None from Sale | Purchase/AVCO cost established |
| Fulfillment allocation | Uses actual inventory; no new fake stock | No Type B ownership transfer yet | None directly | None directly | Allocation treatment unresolved |
| Type B Release Authorization | No physical issue merely from authorization | Physical-goods ownership transfers for actual allocated quantity | None directly | None directly | Unresolved |
| Physical Release | Reuse `issue_stock()` only for actual issue | Ownership already established according to type | None directly | None directly | Timing unresolved |
| Payment | None directly | None | Settles receivable under Payment contract | None | None |
| Customer custody | Physically held goods remain location-relevant | Customer owns goods | None | None | Custody valuation/reporting unresolved |
| Customer → Company | Purchase receipt path | Company ownership under Purchase | Payable as applicable | None | Purchase/AVCO |
| Sales Return | Existing return primitive may reverse physical issue | Separate future ownership/reversal rule | Payment-state dependent | `4200` possible but not approved here | Original-cost treatment unresolved |

No journal entry is selected by this table.

**Classification:** `REPOSITORY FACT + UNRESOLVED DECISION`

---

## O. Revenue Account Selection

The repository contains both:

```text
4110 Wholesale Sales
4120 Retail Sales
```

Tests and accounting helpers demonstrate valid usage of both accounts, but no authoritative Sales business selector was found.

The minimum unresolved question is:

```text
What business attribute selects 4110 versus 4120?
```

A possible proposal is:

```text
WHOLESALE → 4110
RETAIL    → 4120
```

This is not selected by this report. It must not be chosen from quantity, customer name, price, code convenience, or personal judgment.

```text
FINANCIAL SALES IMPLEMENTATION = BLOCKED
```

**Classification:** `UNRESOLVED — ACCOUNTING DECISION REQUIRED`

---

## P. Revenue Timing

The repository does not establish whether revenue occurs at:

- Type A Sale finalization;
- Type B Sale finalization;
- Type B Release Authorization;
- physical issue;
- fulfillment;
- another approved event.

Ownership alone does not decide revenue timing. `issue_stock()` alone does not decide revenue timing.

```text
FINANCIAL SALES IMPLEMENTATION = BLOCKED
```

**Classification:** `UNRESOLVED — ACCOUNTING DECISION REQUIRED`

---

## Q. COGS / Inventory Timing

The following remain unresolved:

- when company inventory is reduced for Type A;
- whether delayed Type A custody requires valuation reclassification;
- when COGS is recognized;
- whether Type B COGS is tied to fulfillment, authorization, physical issue, or another event;
- how AVCO cost is preserved through allocation;
- how delayed release affects financial inventory reporting.

No AVCO modification, journal, new account, or cost engine is proposed.

```text
FINANCIAL SALES IMPLEMENTATION = BLOCKED
```

**Classification:** `UNRESOLVED — ACCOUNTING DECISION REQUIRED`

---

## R. Customer-Owned Custody Accounting

The operational distinction is resolved:

```text
Customer-owned custody ≠ company-owned inventory
```

The financial treatment is not resolved by repository evidence. Alternatives requiring explicit accounting approval are:

1. exclude customer-owned custody from company-owned inventory valuation while retaining physical location reporting;
2. use an approved reclassification treatment;
3. represent it through an entitlement/custody reporting layer with a separately approved financial treatment;
4. another explicitly approved policy.

This report does not choose an account, journal, or valuation policy.

**Classification:** `UNRESOLVED — ACCOUNTING DECISION REQUIRED`

---

## S. Sales Return Boundary

Sales Return is a separate future contract. A complete Sales Return must identify:

- original Sale;
- original SalesLine;
- Sale Type;
- released quantity;
- custody quantity;
- ownership state;
- payment state;
- original inventory cost;
- financial reversal;
- COGS treatment.

Existing inventory return primitives do not prove that the complete Sales Return contract exists.

A customer selling goods to the company is not a Sales Return; it is a new Purchase.

**Classification:** `OUT OF SCOPE / UNRESOLVED FUTURE CONTRACT`

---

## T. Customer-to-Company Purchase Boundary

```text
Customer → Company = NEW PURCHASE
```

The transaction follows the Purchase foundation, including PurchaseLine, receipt, actual cost, inventory history, and payable treatment as applicable.

It is not converted into Sales Return because the same Product may have been sold earlier.

**Classification:** `USER DIRECTIVE`

---

## U. Cancellation / Reversal

No edit-based rollback is permitted after finalization.

### U.1 Before physical events

A future approved cancellation/reversal contract must define the effect on:

- Type A ownership;
- Type B commercial entitlement;
- receivable;
- fulfillment obligation;
- custody;
- pending authorization.

### U.2 After partial release

Cancellation cannot erase:

- release history;
- physical issue history;
- customer custody history;
- journal history.

### U.3 After full release

A controlled Return/Reversal contract is required.

No cancellation state, journal, or ownership reversal is invented here.

**Classification:** `UNRESOLVED DECISION / PROTECTED IMMUTABILITY PRINCIPLE`

---

## V. Idempotency

The final implementation must use distinct idempotency boundaries for:

1. Sales finalization;
2. financial Sales posting, if approved;
3. Warehouse Release Authorization;
4. physical release / `issue_stock()`;
5. fulfillment allocation;
6. later Payment;
7. later Sales Return.

Duplicate requests must not create:

- duplicate journal entries;
- duplicate StockMovement;
- duplicate Release events;
- duplicate allocation;
- duplicate custody quantity.

Exact key/fingerprint formats must be taken from the existing accounting and inventory patterns during implementation. This report does not invent key names.

**Classification:** `REPOSITORY FACT + ARCHITECTURAL PROPOSAL`

---

## W. Printing

Printing is:

```text
Operational
Non-financial
Non-inventory
Non-ownership-changing
Idempotent
```

A multi-Warehouse Sale may produce:

```text
Warehouse A sheet
Warehouse B sheet
Warehouse C sheet
```

Each sheet must preserve independent Product/quantity/unit/SalesLine identity.

Printing twice must not:

- release stock;
- change Type A ownership;
- trigger Type B ownership;
- change custody;
- create a journal;
- create StockMovement;
- create fulfillment allocation.

Printing is a projection of authorization data, not a business event.

**Classification:** `USER DIRECTIVE`

---

## X. API / Service Boundary

Conceptual only; nothing is implemented.

The future service boundary should separate:

```text
Sales Draft / Finalization
Ownership or Commercial Entitlement
Fulfillment Allocation
Warehouse Release Authorization
Physical Release / issue_stock()
Financial Posting
Payment
Sales Return
```

The Sales layer must call/reuse existing accounting, Party Ledger, money, fiscal, audit, idempotency, and inventory primitives. It must not duplicate them.

A future API must not expose a single operation that silently performs all of:

```text
Sale + Payment + Ownership + Allocation + Authorization + Physical Issue
```

**Classification:** `ARCHITECTURAL PROPOSAL`

---

## Y. Security / Integrity / Authorization

Conceptual requirements:

- only authorized Sales users may finalize a Draft;
- finalized commercial facts are immutable;
- only authorized Warehouse users may issue against an approved Release Authorization;
- authorization must identify customer, invoice, SalesLine, Product, Warehouse, quantity, and unit;
- a user must not authorize or issue a wrong Warehouse/Product/SalesLine combination;
- printing permission must not imply release permission;
- financial posting permission must not imply Warehouse issue permission;
- duplicate requests must be idempotent;
- invalidated/reversed Sales must block new release;
- audit history must preserve who finalized, authorized, printed, allocated, and physically released.

Exact role names and permission implementation are not selected here.

**Classification:** `ARCHITECTURAL PROPOSAL grounded in protected audit/integrity conventions`

---

## Z. Test Contract

No tests are written in this task. Future implementation must include the following categories.

### Z.1 Ordinary Sale

- cash Sale;
- credit Sale;
- zero-payment finalized Sale;
- partial payment;
- finalization and buyer ownership;
- custody after finalization;
- zero, partial, multiple, and full release;
- payment does not alter ownership.

### Z.2 Multi-Warehouse

- multiple SalesLines;
- multiple Warehouses;
- same Product from different Warehouses;
- Warehouse preserved per SalesLine;
- ReleaseLine preserves SalesLine identity;
- Warehouse grouping does not merge lines incorrectly.

### Z.3 Customer Custody

- 2,000 sold;
- 200 released;
- 1,800 custody;
- another 300 released;
- 1,500 custody;
- no artificial custody expiry;
- multiple customers in one Warehouse;
- company-owned and customer-owned physical coexistence.

### Z.4 Future Sale

- Sale with zero stock;
- no fabricated StockMovement;
- commercial entitlement without physical ownership;
- later Purchase;
- actual receipt and cost;
- allocation to SalesLine;
- authorization transfers physical-goods ownership under Type B rule;
- custody after authorization if goods remain held;
- physical release after authorization.

### Z.5 Integrity

- over-release;
- release above authorization;
- release above available/fulfilled source;
- wrong Warehouse;
- wrong Product;
- wrong SalesLine;
- duplicate release;
- duplicate allocation;
- over-allocation;
- duplicate finalization;
- finalized line mutation;
- invalid Sale release;
- cancellation after release;
- one Purchase quantity allocated twice.

### Z.6 Accounting

Only after accounting decisions are approved:

- receivable;
- approved revenue account;
- revenue timing;
- COGS;
- inventory reduction;
- custody treatment;
- FX and rate date;
- reversal;
- Sales Return.

### Z.7 PostgreSQL

Concurrency and idempotency-sensitive implementation tests must include PostgreSQL verification. SQLite-only results are insufficient to establish PostgreSQL concurrency behavior.

**Classification:** `ARCHITECTURAL PROPOSAL / FUTURE TEST CONTRACT`

---

## AA. Adversarial Scenarios

| # | Challenge | Required result |
|---:|---|---|
| 1 | Unpaid Type A Sale | Buyer owns goods after finalization. |
| 2 | Physical location treated as ownership | Must be rejected; Warehouse is location only. |
| 3 | Multiple owners in one Warehouse | Must remain representable without changing StockMovement identity. |
| 4 | Indefinite Type A custody | Must remain valid without artificial expiry. |
| 5 | Type B Sale with zero stock | Commercial entitlement only; no fake inventory or physical ownership. |
| 6 | Type B allocation before authorization | Allocation exists; physical ownership has not yet transferred. |
| 7 | Type B authorization after actual fulfillment | Physical-goods ownership transfers for allocated quantity. |
| 8 | Same source stock allocated twice | Second allocation rejected/idempotently resolved. |
| 9 | Release above sold | Rejected. |
| 10 | Release above fulfilled/available | Rejected under approved source constraint. |
| 11 | Header Warehouse overriding line Warehouse | Prohibited. |
| 12 | Printing twice | No release, journal, StockMovement, allocation, or ownership change. |
| 13 | Customer sells to company | New Purchase, not Sales Return. |
| 14 | Second Payment Engine inside Sales | Prohibited. |
| 15 | Sales modifies Product + Warehouse identity | Prohibited. |
| 16 | COGS inferred from `issue_stock()` | Prohibited without accounting decision. |
| 17 | Revenue inferred from ownership | Prohibited without accounting decision. |
| 18 | `4110`/`4120` selected by convenience | Prohibited. |
| 19 | Custody account invented | Prohibited. |
| 20 | Finalized Sale mutated | Rejected; controlled correction only. |
| 21 | Cancellation erases release history | Prohibited. |
| 22 | Future Purchase allocated to multiple Sales | Prohibited. |
| 23 | Physical availability confused with entitlement | Must remain separate. |
| 24 | Customer-owned goods reported as company-owned without policy | Blocked pending accounting decision. |

Any implementation that fails one of these is not contract-conforming.

**Classification:** `FUTURE TEST CONTRACT`

---

## AB. Decision Matrix

| ID | Decision | Business Rule | Repository Evidence | Status | Consequence | Implementation Gate |
|---|---|---|---|---|---|---|
| PH8-001 | Ownership transfer | Type A finalization transfers ownership; Type B authorization after actual fulfillment transfers physical-goods ownership | No Sales implementation; explicit user rules | RESOLVED | Two ownership triggers by Sale Type | Must model Sale Type distinction |
| PH8-002 | Custody | Customer-owned actual goods may remain in company Warehouse indefinitely | No custody domain exists | RESOLVED BUSINESS / ACCOUNTING OPEN | Independent custody history required | Custody accounting approval |
| PH8-003 | Sale vs Release | Separate concepts | `issue_stock()` is physical primitive; no release model | RESOLVED | Release authorization and physical release separate | Required boundary |
| PH8-004 | Payment boundary | Payment separate from Sale and ownership | Payments placeholder; Party Ledger exists | RESOLVED | No Payment Engine in Sales | Later Payment contract |
| PH8-005 | 4110 vs 4120 | Business selector not supplied | Both accounts exist; tests use both | UNRESOLVED — ACCOUNTING DECISION REQUIRED | Revenue posting cannot be finalized | Financial Sales blocked |
| PH8-006 | Partial Release | Multiple release events and cumulative quantity | `SALES_ISSUE` primitive exists | RESOLVED | Event-based ReleaseLines | Bounds/idempotency required |
| PH8-007 | Sales Return | Separate future contract; customer-to-company is Purchase | Inventory return primitives only | OUT OF SCOPE / UNRESOLVED FUTURE CONTRACT | Defer integrated Return | No Return implementation |
| PH8-008 | Phase 7 baseline | Registration discrepancy must be qualified | Working tree has `purchases`; HEAD does not | BLOCKED — BASELINE EVIDENCE | Baseline not unambiguously reproducible | Resolve before implementation |
| PH8-009 | GitHub baseline | Verify if remote exists | No usable remote configured | BLOCKED — BASELINE EVIDENCE | No external verification | Provide authoritative remote |
| PH8-010 | Company inventory vs custody | Customer custody is not company-owned inventory | No accounting custody contract | UNRESOLVED — ACCOUNTING DECISION REQUIRED | Reporting/valuation policy required | Financial Sales blocked |
| PH8-011 | Payment vs ownership | Payment never triggers ownership | Explicit user rule | RESOLVED | Unpaid/partial cases supported | Must be tested |
| PH8-012 | Release vs ownership | Type A release does not trigger ownership; Type B authorization does | Explicit two-mode rule | RESOLVED | Trigger depends on Sale Type | Must not collapse modes |
| PH8-013 | Warehouse on SalesLine | Mandatory line-level Warehouse | Product/Warehouse inventory foundation | RESOLVED | Header-only Warehouse prohibited | Foundation requirement |
| PH8-014 | Multi-Warehouse | One invoice may span Warehouses | No Sales model; user rule | RESOLVED | Group operationally, preserve line identity | Required |
| PH8-015 | Release Authorization | Warehouse needs authoritative instruction | No existing document | PROPOSED — USER APPROVAL REQUIRED | Parent plus ReleaseLines | Approve document model |
| PH8-016 | Printing | Warehouse-specific, non-event print projection | No printing implementation | PROPOSED — USER APPROVAL REQUIRED | Printing cannot release | Approve print contract |
| PH8-017 | Future Sale | No stock may exist at finalization without fake inventory | Inventory Product + Warehouse | RESOLVED | Commercial obligation separate from stock | Sale Type required |
| PH8-018 | Future fulfillment | Purchase/receipt precedes allocation | Purchase and `receive_stock()` exist | RESOLVED | Actual source inventory required | Allocation contract |
| PH8-019 | Customer-to-company Purchase | Always new Purchase unless explicitly true Return | Purchase and Return primitives separate | RESOLVED | No Return shortcut | Purchase boundary |
| PH8-020 | Fulfillment allocation | No double/over allocation or fabrication | No allocation implementation | PROPOSED — USER APPROVAL REQUIRED | Source quantities and locks required | Define allocation contract |
| PH8-021 | Architecture | Preserve physical Product + Warehouse; independent custody/entitlement | Phase 6 protected identity | PROPOSED — USER APPROVAL REQUIRED | Minimal composition | Approve architecture |
| PH8-022 | Lifecycle | DRAFT → FINALIZED; do not conflate financial posting | Purchase immutability precedent; no Sales lifecycle | PROPOSED — USER APPROVAL REQUIRED | Separate commercial and accounting state if needed | Approve lifecycle |
| PH8-023 | Immutability | Finalized commercial facts immutable | Existing posted-history principles | RESOLVED PRINCIPLE | Controlled correction only | Reuse conventions |
| PH8-024 | Idempotency | Separate boundaries for finalization, release, issue, allocation | Existing accounting/inventory idempotency | PROPOSED — USER APPROVAL REQUIRED | No duplicate business events | Define keys during implementation |
| PH8-025 | Custody accounting | No silent valuation/journal choice | No custody accounting evidence | UNRESOLVED — ACCOUNTING DECISION REQUIRED | Financial implementation blocked | Explicit policy required |
| PH8-026 | Revenue/COGS timing | Event timing not established | Accounts/primitives do not select event | UNRESOLVED — ACCOUNTING DECISION REQUIRED | Financial implementation blocked | Accounting approval |
| PH8-027 | Money/FX | Reuse existing Money/Currency/Rate/rounding | Existing currency, journal, FX services | PROPOSED — USER APPROVAL REQUIRED | No duplicate engine | Inspect exact fields during implementation |
| PH8-028 | Cancellation/reversal | No edit rollback; history preserved | Existing reversal/immutability principles | UNRESOLVED — USER/ACCOUNTING DECISION REQUIRED | Controlled lifecycle required | Define before release |
| PH8-029 | Type B ownership trigger | Authorization after actual fulfillment, not finalization/receipt/allocation | Explicit latest user rule | RESOLVED | Future mode has distinct physical ownership event | Must be explicit |
| PH8-030 | Type A custody timing | Finalization transfers ownership; later release reduces custody | Explicit latest user rule | RESOLVED | Custody begins for available goods after finalization | Must not depend on payment |

---

## AC. Implementation Dependency Graph

The validated dependency direction is:

```text
Baseline Qualification
        ↓
Sales Commercial Contract + Sale Type
        ↓
Type A Ownership / Type B Commercial Entitlement
        ↓
Custody and Fulfillment Contract
        ↓
Financial Accounting Contract
        ↓
Warehouse Release Authorization
        ↓
Fulfillment Allocation for Type B
        ↓
Physical Issue Integration
        ↓
Future Fulfillment Operationalization
        ↓
Sales Return
        ↓
Payment / Settlement
```

### Dependency observations

- Sale Type must exist before ownership semantics can be implemented.
- Accounting approval must exist before financial posting, revenue, COGS, or inventory reduction.
- Fulfillment allocation must exist before Type B authorization can be safely issued.
- Release authorization must be separate from printing and physical issue.
- Sales Return depends on ownership, custody, release, payment, and original cost.
- Payment does not belong before the ownership contract; it is not a prerequisite for ownership.

This graph is an implementation dependency proposal, not an implementation action.

**Classification:** `ARCHITECTURAL PROPOSAL`

---

## AD. Explicit Blockers

### AD.1 Accounting blockers

Financial Sales implementation is blocked until the following are approved:

1. `4110` versus `4120` selection rule;
2. revenue timing for Type A and Type B;
3. COGS timing;
4. company inventory reduction timing;
5. custody valuation and reporting treatment;
6. Type B authorization/allocation accounting treatment;
7. cancellation/reversal financial treatment;
8. Sales Return accounting treatment.

### AD.2 Baseline blockers

Implementation baseline is blocked until:

1. the `purchases` registration discrepancy is qualified;
2. the approved Phase 7 snapshot is identified;
3. GitHub/main status is verified if an authoritative remote becomes available.

### AD.3 Operational contract approvals

The following are proposed rather than silently approved:

- Warehouse Release Authorization parent/line structure;
- printing projection and grouping;
- fulfillment allocation source/locking contract;
- exact Sale Type representation;
- exact commercial/accounting state separation.

---

## AE. Final Implementation Readiness Assessment

| Requirement | Classification |
|---|---|
| Type A Available/Ordinary Sale business semantics | RESOLVED |
| Type B Future/Forward Sale business semantics | RESOLVED |
| Type A ownership trigger | RESOLVED |
| Type B physical ownership trigger | RESOLVED |
| Payment independent from ownership | RESOLVED |
| Customer custody business meaning | RESOLVED |
| Open-ended custody | RESOLVED |
| Multiple owners in one Warehouse | RESOLVED |
| Warehouse on SalesLine | RESOLVED |
| Multi-Warehouse invoice | RESOLVED |
| Sale versus Release | RESOLVED |
| Release history and partial release | RESOLVED |
| Future Purchase before fulfillment | RESOLVED |
| Customer → Company boundary | RESOLVED |
| Physical inventory identity | RESOLVED / PROTECTED |
| Release Authorization shape | PROPOSED — USER APPROVAL REQUIRED |
| Printing contract | PROPOSED — USER APPROVAL REQUIRED |
| Fulfillment allocation implementation contract | PROPOSED — USER APPROVAL REQUIRED |
| Sale Type representation | PROPOSED — USER APPROVAL REQUIRED |
| Sales lifecycle implementation mapping | PROPOSED — USER APPROVAL REQUIRED |
| Idempotency key format | PROPOSED — USER APPROVAL REQUIRED |
| `4110` versus `4120` | UNRESOLVED — ACCOUNTING DECISION REQUIRED |
| Revenue timing | UNRESOLVED — ACCOUNTING DECISION REQUIRED |
| COGS/inventory timing | UNRESOLVED — ACCOUNTING DECISION REQUIRED |
| Custody accounting/valuation | UNRESOLVED — ACCOUNTING DECISION REQUIRED |
| Cancellation/reversal | UNRESOLVED — USER/ACCOUNTING DECISION REQUIRED |
| Phase 7 clean baseline | BLOCKED — BASELINE EVIDENCE |
| GitHub baseline | BLOCKED — BASELINE EVIDENCE |
| Payment implementation | OUT OF SCOPE |
| Sales Return implementation | OUT OF SCOPE |
| Frontend/printing implementation | OUT OF SCOPE |

### AE.1 Stage 8.1 boundary after approval

The smallest candidate Stage 8.1 scope is:

```text
Sales
SalesLine
Customer Party reference
Currency
Exchange Rate
Rate Date
Product
Warehouse per SalesLine
Quantity
Unit Price
Discount
Totals
Sale Type
DRAFT
FINALIZED
Audit
Idempotency
Validation
```

This candidate remains gated by baseline qualification and the required financial decisions if Stage 8.1 includes financial finalization/posting.

Explicitly exclude unless separately approved:

- Payment Engine;
- physical issue;
- Sales Return;
- custody accounting;
- advanced future allocation;
- delivery;
- frontend;
- printing implementation;
- reporting implementation.

### AE.2 Overall assessment

The business distinction between Type A and Type B is now explicit and reconciled. The contract is not financially implementation-ready because accounting decisions and baseline evidence remain blocked.

```text
BUSINESS CONTRACT: RESOLVED
ARCHITECTURAL DIRECTION: PROPOSED — USER APPROVAL REQUIRED
FINANCIAL SALES CONTRACT: BLOCKED — ACCOUNTING DECISIONS REQUIRED
IMPLEMENTATION BASELINE: BLOCKED — BASELINE EVIDENCE REQUIRED
```

---

## AF. STOP

```text
PHASE 8 FINAL CONTRACT LOCK

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

ORDINARY SALE CONTRACT: RESOLVED
FUTURE SALE CONTRACT: RESOLVED
OWNERSHIP CONTRACT: RESOLVED
CUSTODY CONTRACT: RESOLVED
RELEASE CONTRACT: PROPOSED — USER APPROVAL REQUIRED
FULFILLMENT CONTRACT: PROPOSED — USER APPROVAL REQUIRED
ACCOUNTING CONTRACT: BLOCKED — ACCOUNTING DECISIONS REQUIRED
BASELINE CONTRACT: BLOCKED — BASELINE EVIDENCE REQUIRED

STATUS:
WAITING FOR USER REVIEW AND APPROVAL
```
