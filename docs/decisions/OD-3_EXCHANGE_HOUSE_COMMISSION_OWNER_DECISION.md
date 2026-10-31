# OD-3 — Exchange-House Commission Owner Decision

**Decision ID:** OD-3  
**Record date:** 2026-10-31  
**Authority:** Explicit owner-approved decisions recorded in the Hesabdari Balkh project conversation  
**Status:** OWNER-APPROVED DECISION — DOCUMENTED BY W0-1  
**Scope:** The company's own exchange-house balances, settlements, transfers, commission, and reconciliation

## 1. Scope boundary

The ERP records the company's own financial relationship with exchange houses: company balances, receipts, payments, transfers, settlement references, commission, and reconciliation.

A standalone public/third-party remittance or hawala business remains completely out of scope unless the owner explicitly changes that scope. This exclusion does not remove the company's own exchange-house accounts and settlements from the ERP.

## 2. Commission is a separate, explicit transaction component

- Commission may be zero or non-zero; it is not mandatory.
- Commission charged to a customer on a customer payment is the customer's responsibility and must not be silently recorded as a company commission expense.
- Supplier purchase principal is paid in full by default. Supplier commission is a separate company expense and must not reduce the supplier payable or principal paid, **except for the narrowly controlled Method A exception in Section 3**.
- Company commission expense uses account **6400 — Exchange House Commission Expense**.
- A zero commission creates no commission expense event or journal line.
- Commission, principal, currency, rate, date, exchange house, transaction reference, source document, and payer/payee responsibility must remain separately identifiable.

## 3. Supplier settlement methods and Method A exception

The default rule is that the supplier receives the full principal owed and the company bears any applicable exchange-house commission separately.

**Method A — deduction from supplier remittance principal is an exception, not a default.** It is permitted only when all of the following are true:

1. A prior agreement with the supplier or other relevant counterparty explicitly authorizes the deduction.
2. The agreement is documented and linked to the transaction.
3. An authorized user records the exception and its reason.
4. The required approval is recorded before the settlement is finalized.
5. The system preserves gross principal, deducted commission, net amount received, currency, rate, and supporting evidence as separate values.

Without all required evidence and authorization, Method A must be unavailable and the full supplier principal must be settled.

Other supported arrangements may charge commission separately to the company's exchange-house balance or pay it separately from company cash/bank. These methods are not interchangeable in accounting treatment.

## 4. Expense and liability integrity

- When company commission is incurred, recognize the expense once using account 6400 and the actual funding/settlement account or applicable liability.
- If commission is accrued as a liability and paid later, the later payment clears that liability; it must not recognize a second commission expense.
- A commission refund is recognized only when the refund is actually received. An expected or promised refund is not a receipt.
- Preserve atomicity, idempotency, historical FX integrity, and reversal-only correction for posted accounting effects.
- Do not silently net commission against unrelated principal, supplier payable, customer receipts, or another currency balance.

## 5. Exchange-house accounts, currencies, and transfers

- Each exchange-house account and currency balance is independent.
- Do not merge different currencies or exchange-house balances.
- Exchange rates are entered/selected manually under the approved transaction-rate rules; do not invent an automatic rate source.
- Transfers may have an in-transit state.
- Failed, rejected, or returned transfers remain recorded with their status and history; they are not deleted.
- Reconciliation compares recorded transactions with external statements and identifies differences. It must never auto-adjust balances or create an unexplained balancing entry.
- Every transfer and settlement must retain its source, destination, amount, currency, reference, actor, timestamps, and linked business documents.

## 6. Commission document, audit, and permissions

Commission must be independently identifiable and auditable, even when associated with a purchase, payment, or exchange-house transfer.

Entry, review, and approval must be permission-controlled. Duplicate commission recording must be prevented. The business methods/paths (including Method A, separate balance deduction, and separate payment) must remain distinguishable and must not be treated as interchangeable.

## 7. Boundaries

This decision records business policy. It does not by itself assert that exchange-house ledgers, commission documents, transfer workflows, reconciliation, APIs, UI, or related tests are implemented.

No standalone remittance/hawala service is authorized. No new accounting entry or account beyond the approved account 6400 is invented by this record.
