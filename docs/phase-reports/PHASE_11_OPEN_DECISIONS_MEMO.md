# Phase 11 — Owner Decisions and Accounting Boundaries

Status: **OWNER DECISIONS RECEIVED — 2026-10-24**. This memo records the owner's explicit selections A1 and B1. It does not authorize a merge or a phase freeze.

## Decision A — Cost-pool correction after downstream warehouse activity

### Owner decision: A1 — keep fail-closed behavior

The owner selected **A1: retain the current fail-closed guard**. When downstream stock movements, receipts, sales, returns, transfers, or later valuation layers make a correction unsafe under the approved reversal rules, the system must refuse the automatic correction. The case requires accountant review and an explicitly approved compensating journal/controlled correction. Do not implement a new general chronological-replay engine under this decision.

### Current behavior and boundaries

- `reverse_landed_cost` in `backend/purchases/landed_cost_reversal.py` uses `_assert_no_later_activity` to refuse reversal when later dependent activity exists.
- The transit-loss valuation reversal has its own guards and must retain its existing narrowly scoped behavior and regression coverage. Do not broaden it into a general replay engine or bypass a guard.
- Posted journals remain immutable. Corrections must use authorized reversals/compensating entries, never edits to posted history.
- Where no later dependent activity exists and the approved reversal workflow proves safe, reverse → repost corrected cost → re-finalize the relevant valuation may be used as currently implemented and tested.
- Where the existing guard rejects the correction, stop atomically and escalate for accountant review. Do not silently post a manual journal automatically or pretend that a compensating journal reconstructs all historical inventory valuation.

### Consequences and controls

A1 favors preservation of audit history and avoids inventing event ordering for consumed AVCO layers. It may require slower manual review and an approved compensating entry. Record the source transaction, reason, affected accounts/warehouses, valuation impact, authorizer, and link to the original posted journals. Never change original documents or posted journals.

### Explicitly not authorized

- A new general chronological-replay engine.
- Automatic rewriting/recalculation of historical COGS after downstream activity when current guards cannot prove a safe correction.
- Weakening or bypassing existing reversal guards.
- Any new migration that fabricates historical allocation or movement data.

### Owner decision status

**RESOLVED — A1 selected by owner on 2026-10-24.** The A1 policy is now the governing decision for this scope. The remaining implementation/review task is to verify that code, tests, and documentation consistently preserve fail-closed behavior and do not claim a general replay engine is approved.

## Decision B — Transit COGS timing

### Owner decision: B1 — invoice-finalization timing

The owner selected **B1: confirm transit COGS at sales-invoice finalization**, using the specific transit purchase lot's cost.

Current approved journal at transit-sale invoice finalization:

- Dr `5100` — Cost of Goods Sold.
- Cr `1430` — Goods in Transit.
- Amount: the sold quantity multiplied by that lot's applicable current unit cost, using the approved money/rounding helpers.

A `TransitSaleAllocation` must preserve the source lot, quantity, and unit-cost traceability. Physical warehouse receipt must not post the same transit COGS a second time. Later direct-cost or final-loss corrections must use the existing approved, guarded adjustment/reversal paths. If a guard cannot establish a safe correction, fail closed under Decision A1.

### Explicitly not authorized

- Deferring transit COGS to physical receipt or delivery.
- Changing the transit journal boundary or clearing behavior.
- Blending transit lot cost into ordinary warehouse AVCO before the approved stock receipt/valuation process.
- Treating the ordinary-stock invoice-time COGS contract as permission to change unrelated transit accounting behavior.

### Owner decision status

**RESOLVED — B1 selected by owner on 2026-10-24.** Preserve invoice-finalization COGS for transit sales. No timing change or migration is authorized by this decision.

## Release gates that remain

- Technical review, exact-head tests, migration verification, and dependency-aware merge-readiness review remain required.
- PR #38 remains the stack root; PRs #39 and #40 depend on it. Verify actual ancestry and exact heads before any integration.
- Merge requires separate explicit owner authorization. These accounting decisions do **not** authorize merging.
- Phase freeze requires authorized integration, required post-merge evidence on `main`, and review of any remaining technical risks. Do not describe A or B as still undecided; both decisions are resolved.
