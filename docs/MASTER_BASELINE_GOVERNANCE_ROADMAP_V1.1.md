# HESABDARI BALKH ERP
## MASTER BASELINE & GOVERNANCE ROADMAP
**Version 1.1 — October 30, 2026**

**Repository:** `https://github.com/Balkh/hesabdari_balkh`  
**Authoritative Product Specification:** ERP MASTER BLUEPRINT & BUILD SPECIFICATION v3.0  
**Purpose:** Establish one controlled, evidence-based reference for continuing the existing ERP.

---

# 1. PROJECT MISSION

Continue the existing Hesabdari Balkh ERP. Do not rebuild it, replace its architecture, repeat completed work, or independently change approved accounting contracts.

The system is an Afghanistan-oriented professional ERP supporting:

- Django + Django REST Framework backend
- React + TypeScript frontend
- PostgreSQL production database
- SQLite compatibility for appropriate development/testing
- Tauri desktop direction
- Persian/Dari and English
- RTL/LTR
- Gregorian internal date storage and Jalali user-facing dates
- AFN base currency, USD primary foreign currency, and approved additional currencies
- Centralized design system and professional, simple user experience

**Core product principle:**

ONE BUSINESS ACTION → ONE SOURCE OF TRUTH → AUTOMATIC ACCOUNTING + INVENTORY + PARTY LEDGER + REPORTING + DOCUMENTS.

# 2. AUTHORITATIVE SOURCES AND PRECEDENCE

Use these sources together:

1. ERP MASTER BLUEPRINT & BUILD SPECIFICATION v3.0.
2. Existing approved and frozen accounting/business contracts.
3. Current repository implementation, tests, migrations, and documentation.
4. Comprehensive Project Status and Roadmap Audit.
5. Detailed Phase 8 Audit and its adversarial review.
6. Explicit owner decisions recorded in project conversations and approved project documents.

When sources conflict:

- Do not silently choose one.
- Preserve existing approved contracts.
- Identify the exact conflict and supporting evidence.
- Mark unresolved matters as `OWNER DECISION REQUIRED`.
- Do not convert a proposed roadmap item into an approved implementation contract.

Historical phase numbers and names must not be rewritten merely to fit this roadmap.

# 3. GOVERNANCE — MANDATORY

Every implementation stage follows:

INSPECT → PLAN → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → FROZEN → NEXT.

Before any implementation:

- Inspect live GitHub main, exact SHA, branches, PRs, diffs, and CI.
- Identify protected contracts and dependencies.
- Search for existing functionality before adding anything.
- Make the smallest root-cause correction.
- Keep backend/domain logic authoritative.
- Preserve atomicity, idempotency, auditability, and historical integrity.
- Do not duplicate accounting, inventory, date, currency, validation, or lifecycle engines.

No agent may declare the user's approval or freeze a stage.

Never claim PASS, VERIFIED, GREEN, COMPLETE, APPROVED, or FROZEN without the appropriate executed evidence and owner approval.

# 4. EXISTING PROJECT STATE — AUDIT SNAPSHOT

The October 30, 2026 audit reports identify the following repository snapshot:

`main` SHA reported: `03fc31acdcf628a40ed13c97353759d9e505c79a`

Exact-head CI run reported: `41008998695`  
Run number: `#487`  
The four reported jobs succeeded.

This is a historical audit baseline, NOT permission to assume that the repository is still at this SHA. Step 0 must re-fetch live GitHub and establish the actual current state.

Reported evidence and limitations:

- SQLite suite on the reported SHA: 1022 passed, 9 skipped.
- PostgreSQL 17.11 exact-SHA execution was not independently established.
- CI PostgreSQL job used PostgreSQL 16.
- Frontend React shell exists, but operational business pages were not found in the audited state.
- Four API areas were reported mounted: core health, security, fiscal periods, and landed costs.
- Backend domain capabilities exist across accounting, purchasing, inventory, transit, landed costs, sales, returns, custody, payments, and allocations.
- Reporting, printing/PDF, backup/restore, and complete operational UI/API workflows remain major gaps.
- PR #46 was merged and must be included in the history.
- `12d78fb` is not a global Phase 8/11 freeze marker.
- Phase 8 and Phase 11 have implemented and tested subcontracts, but repository documentation does not establish a blanket global freeze for both phases.

These claims must be checked against live evidence in Step 0.

# 5. PROTECTED ACCOUNTING AND INVENTORY CONTRACTS

Preserve all owner-approved and frozen contracts.

Known accounting foundations include:

- Full double-entry accounting.
- Canonical four-digit Chart of Accounts.
- `post_journal()` as the accounting posting boundary.
- Half-Up money precision.
- Balanced journals.
- Atomic posting and idempotent retry behavior.
- Posted financial history is immutable.
- Corrections use approved reversal/adjustment mechanisms.
- Posted-only balance and trial-balance derivation.
- Historical exchange-rate integrity.
- No silent mixed-currency aggregation.
- Traceability from business event to journal and ledger.

Known account identities include:

- `1110` Cash
- `1210/1220` Exchange-house accounts
- `1310` Receivables
- `2200` Advances/credits
- `4110` Wholesale revenue
- `4120` Retail revenue
- `4200` Sales returns
- `5100` COGS
- `5200` Purchase returns
- `8100/8200` FX gain/loss patterns

Do not alter account identities or posting rules without explicit owner approval.

Inventory and costing protections include:

- Preserve product/warehouse stock identity and existing movement rules.
- Preserve approved transit, landed-cost, wastage, and costing behavior.
- Do not blend independent purchase lots contrary to approved contracts.
- Preserve chronological replay and controlled correction rules.
- Preserve the approved distinction between ownership, custody, physical release, and inventory movement.
- Do not silently change invoice-time COGS or approved Phase 11 costing decisions.

# 6. EXCHANGE-HOUSE, HAWALA AND COMMISSION SCOPE

This section explicitly clarifies the company's own financial operations.

## 6.1 In scope

The ERP must support the company's financial relationship with exchange houses, including:

- Purchase invoice settlement through an exchange house.
- Sales invoice receipt through an exchange house.
- Company funds held with each exchange house.
- Transfers between company cash and exchange-house accounts.
- Transfers between one exchange house and another.
- Exchange-house transaction references and supporting records.
- Exchange-house account balances and statements.
- Reconciliation of recorded transactions against exchange-house statements.
- Applicable fees/commissions and foreign-exchange differences.
- Traceability to the related purchase, sale, payment, receipt, or treasury event.

The system records the company's financial event and its reference. It does not recreate the exchange house's internal remittance network.

## 6.2 Commission handling — owner-confirmed business requirement

A commission may be zero or may be charged.

The company may choose or agree with the exchange house to settle commission in different ways:

**A. Deduct commission from the remittance principal**

Example:

- Instruction/remittance amount: USD 100,000
- Commission deducted from principal: USD 50
- Net amount reaching destination: USD 99,950

**B. Deduct commission separately from the company's balance held with the exchange house**

Example:

- Principal delivered to destination: USD 100,000
- Commission: USD 50
- Total debit to company's exchange-house balance: USD 100,050

**C. Pay commission separately**

Example:

- Principal: USD 100,000
- Separate commission payment: USD 50
- Total company outflow: USD 100,050

The system must preserve the distinction between:

- Principal amount instructed.
- Net amount received by the beneficiary.
- Commission amount.
- Amount deducted from the company's exchange-house balance.
- Any separate commission payment.
- Currency and applicable exchange-rate information.
- Exchange house, transaction reference, date, and related business document.

These are business requirements. Exact accounting entries, fee classification, currency conversion, and reconciliation rules must be verified against existing contracts and submitted for owner approval if undefined.

Do not assume all three methods are interchangeable in their accounting treatment.

### 6.2.1 Supplier purchase settlement — explicit owner clarification

For payments settling a supplier's purchase payable, the supplier must receive the
full amount owed. Exchange-house commission is a separate company expense and MUST
NOT reduce the supplier's payable or the principal credited as paid to the supplier.

Owner-approved rules:

- Commission is optional per payment; it is not mandatory.
- A payment may have zero commission. Zero commission creates no commission
  expense journal line or expense event.
- When commission is charged, record it separately from the supplier principal.
- The canonical expense account is **6400 — Exchange House Commission Expense**
  (**هزینه کمیسیون صرافی‌ها**), a posting EXPENSE account under 6000 — Expenses.
- If the commission is charged to the company's exchange-house balance, debit
  the commission expense and credit that exchange-house account separately from
  the supplier-principal settlement.
- If commission is paid separately from company cash/bank, debit the commission
  expense and credit the actual cash/bank account separately.
- The supplier payable is settled for the full principal amount, regardless of
  the separate commission.
- Preserve separate principal and commission amounts, currencies, rates, dates,
  exchange-house/payment references, and source-document traceability.
- Apply atomicity, idempotency, historical FX integrity, and reversal-only
  correction to posted accounting effects.

Illustration for a USD 100,000 supplier payable and USD 50 commission:

- Supplier settlement: Dr Trade Payables 100,000 / Cr Exchange House 100,000.
- Commission from exchange-house balance: Dr 6400 50 / Cr Exchange House 50.
- Or commission paid separately: Dr 6400 50 / Cr the actual cash/bank account 50.

If commission is zero, only the supplier settlement is recorded. This supplier
rule does not silently define commission treatment for unrelated sales or other
business events; those must follow their own approved contracts.

## 6.3 Out of scope

A standalone public/third-party remittance business is excluded unless the owner explicitly changes scope.

This exclusion does NOT remove the company's own purchase/sales settlement through hawala or its own exchange-house accounts.

# 7. DEPENDENCY-AWARE ROADMAP

The following is the controlled roadmap. It is not a claim that every listed capability is currently incomplete or complete; Step 0 must establish exact status.

## STEP 0 — Master Baseline Verification and Dependency Audit

Read-only reconciliation of:

- Blueprint v3.0
- Approved/frozen contracts
- Project status and Phase 8 audits
- Current live GitHub state
- Actual code, migrations, tests, API routes, and CI evidence
- Exchange-house and commission requirements in this baseline

Deliver a verified status register, risk register, contract register, dependency graph, and proposed first implementation batch.

## STEP 1 — Resolve Confirmed Contract Gaps

Only where evidence establishes an actual unresolved or contradictory contract.

Candidate subjects include:

- Remaining FUTURE Sales behavior.
- Exchange-house settlement and commission details.
- Role/permission model.
- Other material business decisions discovered by Step 0.

No speculative contract changes.

## STEP 2 — Security, Users, Roles and Permissions

Verify authentication, authorization, roles, access boundaries, audit events, and production protections.

Preserve the approved Security Batch 2 and Batch 3 scope.

## STEP 3 — Purchase-to-Inventory Operational Vertical

Verify and complete the operational chain where gaps exist:

Purchase → Payment/Settlement → Exchange House where applicable → Receiving → Landed Costs → Inventory → Supplier Ledger → Accounting.

Include the company's exchange-house settlement and commission requirements where applicable.

## STEP 4 — AVAILABLE Sales Operational Vertical

Verify and expose the approved AVAILABLE sales workflow through the required API and UI layers.

Preserve approved revenue, COGS, custody, allocation, return, and release behavior.

## STEP 5 — FUTURE Sales

Proceed only after the unresolved FUTURE sales contract is fully reviewed and approved.

Do not infer fulfillment COGS, stock reduction, custody valuation, ownership transfer, or release authorization.

## STEP 6 — Master Data and Party Ledger

Verify and complete the operational customer, supplier, product, unit, and related party workflows and ledger views.

## STEP 7 — Treasury and Exchange-House Operations

Complete the company's cash and exchange-house operational workflows, including:

- Cash accounts.
- Exchange-house accounts.
- Inter-account transfers.
- Purchase/sales settlements.
- Commission handling.
- Currency and rate traceability.
- Statements and reconciliation.

Avoid duplicate accounting logic.

## STEP 8 — Operational Frontend

Deliver coherent end-to-end screens for the approved operational workflows, bilingual and RTL/LTR, using the existing design system.

## STEP 9 — Reporting

Deliver accurate financial and operational reports from authoritative backend data.

## STEP 10 — Documents and Printing

Centralized document/print/PDF architecture, approved invoice formats, Half-A4 support, selected invoice items, and bilingual presentation.

## STEP 11 — Fiscal Periods and Closing

Verify posting-date enforcement, period states, close validation, authorized reopening, and historical reporting.

## STEP 12 — Backup, Restore and Disaster Recovery

Implement and test actual backup and restore, including data integrity verification.

## STEP 13 — Settings, Search and Management Capabilities

Complete remaining product-level configuration and management features supported by the Blueprint.

## STEP 14 — Data Migration and Deployment

Define controlled import/opening-balance procedures, deployment configuration, and operational readiness.

## STEP 15 — End-to-End Validation and Acceptance

Run complete accounting, inventory, party-ledger, exchange-house, API, frontend, document, security, performance, backup/restore, and regression validation.

Final acceptance requires owner review and explicit approval.

# 8. REQUIRED EVIDENCE STANDARD

For each stage, provide:

- Exact repository URL, branch, and SHA.
- PR and commit references.
- Files changed and reason for each change.
- Tests added/changed and exact commands.
- Actual test outputs and exit codes.
- Database/backend/frontend/CI evidence as applicable.
- Accounting reconciliation.
- Inventory reconciliation.
- Party-ledger and exchange-house reconciliation where applicable.
- Known limitations and skipped tests.
- Contract impact analysis.
- User-review handoff.

A CI badge alone is not proof of business correctness.

# 9. OUT-OF-SCOPE AND PROHIBITIONS

Do not:

- Rebuild the repository.
- Rewrite frozen contracts.
- Add a standalone third-party remittance business.
- Invent accounting entries or commission rules.
- Change chart-of-account identities without approval.
- Duplicate posting, inventory, currency, date, audit, or validation logic.
- Silently alter posted history.
- Declare a phase frozen on the owner's behalf.
- Merge or push without explicit authorization.
- Treat missing UI as proof that backend functionality is absent.
- Treat backend models/services as proof that an operational workflow is complete.
# 10. IMMEDIATE NEXT ACTION

Execute STEP 0 only.

It is a read-only audit. Its deliverable is the evidence-based current Master Baseline Audit and a proposed first bounded implementation batch.

Stop after presenting the report. Wait for owner review and approval.

# 11. OWNER DECISION AMENDMENT — OD-6 ITEM 2 (2026-10-30)

The owner has explicitly revised OD-6 Item 2 and restored persisted Draft documents in accordance with the original contract. This decision supersedes only the earlier rejection of Draft persistence.

- Draft documents are saved as persistent database records and remain editable before submission.
- Saving a Draft does not submit it for review/approval and creates no accounting posting or final business effect.
- When complete, the document is submitted to the existing OD-6 review/approval workflow.
- `DRAFT` (creator is still preparing the document) must be distinguished from `PENDING_EVIDENCE` (document is in the controlled workflow but required supporting evidence is outstanding).
- OD-4 evidence rules, the authorized temporary-exception process, approval/posting separation, posted-document immutability, and all other OD-6 decisions remain unchanged.

Detailed owner amendment: `docs/decisions/OD-6_ITEM_2_DRAFT_PERSISTENCE_OWNER_AMENDMENT_2026-10-30.md`.

**Implementation status:** owner decision recorded; no implementation, migration, API/UI change, test result, freeze, or merge is implied by this amendment.
