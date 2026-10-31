# OD-4 — Document Authority Owner Decision

**Decision ID:** OD-4  
**Record date:** 2026-10-31  
**Authority:** Explicit owner-approved decisions recorded in the Hesabdari Balkh project conversation  
**Status:** OWNER-APPROVED DECISION — DOCUMENTED BY W0-1  
**Scope:** Authority, evidence, integrity, and traceability of business and financial documents

## 1. Three distinct sources of authority

The system must preserve the distinction between:

1. **Commercial/business documents** — evidence of what the parties agreed and what business activity occurred.
2. **Posted accounting documents** — authoritative evidence of the financial effect recorded in the books.
3. **Audit trail** — evidence of who performed, changed, reviewed, approved, or reversed an action, and when and why.

These sources are related but are not interchangeable. A commercial document alone does not prove that accounting was posted; an accounting journal does not replace the underlying business evidence; an audit event does not replace either document.

## 2. Required evidence and discrepancy handling

- Required supporting evidence must be linked to the relevant transaction/document.
- Material differences in quantity, amount, or inventory must be identified and resolved before normal finalization/posting.
- A disputed portion must be held; it must not be silently accepted or included in a final posting.
- An incomplete document may remain pending required evidence, but normal final posting is blocked while mandatory evidence is missing.
- Any temporary exception must be explicitly authorized and must record the approver, reason, scope, and deadline. An exception is not a silent waiver or permanent removal of the evidence requirement.
- The user responsible for resolving a discrepancy must record the outcome, reason, supporting evidence, and approver where required.

## 3. Document identity, history, and versions

- Documents must be linked to their originating and related transaction identifiers.
- Documents must be searchable by document number, date, counterparty, and document type.
- Document view, download, edit, and approval actions must be permission-controlled and logged.
- Revisions must be preserved as versions/history; the system must not erase the fact that a prior version existed.
- A posted document must never be permanently deleted or directly overwritten. A correction must use a new version or the approved reversal/adjustment process appropriate to the document type.
- The audit trail must retain the actor, action, timestamp, reason where required, and links to the affected document/transaction.

## 4. Relationship to workflow and accounting

Document review/approval is separate from accounting posting. A document may be commercially prepared or approved while still not posted. Posting is allowed only when required validation, authorization, and evidence conditions are satisfied.

OD-4 must be applied together with OD-6 workflow rules. Where an authorized temporary evidence exception is used, its scope and expiry/deadline must remain visible and auditable.

## 5. Implementation boundary

This decision defines document authority and evidence policy. It does not claim that a centralized document repository, attachment service, versioning system, approval workflow, API, UI, or immutable audit storage is implemented. Implementation must inspect and reuse existing document numbering, domain documents, audit events, and lifecycle services rather than creating competing engines.
