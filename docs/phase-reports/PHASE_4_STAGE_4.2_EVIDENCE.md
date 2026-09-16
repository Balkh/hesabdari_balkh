# Phase 4 — Stage 4.2 Evidence: Party Master (Option A — Shared Party + Roles)

**Date (UTC):** 2026-09-15T19:06Z
**Verdict: PHASE 4.2 IMPLEMENTED → TESTED → EVIDENCE RECORDED →
WAITING FOR USER REVIEW. No approval/freeze/merge claimed.**

## Repository

```text
Branch: phase/4 (local-only; origin/main unchanged @ 646e35e)
Base:   60dfaf7 (4.1 FROZEN — untouched)
HEAD:   6b47ff9 (after C1+C2; this doc → C3)
```

Commits: `a35402d` docs(decisions incl. FR-1..FR-9 + gate-lift note) →
`b2f1995e484fef7c9513ffc2446980394342f7b3` feat (8 files, +500/−1) →
`6b47ff9c963b9d8227fd5446ca041380a073eb5d` golden (+129).

## Implementation

```text
Party model: backend/parties/models.py — ONE table, no relations
fields:      name (req) + name_fa (opt) + is_customer/is_supplier
             (default False) + phone/address/note (opt free text)
             + is_active (default True) + created_at
constraints: party_name_nonblank + party_has_role (customer OR supplier)
validation:  PartyValidationError; blank/non-text/type guards; role
             invariant re-checked on final flags at update; idempotent
             no-op updates create no audit rows
audit:       CREATE/UPDATE via existing record_audit_event (entity Party)
```

No code, no numbering, no currency/balance/ledger, no FKs, no
serializers/views/urls, no admin, no frontend — per FR-4/FR-8/FR-9 and
the contract-silence discovery (no API requirement exists).

`updated_at` inspection note (§3): the prompt listed it "per real repo
convention", but inspection proves NO master has `updated_at` (it exists
only on the document `NumberSequence` row). Per §3's own rule — real
convention wins, invent nothing — Party follows the 4.1 master shape
(`created_at` only), same pattern as the FR-5 names ruling the user
accepted. Additive later if ever required.

## Tests (executed, real numbers)

```text
SQLite:
  pytest -q                                    436 passed (401 frozen + 35 new)
  manage.py test                               Ran 17 — OK
  manage.py test --pattern="*_tests.py"        Ran 419 — OK (384 + 35)
  manage.py check                              0 issues
  makemigrations --check                       No changes detected
  focused parties (unit + golden)              35 passed (first run green)
  migration parties zero→0001→zero→0001        OK

PostgreSQL 17.10 (real server, role/db verified):
  pytest -q --ds=config.settings.postgres      436 passed
  manage.py test                               Ran 17 — OK
  manage.py test --pattern="*_tests.py"        Ran 419 — OK
  manage.py check                              0 issues
  migration parties zero→0001→zero→0001        OK

Golden G42:  G42-01..G42-08 — 8 PASS, 0 FAIL
             (trail: PHASE_4_STAGE_4.2_GOLDEN_OUTPUT.txt, 29 lines)
```

New suites: `party_tests` 27, `golden_tests` 8 → 35 total.

## Scope (untouched — verified via git status/diff)

```text
Phase 1 untouched:        YES (zero diff)
Phase 2 untouched:        YES (accounting/money/FX/journal/posting/balances)
Phase 3 untouched:        YES (fiscal periods + API boundary)
Phase 4.1 untouched:      YES (categories/UOM/products + migrations)
Frontend untouched:       YES (zero diff)
Dependencies untouched:   YES
CI workflow untouched:    YES
```

Only changes: `parties/` app (7 new paths) + 1 INSTALLED_APPS line +
4.2 docs. No forbidden §5 module touched (no code/ledger/balance/
invoice/payment/inventory/CRM/tax/API/UI of any kind).

## Git

```text
git status:      clean (at C1+C2; this doc + golden txt → C3)
git diff --check: clean (exit 0)
commit:          b2f1995 feat + 6b47ff9 golden (+ a35402d decisions)
```

## CI (honest status — §21)

```text
Remote CI for Phase 4.1: NOT RUN
```

4.2 implementation was explicitly authorized by user order while the
remote gate stays open. Local verification above is complete and green;
nothing here claims remote execution. 4.1 freeze/lock status unchanged.

**STOP — awaiting explicit user review/approval. No freeze, no merge,
no 4.3, no ledger, no inventory, no accounting integration.**
