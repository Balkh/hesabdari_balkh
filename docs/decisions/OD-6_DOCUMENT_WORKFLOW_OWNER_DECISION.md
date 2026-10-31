# OD-6 — Document Workflow and Approval Owner Decision

**Decision ID:** OD-6  
**Record date:** 2026-10-31  
**Authority:** Explicit owner-approved workflow decisions recorded in the Hesabdari Balkh project conversation  
**Status:** OWNER-APPROVED DECISION — DOCUMENTED BY W0-1  
**Scope:** Generic business-document preparation, review, approval, posting, cancellation, partial execution, and workflow history

## 1. General workflow

Documents follow a controlled lifecycle appropriate to their type. Preparation, submission, review, approval, accounting posting, physical execution, and cancellation are distinct events. A module must not collapse these stages into one status or infer that approval automatically means posting.

The exact state names and permitted transitions must reuse the existing document/domain lifecycle where suitable. This generic decision does not silently replace document-specific contracts.

## 2. Persistent Draft — owner amendment

A business document may be saved as a persistent **DRAFT** database record before submission.

- DRAFT is persisted and remains editable by its creator/authorized users.
- DRAFT has not been submitted for review or approval.
- Saving DRAFT creates no journal, accounting posting, inventory movement, party-ledger effect, or other final business effect.
- When complete, the document is submitted into the configured workflow.
- DRAFT must not be conflated with PENDING_EVIDENCE.

**DRAFT** means preparation is still in progress and the document has not entered review. **PENDING_EVIDENCE** means the document has been submitted or is in the controlled workflow but required evidence remains outstanding; normal posting is blocked under OD-4 unless an authorized temporary exception applies.

The detailed owner amendment is recorded in OD-6_ITEM_2_DRAFT_PERSISTENCE_OWNER_AMENDMENT_2026-10-30.md and merged through PR #53. This record does not alter that amendment.

## 3. Required-field validation and submission

Required fields and document-specific validations must be checked before submission and again at the authoritative business/posting boundary as appropriate. Client-side validation is not sufficient. Invalid or incomplete documents must not enter a state that permits unauthorized posting or execution.

## 4. Reviewers and approvers

The GM assigns reviewers/approvers according to document type and the approved workflow configuration. Assignment and reassignment must be recorded.

## 5. Self-approval and GM authority

A creator may approve their own document only when the creator has the explicit permission for that document/action. The GM may create and approve the GM's own operations; no second approver is required for the GM. These rules do not override any hard accounting, evidence, or posted-history invariant.

## 6. Reject, return, and resubmission

A reviewer/approver may reject or return a document with a recorded reason. The authorized creator/user may correct it and resubmit it. The workflow must preserve prior submissions, decisions, reasons, and actors rather than erasing the history.

## 7. Editing an approved but unposted document

An approved but not-yet-posted document may not be edited while its approval remains effective. The approval must first be revoked through the authorized workflow, and the document must be returned to correction/review before edits are made. The revocation, reason, and subsequent review must be recorded.

## 8. Approval versus accounting posting

Approval is separate from accounting posting. An approved document is not necessarily posted. Posting requires its own authorization, validation, evidence, period, idempotency, and accounting/domain controls.

## 9. Posted-document immutability

A POSTED document is locked and must not be directly edited, overwritten, or deleted, including by the GM. Correction follows the approved reversal/adjustment or versioned correction path for that document type. No workflow permission can bypass this invariant.

## 10. Cancellation and partial execution

- An approved but unposted document may be cancelled with a recorded reason and authorized actor.
- A posted document cannot be cancelled by erasing or directly changing its history; use the approved reversal/correction path.
- For a partially executed document, the completed portion and its history remain intact. Only the unexecuted remainder may be cancelled, with reason and authorization.
- Cancellation must not reverse or erase already completed physical or financial events unless the applicable approved domain contract explicitly requires a separate reversal.

## 11. Partial operations

The workflow must support partial execution where the document type permits it. Each completed portion must be traceable and idempotent. Remaining quantities/amounts must be derived without duplicating or overwriting completed events.

## 12. Related-document linkage

Related documents must be linked through stable transaction/document identifiers so the complete business chain can be navigated and audited.

## 13. Workflow history

Workflow history must preserve, at minimum, actors, timestamps, action/stage, reasons, assignments, approvals, returns/rejections, revocations, submissions, and links to the affected document/version.

## 14. Duplicate prevention

Stable unique identifiers and idempotency boundaries must prevent duplicate submission effects, approvals where non-repeatable, accounting posting, and execution. Retries must not create duplicate journals, inventory movements, or other final business effects.

## 15. OD-4 evidence rules and exceptions

Required evidence, material discrepancy handling, pending-evidence behavior, and temporary exceptions follow OD-4. Missing mandatory evidence blocks normal final posting. Any temporary exception must be authorized and retain approver, reason, scope, and deadline. An exception must not become a silent permanent waiver.

## 16. Implementation boundary

This record consolidates the owner-approved workflow rules and the later Draft amendment. It does not claim that a central document engine, workflow API, database persistence, frontend, migrations, or tests are implemented. Implementation must inspect and reuse existing document numbering, document-specific models/services, audit events, and lifecycle logic rather than introducing duplicate engines.
