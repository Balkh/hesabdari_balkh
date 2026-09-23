# Phase 8 — Master Contract Lock

**Repository:** `Balkh/hesabdari_balkh`  
**Working branch:** `phase/4`  
**Inspected HEAD:** `692e2735234e2d123625bc2dc9a2f15be9c0e564`  
**Mode:** Contract lock / discovery only  
**Implementation:** Strictly forbidden and not performed

All conclusions below are labelled as `USER DIRECTIVE`, `REPOSITORY FACT`, `TEST EVIDENCE`, `ARCHITECTURAL PROPOSAL`, `UNRESOLVED DECISION`, or `BLOCKER`.

---

## 1. Executive Contract Status

The business contract is resolved for the two mandatory Sales modes:

```text
TYPE A — AVAILABLE / ORDINARY SALE
Finalization → buyer ownership → custody or release

TYPE B — FUTURE / FORWARD SALE
Finalization → commercial entitlement only
Purchase/receipt → actual inventory
Allocation → identifies actual goods
Release Authorization → physical-goods ownership
Physical Release → handover / issue
```

The contract is **not financially implementation-ready** because the repository does not establish:

- the `4110` versus `4120` selector;
- revenue timing;
- COGS and inventory-reduction timing;
- customer-custody valuation/accounting;
- cancellation/reversal accounting;
- a clean/reproducible Phase 7 baseline;
- an independently verified GitHub baseline.

**Classification:** `USER DIRECTIVE + REPOSITORY FACT + BLOCKER`

---

## 2. Repository Baseline

### 2.1 Current state

```text
Branch: phase/4
HEAD:   692e2735234e2d123625bc2dc9a2f15be9c0e564
HEAD:   freeze phase 7 purchase workflow
```

**Classification:** `REPOSITORY FACT`

### 2.2 Working tree

The inspected working tree contains:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_8_FINAL_CONTRACT_LOCK.md
?? docs/phase-reports/PHASE_8_FINAL_SALES_CONTRACT_RESOLUTION.md
?? docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_CUSTODY_DISCOVERY.md
?? docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_REPORT.md
```

The tracked settings diff is exactly:

```diff
- "party_ledger", "inventory",
+ "party_ledger", "inventory", "purchases",
```

The other tracked change is documentation-only in the Phase 6.6 evidence file. No dirty file was cleaned, reset, or discarded.

**Classification:** `REPOSITORY FACT`

### 2.3 Phase 7 registration discrepancy

The working tree registers `purchases` in `INSTALLED_APPS`; the inspected HEAD does not. The evidence establishes an uncommitted Phase 7 integration difference. It does not establish whether the frozen commit is independently reproducible as the approved Purchase runtime baseline.

```text
PHASE 7 BASELINE: BLOCKED — BASELINE EVIDENCE
```

**Classification:** `REPOSITORY FACT + BLOCKER`

### 2.4 Remote

No usable Git remote URL is configured. Therefore:

```text
GITHUB BASELINE = NOT VERIFIED
REMOTE VERIFICATION = BLOCKED
```

No claim is made about GitHub `main`, merges, or remote Phase 7 state.

**Classification:** `REPOSITORY FACT + BLOCKER`

### 2.5 Existing Phase 8 material inspected

```text
docs/phase-reports/PHASE_8_FINAL_CONTRACT_LOCK.md
docs/phase-reports/PHASE_8_FINAL_SALES_CONTRACT_RESOLUTION.md
docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_CUSTODY_DISCOVERY.md
docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_REPORT.md
```

They were reconciled against the current user directive. This report supersedes earlier wording where the explicit Type A/Type B distinction is more specific.

---

## 3. Protected Contracts

The following remain protected:

- Phase 0 domain/accounting contracts;
- `JournalEntry`, `JournalLine`, `post_journal()`;
- posted-history immutability and reversal conventions;
- Money, precision, rounding, Currency, Exchange Rate, Rate Date;
- Fiscal Period validation;
- Party, roles, PartyLedgerAttribution, receivable/payable derivation;
- Product and Warehouse;
- `StockMovement`;
- `Product + Warehouse` physical stock identity;
- `receive_stock()` and `issue_stock()`;
- AVCO and inventory cost history;
- inventory idempotency and concurrency rules;
- Purchase, PurchaseLine, Purchase posting, receipt, and immutability;
- existing return primitives;
- audit conventions.

The following are prohibited:

```text
StockMovement(Product + Warehouse + Owner)
Second inventory engine
Second AVCO engine
Parallel stock ledger
Duplicate Party, Ledger, Money, Currency, Audit, or Idempotency framework
```

**Classification:** `USER DIRECTIVE + REPOSITORY FACT`

---

## 4. Type A — Available/Ordinary Sale

### Definition

Physical goods exist and are available/obtained when the Sale is finalized.

```text
Finalization → buyer ownership
             → immediate collection OR customer custody
             → later partial/full release
```

### Rules

- ownership trigger is Sales Finalization;
- payment does not trigger ownership;
- physical release does not trigger ownership;
- Warehouse location does not determine ownership;
- zero-payment, credit, and partially paid Sales are valid;
- custody may be open-ended;
- multiple releases are preserved as events;
- customer-owned custody may coexist with company-owned stock.

**Classification:** `USER DIRECTIVE`

---

## 5. Type B — Future/Forward Sale

### Definition

A commercial Sale/obligation is finalized before the goods exist in company inventory.

At finalization:

```text
Commercial entitlement = yes
Physical inventory = no
Physical custody = no
Physical ownership of nonexistent goods = no
Physical release = no
```

The required chain is:

```text
Future Sale
  → Purchase
  → actual receipt through receive_stock()
  → actual Product + Warehouse inventory and cost
  → fulfillment allocation
  → Warehouse Release Authorization
  → physical release
```

### Type B ownership

```text
Sale Finalization = commercial entitlement
Purchase/Receipt = actual company inventory
Allocation = identifies actual goods
Warehouse Release Authorization = physical-goods ownership transfer
Physical Release = physical handover / inventory issue
```

Ownership does not transfer merely at payment, Purchase receipt, or allocation. It transfers at the authoritative Release Authorization after actual goods are obtained and allocated.

If authorized goods remain in the company Warehouse, they become customer-owned custody goods. If physically released, custody decreases accordingly.

No StockMovement, AVCO, custody, or physical ownership is fabricated at Type B finalization.

**Classification:** `USER DIRECTIVE`

---

## 6. Ownership Contract

### Type A

```text
Sales Finalization → buyer owns actual goods
```

### Type B

```text
Sales Finalization → commercial entitlement only
Release Authorization after actual fulfillment → physical-goods ownership
```

### Universal separation

```text
Payment ≠ ownership trigger
Warehouse ≠ owner
Physical location ≠ economic ownership
Printing ≠ ownership
Physical release ≠ Type A ownership trigger
```

Corrections after finalization must not mutate commercial history. The exact cancellation/reversal policy remains unresolved.

**Classification:** `USER DIRECTIVE + UNRESOLVED DECISION for reversal policy`

---

## 7. Custody Contract

Customer custody means:

```text
Customer owns actual goods
Company physically holds those goods
Collection date is unknown, later, or open-ended
```

Custody must be traceable to:

```text
Customer
Sale
SalesLine
Product
Warehouse
Ownership event
Release history
Quantity
```

For Type A:

```text
2,000 sold → 200 released → 1,800 customer custody
          → 300 later released → 1,500 customer custody
```

For Type B, custody begins only after actual goods are allocated and Type B Release Authorization transfers physical-goods ownership. It does not begin at forward-sale finalization.

No artificial expiry date is permitted.

**Classification:** `USER DIRECTIVE`

---

## 8. SalesLine / Warehouse Contract

Warehouse is mandatory on every SalesLine. A header-only Warehouse is prohibited.

```text
Sale
  ├── Line 1 → Product A → Warehouse A
  ├── Line 2 → Product B → Warehouse B
  └── Line 3 → Product C → Warehouse C
```

The SalesLine Warehouse identity must survive through:

```text
SalesLine
  → fulfillment allocation
  → ReleaseLine
  → physical issue
  → custody reporting
```

A Sales header must not silently override a line Warehouse.

**Classification:** `USER DIRECTIVE`

---

## 9. Release Authorization Contract

The business term “check” means a Warehouse authorization, not a bank cheque, payment instrument, cash, or settlement.

The standardized conceptual name is:

```text
Warehouse Release Authorization
```

Conceptual structure:

```text
Sale
  → Warehouse Release Authorization
      → Release Lines
```

Each ReleaseLine identifies:

```text
Sale
Customer
SalesLine
Product
Warehouse
Unit
Authorized Quantity
Release status
```

A parent authorization may group lines by Warehouse for operations and printing, but grouping must preserve SalesLine identity.

Integrity requirements:

- no Release > Sold;
- no Release > authorized quantity;
- no Release > available/fulfilled source under the approved allocation rule;
- no wrong Product, Warehouse, or SalesLine;
- no duplicate authorization or release;
- no authorization against invalidated/reversed Sale.

For Type A, authorization is permission to release. For Type B, after actual allocation, authorization is also the physical-goods ownership transfer event. In both modes it is distinct from physical release.

**Classification:** `USER DIRECTIVE + ARCHITECTURAL PROPOSAL`

---

## 10. Fulfillment Contract

Fulfillment is the relationship between an existing Sales obligation and actual obtained goods. It is distinct from Purchase receipt, physical availability, ownership, custody, authorization, and physical release.

For Type B:

```text
Future Sale
  → Purchase/PurchaseLine
  → receive_stock()
  → actual inventory and AVCO cost
  → allocation to SalesLine
  → Release Authorization
  → physical release
```

Allocation must identify the actual source quantity and prevent:

- double allocation;
- over-allocation;
- over-fulfillment;
- nonexistent-stock allocation;
- allocating one physical quantity to multiple Sales;
- fabricated StockMovement;
- duplicate authorization.

**Classification:** `USER DIRECTIVE`

---

## 11. Quantity Invariants

| Quantity | Meaning | Source |
|---|---|---|
| Sold / Contracted | Finalized SalesLine quantity | Sales fact; immutable |
| Physical Available | Actual Product + Warehouse quantity | StockMovement/AVCO-derived |
| Allocated / Fulfilled | Actual obtained quantity assigned to SalesLine | Fulfillment event-derived |
| Released | Physically handed-over quantity | Release event history; cumulative-derived |
| Customer Custody | Customer-owned goods physically held by company | Ownership/custody event-derived |
| Remaining Fulfillment | Contracted minus allocated/fulfilled | Sales/fulfillment-derived |

### Type A invariants

If 2,000 are obtained and sold:

```text
Sold = 2,000
Allocated/Fulfilled = 2,000
Released = 0 initially
Custody = 2,000 initially
Remaining Fulfillment = 0
```

After releases of 200 and 300:

```text
Released = 500 cumulative
Custody = 1,500
```

### Type B invariants

At finalization:

```text
Contracted = 5,000
Available = 0
Allocated = 0
Released = 0
Custody = 0
Remaining Fulfillment = 5,000
```

After actual receipt: Available increases by actual received quantity only.

After allocation: Allocated increases; Remaining Fulfillment decreases; ownership/custody remains zero until Type B Release Authorization.

After Type B authorization: actual authorized allocated quantity becomes customer-owned; if still held, it is custody.

After physical release: Released increases and custody decreases.

No single mutable field may represent multiple quantities.

**Classification:** `USER DIRECTIVE + ARCHITECTURAL PROPOSAL`

---

## 12. Commercial Lifecycle

The minimum commercial lifecycle is:

```text
DRAFT → FINALIZED
```

Do not automatically rename `FINALIZED` to `POSTED`. Do not conflate:

```text
commercial finalization
financial posting
fulfillment
authorization
physical release
```

If financial posting needs a separate state, it must be defined separately under the accounting contract.

After finalization, these are immutable:

```text
Customer
Sale Type
Product
Warehouse
Quantity
Unit
Unit Price
Discount
Currency
Exchange Rate
Rate Date
Totals
Ownership basis
Commercial terms
```

**Classification:** `ARCHITECTURAL PROPOSAL grounded in USER DIRECTIVE and protected immutability`

---

## 13. Accounting Boundary

Relevant existing accounts are:

```text
1310 Trade Receivables
4110 Wholesale Sales
4120 Retail Sales
4200 Sales Returns
5100 COGS
```

Their existence does not establish the Sales policy.

| Event | Inventory | Ownership | Receivable | Revenue | COGS |
|---|---|---|---|---|---|
| Type A finalization | No fabricated stock; valuation timing unresolved | Buyer owns actual goods | May create receivable if approved | Unresolved | Unresolved |
| Type B finalization | No StockMovement | Commercial entitlement only | May create receivable if approved | Unresolved | Unresolved |
| Purchase/receipt | Actual inventory through Purchase/`receive_stock()` | Company holds actual goods before Type B authorization | Purchase payable per Purchase | None from Sale | Cost established under Purchase/AVCO |
| Allocation | Uses actual inventory; no fake stock | No Type B ownership transfer yet | None directly | None directly | Unresolved |
| Type B authorization | No physical issue solely from authorization | Physical-goods ownership transfers | None directly | Unresolved | Unresolved |
| Physical release | Reuse `issue_stock()` for actual issue | Handover; Type A ownership already existed | None directly | None directly | Unresolved |
| Payment | None directly | None | Settles receivable under future Payment | None | None |
| Custody | Physical location remains; customer-owned status separate | Customer owns | None | None | Valuation/reporting unresolved |
| Customer → Company | Purchase receipt | Company ownership under Purchase | Payable as applicable | None | Purchase/AVCO |
| Sales Return | Existing return primitive may apply physically | Future return contract required | Future payment treatment | `4200` possible but not selected | Original-cost/COGS unresolved |

No journal is invented by this table.

**Classification:** `REPOSITORY FACT + UNRESOLVED DECISION`

---

## 14. Revenue / COGS Decisions

### 14.1 Revenue account selection

The repository contains both `4110 Wholesale Sales` and `4120 Retail Sales`. Tests prove valid posting usage, not a Sales selector.

Required unresolved question:

```text
What approved business attribute selects 4110 versus 4120?
```

`WHOLESALE → 4110` / `RETAIL → 4120` is only a proposal, not a selected rule.

### 14.2 Revenue timing

Unresolved for both Sale Types:

```text
Finalization?
Authorization?
Physical Release?
Other?
```

Ownership alone does not determine revenue timing.

### 14.3 COGS and inventory reduction

Unresolved:

- Type A COGS event;
- Type B COGS event;
- inventory-reduction event;
- AVCO preservation through allocation;
- delayed custody valuation;
- delayed physical release.

### 14.4 Customer-custody accounting

The business rule is fixed:

```text
Customer-owned custody ≠ company-owned inventory
```

The financial treatment is not evidenced. Possible policies require explicit approval and must not be silently selected:

- exclude custody from company-owned valuation while retaining physical reporting;
- approved reclassification;
- entitlement/custody reporting with an approved financial treatment;
- another documented policy.

```text
FINANCIAL SALES IMPLEMENTATION = BLOCKED
```

**Classification:** `UNRESOLVED ACCOUNTING DECISION + BLOCKER`

---

## 15. Customer-to-Company Purchase Boundary

```text
Customer → Company = NEW PURCHASE
```

The transaction follows the protected Purchase/receipt/cost/inventory/payable path. It is not automatically a Sales Return because the same Product was previously sold.

**Classification:** `USER DIRECTIVE`

---

## 16. Sales Return Boundary

Sales Return is a separate future contract and is not implemented here.

It must eventually identify:

```text
Original Sale
Original SalesLine
Sale Type
Released quantity
Custody quantity
Ownership state
Payment state
Original inventory cost
Financial reversal
COGS treatment
```

Existing inventory return primitives are not evidence of a complete financial Sales Return contract.

**Classification:** `OUT OF SCOPE + UNRESOLVED FUTURE CONTRACT`

---

## 17. Cancellation / Reversal

Edit-based rollback is prohibited after finalization. History must survive:

```text
ownership history
custody history
release history
physical issue history
journal history
```

The effect of cancellation/reversal before release, after partial release, and after full release is not fully defined. It must not be invented.

```text
CANCELLATION/REVERSAL = UNRESOLVED
```

**Classification:** `UNRESOLVED DECISION + BLOCKER for release/financial implementation`

---

## 18. Idempotency

Separate conceptual idempotency boundaries are required for:

```text
Sales Finalization
Financial Sales Posting
Fulfillment Allocation
Warehouse Release Authorization
Physical Release
Payment
Sales Return
```

Duplicate requests must not create duplicate:

- journals;
- StockMovements;
- authorization/release events;
- allocations;
- custody quantities.

Exact key/fingerprint formats must reuse existing accounting/inventory conventions and are not invented here.

**Classification:** `REPOSITORY FACT + ARCHITECTURAL PROPOSAL`

---

## 19. Printing

Printing is a projection only:

```text
Operational
Non-financial
Non-inventory
Non-ownership-changing
```

One Sale may produce Warehouse-specific documents. Each product/item line remains independently identifiable and printable.

Printing twice must not issue stock, transfer ownership, change custody, create a journal, create StockMovement, or create allocation.

**Classification:** `USER DIRECTIVE`

---

## 20. Security / Authorization

Conceptual permission boundaries are separate:

```text
Sales Finalization
Warehouse Authorization
Physical Warehouse Release
Financial Posting
Printing
```

The same user is not assumed to have all permissions.

Printing permission does not imply release permission. Financial posting permission does not imply warehouse issue permission. Invalidated/reversed Sales must block new release. Audit must retain actor and event history.

Exact role names are not selected because no project-wide Sales authorization contract exists.

**Classification:** `ARCHITECTURAL PROPOSAL`

---

## 21. Architecture Decision

### Option A — Owner in StockMovement

```text
Product + Warehouse + Owner
```

- Phase 6 compatibility: poor;
- AVCO/Purchase/transfers/returns/concurrency: invasive impact;
- migration risk: high;
- duplication risk: high if old and new identities coexist;
- multiple owners: direct but destabilizing.

**Status:** `PROPOSED REJECTION`

### Option B — Independent ownership/custody layer

Keep `Product + Warehouse` for physical inventory and add Sales ownership/custody/entitlement information.

- Phase 6 compatibility: high;
- AVCO/Purchase impact: limited bridge work;
- multiple owners: supported;
- future fulfillment: supported;
- accounting reconciliation: required.

**Status:** `PROPOSED`

### Option C — Sales entitlement/release layer over physical Inventory

Sales owns commercial entitlement and Release relationships; Inventory remains physical-stock oriented.

- Phase 6 compatibility: high;
- minimal footprint: strongest;
- multi-Warehouse and partial release: supported;
- future allocation: supported;
- custody accounting: still requires decision.

**Status:** `PROPOSED PREFERRED SHAPE`

### Option D — Separate customer-custody inventory subsystem

- multiple owners: supported;
- Phase 6 compatibility: medium;
- duplicate inventory/AVCO risk: high;
- reconciliation complexity: high;
- minimal footprint: poor.

**Status:** `PROPOSED REJECTION`

### Architecture conclusion

Prefer B+C composition:

```text
Protected physical Inventory
+
SalesLine-level entitlement/custody
+
Warehouse Release Authorization
+
Fulfillment allocation from actual Purchase/Inventory sources
```

This is not approval to implement. It is the smallest architecture consistent with the user rules and protected Phase 6 evidence.

**Classification:** `ARCHITECTURAL PROPOSAL — USER APPROVAL REQUIRED`

---

## 22. Decision Matrix

| ID | Decision | Business Rule | Repository Evidence | Classification | Status | Implementation Consequence | Required Approval |
|---|---|---|---|---|---|---|---|
| PH8-001 | Ownership | Type A finalization; Type B authorization after actual fulfillment | No Sales implementation; explicit user rule | USER DIRECTIVE | RESOLVED | Two Sale Type triggers | None for business rule |
| PH8-002 | Custody | Customer-owned actual goods may remain indefinitely | No custody domain | USER DIRECTIVE | RESOLVED business / accounting open | Custody history layer | Accounting treatment |
| PH8-003 | Sale vs Release | Separate concepts | `issue_stock()` exists; no Release domain | USER DIRECTIVE + REPOSITORY FACT | RESOLVED | Separate authorization and issue | None for separation |
| PH8-004 | Payment | Separate domain; never ownership trigger | Payments placeholder; Party Ledger exists | USER DIRECTIVE | RESOLVED | No Payment Engine in Sales | Later Payment approval |
| PH8-005 | 4110 vs 4120 | Approved business selector required | Both accounts exist; no Sales selector | UNRESOLVED DECISION | BLOCKED | Financial posting blocked | Accounting/business owner |
| PH8-006 | Partial Release | Event history and cumulative quantity | `SALES_ISSUE` primitive exists | USER DIRECTIVE | RESOLVED | Release events required | None for rule |
| PH8-007 | Sales Return | Separate future contract | Inventory return primitives only | UNRESOLVED DECISION | OUT OF SCOPE | Defer Return | Later approval |
| PH8-008 | Phase 7 baseline | Must be reproducible | Working tree has `purchases`; HEAD does not | REPOSITORY FACT | BLOCKED | No clean implementation baseline | Owner/maintainer |
| PH8-009 | GitHub baseline | Must verify if remote exists | No usable remote | REPOSITORY FACT | BLOCKED | No external baseline proof | Remote authority |
| PH8-010 | Company inventory vs custody | Customer custody is not company-owned inventory | No accounting custody policy | USER DIRECTIVE | BLOCKED accounting | Reporting/valuation policy required | Accounting owner |
| PH8-011 | Payment vs ownership | Payment never triggers ownership | Explicit user rule | USER DIRECTIVE | RESOLVED | Unpaid/partial valid | None |
| PH8-012 | Release vs ownership | Type A release not trigger; Type B authorization is trigger | Explicit two-mode rule | USER DIRECTIVE | RESOLVED | Do not collapse modes | None |
| PH8-013 | Warehouse per SalesLine | Mandatory | Product/Warehouse foundation; no Sales model | USER DIRECTIVE | RESOLVED | Header-only Warehouse prohibited | None |
| PH8-014 | Multi-Warehouse | One invoice may span Warehouses | No Sales implementation | USER DIRECTIVE | RESOLVED | Preserve line identity | None |
| PH8-015 | Release Authorization | Parent plus traceable ReleaseLines | No existing document | ARCHITECTURAL PROPOSAL | PROPOSED | Document shape required | User approval |
| PH8-016 | Printing | Projection; no business event | No printing implementation | USER DIRECTIVE | PROPOSED | Warehouse-specific sheets | User approval |
| PH8-017 | Future Sale | No fake physical inventory | Protected StockMovement identity | USER DIRECTIVE | RESOLVED | Commercial obligation separate | None |
| PH8-018 | Future Fulfillment | Purchase/receipt before allocation | Purchase and `receive_stock()` exist | USER DIRECTIVE | RESOLVED | Actual source inventory required | None for order |
| PH8-019 | Customer → Company | New Purchase | Purchase and returns are separate | USER DIRECTIVE | RESOLVED | No Return shortcut | None |
| PH8-020 | Fulfillment allocation | No double/over allocation | No allocation implementation | USER DIRECTIVE | PROPOSED | Source locking/traceability required | User approval |
| PH8-021 | Architecture | Preserve physical identity | Phase 6 protected | ARCHITECTURAL PROPOSAL | PROPOSED | B+C composition | User approval |
| PH8-022 | Lifecycle | DRAFT → FINALIZED | Purchase immutability precedent; no Sales lifecycle | ARCHITECTURAL PROPOSAL | PROPOSED | Separate commercial state | User approval |
| PH8-023 | Immutability | Finalized facts immutable | Protected posted-history convention | USER DIRECTIVE + REPOSITORY FACT | RESOLVED principle | Controlled correction only | Reversal policy later |
| PH8-024 | Idempotency | Separate event boundaries | Existing accounting/inventory patterns | ARCHITECTURAL PROPOSAL | PROPOSED | Reuse conventions | Implementation review |
| PH8-025 | Custody accounting | No silent financial treatment | No evidence | UNRESOLVED DECISION | BLOCKED | Financial Sales blocked | Accounting owner |
| PH8-026 | Revenue/COGS timing | Must be explicitly selected | Accounts/primitives do not select | UNRESOLVED DECISION | BLOCKED | Financial Sales blocked | Accounting owner |
| PH8-027 | Money/FX | Reuse existing conventions | Currency/accounting/FX services exist | REPOSITORY FACT + PROPOSAL | PROPOSED | No duplicate engine | Exact field review |
| PH8-028 | Cancellation/reversal | No edit rollback; policy required | Immutability/reversal conventions | UNRESOLVED DECISION | BLOCKED | Release/financial work gated | User/accounting owner |
| PH8-029 | Type B trigger | Authorization after actual fulfillment | Explicit user rule | USER DIRECTIVE | RESOLVED | Physical ownership event explicit | None |
| PH8-030 | Type A custody | Finalization ownership; release reduces custody | Explicit user rule | USER DIRECTIVE | RESOLVED | Custody begins for available goods | None |

---

## 23. Adversarial Test Contract

No tests are written or modified. Future tests must cover:

### Ordinary Sale

- cash;
- credit;
- zero payment;
- partial payment;
- finalization;
- ownership at Type A finalization;
- custody;
- partial and multiple releases;
- full release;
- payment never changing ownership.

### Multi-Warehouse

- multiple lines and Warehouses;
- same Product from different Warehouses;
- line-level Warehouse integrity;
- ReleaseLine traceability;
- no header override.

### Custody

- 2,000 sold / 200 released / 1,800 custody;
- additional 300 / 1,500 custody;
- no expiry;
- multiple customers in one Warehouse;
- company and customer-owned coexistence.

### Future Sale

- zero-stock Sale;
- no fabricated StockMovement/AVCO/custody;
- later Purchase and actual receipt;
- actual cost;
- allocation;
- no ownership at allocation;
- Type B authorization transfers ownership;
- custody after authorization;
- later physical release.

### Integrity

- over-release;
- wrong Warehouse;
- wrong Product;
- wrong SalesLine;
- duplicate release;
- duplicate authorization;
- duplicate allocation;
- over-allocation;
- duplicate finalization;
- finalized mutation;
- invalid Sale release;
- same source stock allocated twice;
- cancellation after release.

### Accounting, only after decisions

- receivable;
- approved revenue account;
- revenue timing;
- COGS;
- inventory reduction;
- custody policy;
- FX/rate date;
- reversal;
- Return.

### PostgreSQL

Concurrency/idempotency-sensitive behavior must eventually be verified under PostgreSQL. SQLite-only evidence is insufficient for PostgreSQL concurrency claims.

**Classification:** `TEST CONTRACT — FUTURE / NO TESTS WRITTEN`

---

## 24. Dependency Graph

```text
Baseline Qualification
        ↓
Sales Commercial Contract
        ↓
Sale Type
        ↓
Ownership / Commercial Entitlement
        ↓
Custody
        ↓
Fulfillment Allocation
        ↓
Accounting Contract
        ↓
Warehouse Release Authorization
        ↓
Physical Release Integration
        ↓
Future Fulfillment
        ↓
Sales Return
        ↓
Payment / Settlement
```

The ordering is intentional:

- Sale Type precedes ownership semantics;
- actual allocation precedes Type B authorization;
- accounting approval precedes financial posting and COGS;
- authorization is separate from physical issue;
- Return depends on ownership, custody, release, payment, and cost;
- Payment is not an ownership prerequisite.

**Classification:** `ARCHITECTURAL PROPOSAL`

---

## 25. Stage 8.1 Candidate Scope

After user approval and baseline qualification, the smallest candidate Stage 8.1 is:

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

This is a scope proposal, not authorization.

Exclude unless separately approved:

```text
Payment Engine
Sales Return
Physical Issue
Advanced Fulfillment
Custody Accounting
Frontend
Printing implementation
Reporting implementation
Delivery
```

If financial posting is included in Stage 8.1, the unresolved accounting blockers must be resolved first.

**Classification:** `ARCHITECTURAL PROPOSAL`

---

## 26. Implementation Blockers

### Accounting blockers

1. `4110` versus `4120` selector;
2. Type A revenue timing;
3. Type B revenue timing;
4. Type A COGS/inventory-reduction timing;
5. Type B COGS/inventory-reduction timing;
6. custody valuation and financial treatment;
7. Type B authorization/allocation accounting;
8. cancellation/reversal accounting;
9. Sales Return accounting.

### Baseline blockers

1. working-tree Purchase registration versus HEAD;
2. qualification of the frozen Phase 7 runtime baseline;
3. no remote/GitHub verification.

### Proposal-approval gates

1. Release Authorization parent/ReleaseLine shape;
2. printing projection/grouping;
3. fulfillment allocation source and locking contract;
4. conceptual Sale Type representation;
5. commercial state versus financial posting state;
6. exact idempotency boundaries and event references.

**Classification:** `BLOCKER`

---

## 27. Final Implementation Readiness

| Requirement | Status | Evidence | Blocker |
|---|---|---|---|
| Type A business semantics | RESOLVED | User directive | No business blocker |
| Type B business semantics | RESOLVED | User directive | No business blocker |
| Type A ownership trigger | RESOLVED | User directive | No business blocker |
| Type B ownership trigger | RESOLVED | User directive | No business blocker |
| Payment boundary | RESOLVED | User directive; Payments placeholder | No Payment implementation in Phase 8 |
| Custody meaning and open-ended duration | RESOLVED | User directive | Accounting treatment remains blocked |
| Multiple owners in Warehouse | RESOLVED | User directive; protected Product + Warehouse | Custody implementation proposal requires approval |
| SalesLine Warehouse | RESOLVED | User directive; Warehouse foundation | None for business rule |
| Multi-Warehouse Sale | RESOLVED | User directive | Release shape approval |
| Sale versus Release | RESOLVED | User directive; `issue_stock()` | None for separation |
| Partial release | RESOLVED | User directive; `SALES_ISSUE` primitive | Release implementation approval |
| Future Purchase before fulfillment | RESOLVED | User directive; Purchase/`receive_stock()` | Allocation contract |
| Customer → Company | RESOLVED | User directive; Purchase boundary | None |
| Physical identity Product + Warehouse | RESOLVED / PROTECTED | Phase 6 evidence | Must not be changed |
| Release Authorization model | PROPOSED | No existing Sales document | User approval |
| Fulfillment allocation | PROPOSED | No existing allocation domain | User approval |
| Sale Type representation | PROPOSED | Required by two distinct user modes | User approval |
| Commercial lifecycle | PROPOSED | Existing immutability precedent; no Sales lifecycle | User approval |
| `4110` versus `4120` | UNRESOLVED | Both accounts exist; no selector | Accounting decision |
| Revenue timing | UNRESOLVED | No Sales timing contract | Accounting decision |
| COGS/inventory timing | UNRESOLVED | No Sales timing contract | Accounting decision |
| Custody accounting | UNRESOLVED | No custody accounting contract | Accounting decision |
| Cancellation/reversal | UNRESOLVED | No Sales policy | User/accounting decision |
| Phase 7 baseline | BLOCKED | Working tree differs from HEAD | Qualify baseline |
| GitHub baseline | BLOCKED | No usable remote | Provide authoritative remote |
| Payment implementation | OUT OF SCOPE | Payments placeholder/roadmap boundary | Later phase |
| Sales Return implementation | OUT OF SCOPE | Returns placeholder and partial return primitives | Later contract |
| Frontend/printing implementation | OUT OF SCOPE | No Sales UI/printing | Later stage |

### Overall readiness

```text
BUSINESS CONTRACT: RESOLVED
ARCHITECTURAL DIRECTION: PROPOSED
FINANCIAL CONTRACT: BLOCKED
BASELINE CONTRACT: BLOCKED
IMPLEMENTATION AUTHORIZATION: NOT GRANTED
```

---

## 28. STOP

```text
PHASE 8 CONTRACT LOCK

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

TYPE A BUSINESS CONTRACT: RESOLVED
TYPE B BUSINESS CONTRACT: RESOLVED
OWNERSHIP CONTRACT: RESOLVED
CUSTODY CONTRACT: RESOLVED
RELEASE CONTRACT: PROPOSED — USER APPROVAL REQUIRED
FULFILLMENT CONTRACT: PROPOSED — USER APPROVAL REQUIRED
ACCOUNTING CONTRACT: BLOCKED — ACCOUNTING DECISIONS REQUIRED
BASELINE CONTRACT: BLOCKED — BASELINE EVIDENCE REQUIRED
GITHUB BASELINE: BLOCKED — NOT VERIFIED

IMPLEMENTATION AUTHORIZATION:
NOT GRANTED

WAITING FOR USER REVIEW AND APPROVAL
```
