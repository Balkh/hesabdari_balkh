# PHASE 6 — STAGE 6.3 — WAREHOUSE TRANSFER — EVIDENCE

## Baseline

```text
Branch: phase/4 — HEAD before: 8697768 (verified chain 2f65472→50625b4→8697768)
Working tree before: clean. CI scripts 100755 (stored + worktree).
6.1/6.2 present: receive/issue/open, AVCO replay, mapping, 66 tests, 2 migrations.
```

## Implementation

Files changed (3 code + this doc; NO migration — no schema change):

- `backend/inventory/models.py` — +2 constants only:
  `TRANSFER_SOURCE_TYPE="TRANSFER"`, `INVENTORY_TRANSFER_OPERATION`.
- `backend/inventory/services.py` — +`transfer_stock()` (+`_transfer_
  fingerprint`, `_resolve_transfer_retry`, `_execute_transfer`);
  module docstring updated (no longer "three only").
- `backend/inventory/inventory_tests.py` — +29 tests (66 → 95).

Architectural extension: transfer = one atomic operation posting
TRANSFER_OUT (source, at the issue-rule basis) + TRANSFER_IN
(destination, same basis, no FX) + the neutral reclass journal Dr
mapped-dest / Cr mapped-source via `post_journal`. Legs linked by
shared journal + reference + description + cost context; the operation
idempotency key lives on one `inventory.transfer` record (legs keep
`idempotency_key` NULL — that column is unique per row; discovered via
a caught `IntegrityError` during testing, fixed before evidence).
Journal number always system-assigned (no caller number ⇒ no test-29
class problem). Same-account mappings post a balanced wash journal
(uniform rule, documented). Basis branch mirrors `issue_stock`
(deliberate mirror — committed code not refactored).

Why accounting was implemented (§12): the approved 6.1 decision (§20)
defined this exact reclass; mapping is authoritative and tested; every
journal element (accounts/amount/currency/rate/numbering) resolves
from existing infra — zero invention required.

## Tests — SQLite

- Focused: `pytest inventory/inventory_tests.py -q` → **95 passed**.
- Full: `pytest -q` → **667 passed** (638 prior + 29 new).
- Django: `manage.py test` → Ran 17, OK. Check → 0 issues.
- Migrations: `--check` clean; fwd / zero / fwd OK (no new migration).

## Tests — PostgreSQL 17.11 (real server)

- Full: `pytest -q` → **667 passed**. Django runner → Ran 17, OK.
- Check → 0 issues.

## Accounting

Live demo (real output):

```text
JE JE-1404-00001 [TRANSFER/DEMO-T1] AFN rate=1.0000 afn=770000.00
  Dr=770000.00 Cr=0.00 1420 Secondary Warehouse
  Dr=0.00 Cr=770000.00 1410 Main Warehouse
A stock=400 avco=7700.0000 | B stock=100 avco=7700.0000
```

USD receipt (110 @ 70) → transfer at AFN AVCO 7700; journal AFN-only,
P&L-neutral, no COGS/Revenue/Expense/FX lines (asserted by
`test_no_pnl_cogs_or_fx`; accounts ⊆ mapped pair). Atomic with legs.

## Idempotency

`test_retry_returns_original_pair`: same key twice → same (OUT, IN)
pks; 2 movements / 1 journal total; 0 new audits on retry.
`test_retry_mismatch_rejected`: qty 150 and different-dest variants →
`InventoryValidationError`; journal count stays 1.

## Atomicity

`test_journal_failure_rolls_back_everything` (mocked `post_journal`
raise): 0 new movements/journals/audits/idempotency records.
`test_leg_failure_rolls_back_journal` (2nd leg raises): journal +
first leg + audits all rolled back.

## Immutability

`test_legs_immutable`: `save`/`delete` raise `PostedImmutabilityError`
(reused). `test_later_receipt_preserves_transfer_cost`: legs keep
10.0000 after 999/888 receipts.

## Audit

`test_audit_evidence`: per-leg CREATE with full snapshot (type,
warehouses, ±qty, before/after, description, journal link) + JE POST
event. `test_negative_acknowledgement_audited`: ack text in reason.

## Historical / AVCO

§21 scenario test: 100@10 + 50@20, transfer 50 → legs @ 13.3333; B
AVCO 13.3333; A AVCO 13.3334 (honest relief dust, commented).
Backdated transfer replays by (date, id); post-time basis preserved;
zero-reset interplay covered.

## Scope Protection

Changed: ONLY the 3 inventory files + this doc. Verified zero changes
under accounting, fiscal_periods, parties, categories, uom, products,
warehouses, cash_accounts, exchange_houses, currencies, documents,
security, core, scripts, .github, frontend. No new engines, no master
changes, no API/UI, no COA changes. Out-of-scope (§23) untouched.

## Git

Commit created per §30 (narrowly scoped, code + tests + this doc):

```text
feat(inventory): implement Stage 6.3 warehouse transfer
parent: 8697768 (exact hash in review report). No history rewrite.
No merge. No tag/freeze.
```
