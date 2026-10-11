# Phase 11 — Warehouse Check Pre-Delivery Cancellation Decision

**Status:** User-approved business rule  
**Scope:** Cancellation of a finalized Warehouse Check when the goods have not physically been delivered  
**Approval recorded:** 2026-10-11

## Decision

Cancelling a Warehouse Check before physical delivery cancels the release authorization only. It does not cancel the finalized Sale or change the customer's ownership.

The cancellation must:
- require explicit confirmation that physical delivery did not occur;
- append an immutable reversal of the customer-custody release event;
- restore the quantity to customer-owned custody at the relevant warehouse;
- retain the original Warehouse Check, Sale, ownership entitlement, stock movement, revenue journal, and COGS journal as immutable history;
- prevent the cancelled check from being finalized again or consuming the invoice line's available check quantity;
- reject this path when a Sales Return already exists or when an unsupported negative-COGS obligation is present.

## Independent post-delivery path

If goods were physically delivered and later returned, use the independent Sales Return workflow. A Sales Return must not be represented as pre-delivery authorization cancellation.

## Accounting boundary

This decision does **not** decide or redefine the initial revenue-recognition timing, COGS timing, inventory-reduction timing, or the financial valuation policy for customer-owned custody. It only specifies that cancelling an undelivered Warehouse Check does not automatically reverse the finalized Sale, ownership, or already-posted accounting history.

Customer-owned goods physically held by the company must not be returned to company-owned inventory merely because a release authorization was cancelled.

## Integrity requirements

- Preserve original events and journals; use immutable compensating custody history.
- Keep cancellation idempotent and atomic.
- Test customer custody restoration, unchanged Sale/revenue/COGS history, unchanged company-owned stock, duplicate requests, and the independent Sales Return path.
- Do not merge until current-head CI and review evidence are complete.
