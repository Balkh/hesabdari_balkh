# Phase 4.1 — Contract Interpretation Record (REQUIRED BEFORE MIGRATION)

**Date (UTC):** 2026-09-13
**Branch:** `phase/4` (from frozen `a43725e`)
**Principle:** *Contract silence ≠ permission to invent a permanent business rule.*
Every item below is either (C) contract-stated, (R) repo-convention, or (U) user ruling.
(U) items were approved by the user on 2026-09-13 BEFORE any schema/code.

## U-1. App layout: three apps — `categories`, `uom`, `products` (U)
Fine-grained, matching repo convention. 4.2/4.3/4.4 apps untouched.

## U-2. Category identity: id + name(required) + name_fa(optional). NO code. (U)
Contract never requires a Category code; inventing one now would freeze a
permanent rule. Names are NON-unique: neither contract nor repo convention
(`Account.name`, `FiscalPeriod.name` are non-unique) requires name uniqueness.

## U-3. UOM identity: id + name(required) + name_fa(optional). NO code. (U)
Same rationale as U-2. Model class: `UnitOfMeasure`.

## U-4. Reference prices: numeric-only, 4 decimals, NO currency. (U)
Contract (§4.1 + §4.2) defines them as currency-less suggestions; assuming a
currency (even AFN) would be invention. Storage precision 4 follows §3.11
Unit Price (C). No >= 0 constraint: suggestions are never posted or computed
in 4.1, so any sign rule would be invented behavior. Recorded non-decision.

## R-1. Category is FLAT (no parent/hierarchy). (R: silent contract → minimal)
A hierarchy would be invented structure. Additive later if ever required.

## R-2. Conversion factor: always present, default 1, must be > 0. (C+R)
§4.1 lists it WITHOUT "optional" → NOT NULL. Default 1 = identity for
single-UOM products. Direction convention (RECORDED, NEVER APPLIED in 4.1):
primary units per 1 secondary, matching §3.13 examples ("1 Carton = 10 L").
The > 0 check defends the recorded definition itself (structural, like the
fiscal date-range check) — not business behavior.

## R-3. Minimum stock: NOT NULL, default 0, must be >= 0. (C+R)
§4.1 lists it WITHOUT "optional" → NOT NULL. Negative minimum contradicts the
plain contract term (structural). Maximum / reorder: nullable (C: "optional").

## R-4. Recorded NON-decisions (explicitly NOT enforced — contract is silent):
- max >= min, reorder within [min, max]: NOT validated.
- secondary UOM != primary UOM: NOT validated.
- reference price sign: NOT constrained (see U-4).
- name uniqueness (Category/UOM/Product): NOT enforced (see U-2/U-3).
- barcode uniqueness/format: NOT enforced (§4.1 says "Unique" only for code).

## R-5. Brand is a Product ATTRIBUTE (free text), not a master entity. (C)
§4.1 lists "Brand optional" under "Each product". No brands table.

## R-6. Product.code: user-assigned, unique, max 30 (C+R).
Uniqueness is contract (C). No auto-numbering: `NumberSequence` is
document-scoped (document_type + jalali_year). Length 30 follows the
document-number convention (R: DB types require SOME length).

## R-7. Product names: BOTH required (C). `name`=English, `name_fa`=Persian/Dari (R).
§4.1 lists both WITHOUT "optional"; field pair follows `Account` (R).

## R-8. Quantities (min/max/reorder): Decimal(20,3), no behavior. (R)
Contract gives no quantity precision; 3dp is the recorded neutral storage
choice. Values are stored ONLY — no availability, no alerts, no blocking.

## R-9. No DELETE path in 4.1 services (C+R).
§10: inactive ≠ deletion. Frozen `AuditAction` has no DELETE choice and
frozen apps cannot be migrated. Deactivation via UPDATE only.

## R-10. API: domain-only, NO REST in 4.1 (C).
Contract contains zero API requirements; §13 orders the smallest boundary.
Consumed via services (same as the journal engine, which has no API either).

## R-11. Audit: CREATE + UPDATE via existing writer (C+R).
§13.4 lists Create/Update/Delete as important trail actions → reuse
`record_audit_event` with previous/new snapshots. No new audit model/writer.

## R-12. Deterministic ordering + blank-guards (R).
`ordering = ["name", "id"]` (masters) / `["code", "id"]` (product);
DB `Length() > 0` checks on required texts (structural, PG/SQLite-safe).

## Frozen-surface note
Phase 1/2/3 files, all existing migrations, frontend, CI: untouched.
New: 3 apps + this record + evidence. `phase/4` only; no merge without approval.
