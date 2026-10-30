# OD-6 Item 2 — Owner Amendment: Persisted Draft Documents

**Decision ID:** OD-6 / Item 2  
**Decision date:** 2026-10-30  
**Authority:** Explicit ERP owner instruction in the project conversation  
**Status:** OWNER-APPROVED DECISION; MERGED INTO MAIN VIA PR #53  
**Scope:** Generic document lifecycle only. This amendment does not change the other OD-6 decisions or any accounting, inventory, Phase 8 Sales, Phase 11, OD-4, or security contract.

## 1. Superseding owner decision

The owner expressly reverses the earlier rejection of Draft persistence and restores Draft capability in accordance with the original contract.

**Approved rule:** A business document may be saved as a persistent **DRAFT** record in the database before it is submitted into the review/approval workflow.

A Draft document:
- is persisted; it is not merely temporary browser/UI state;
- remains editable while it is in Draft;
- is not yet submitted for review or approval;
- must not create an accounting posting, journal, inventory movement, ledger effect, or other final business effect merely because it was saved as Draft;
- may be submitted to the configured review workflow when the required information is complete.

After submission, the document follows the already-approved OD-6 workflow: validation, assigned review/approval, return/rejection with reason where applicable, approval separate from accounting posting, and the existing posting/immutability rules.

## 2. Draft versus Pending Evidence

These states must not be conflated:

- **DRAFT:** The document is still being prepared by its creator. It is persisted and editable, and has not yet entered review/approval.
- **PENDING_EVIDENCE:** The document has been submitted or is otherwise in the controlled business workflow, but required supporting evidence is incomplete or outstanding. The document remains non-postable under OD-4 unless the explicitly authorized temporary exception process is used (reason, approver, and deadline).

The exact status representation and transitions must reuse the existing document/domain lifecycle design; do not create a competing lifecycle engine.

## 3. Unchanged decisions and protections

- OD-6 items 1 and 3–15 remain as previously owner-approved.
- OD-4 remains unchanged, including evidence requirements and its authorized temporary-exception rule.
- Approval remains distinct from accounting posting.
- A posted document remains immutable; correction follows approved reversal/correction mechanisms.
- No draft save may be treated as approval, finalization, posting, or permission to alter posted history.
- Existing document-specific contracts may define their own additional states and transitions; this generic amendment does not silently rewrite them.

## 4. Implementation and evidence boundary

This is an owner business decision and documentation amendment only. It does not assert that a centralized document workflow, persistence API, frontend, migration, or tests have been implemented or verified.

Before implementation, inspect existing document models/services and document-specific contracts. Reuse existing Draft capabilities where they satisfy this rule; identify only proven gaps. Any implementation must follow the repository's INSPECT → PLAN → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → FROZEN process.

## 5. Supersession note

This record supersedes only the earlier owner rejection of Draft persistence for OD-6 Item 2. It does not supersede the Phase 0 contract, Blueprint v3.0, Phase 8 Sales lifecycle contract, Phase 11 contracts, or any other approved decision.
