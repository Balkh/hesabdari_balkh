# PHASE 2 — STAGE 2.2 EVIDENCE REPORT: Journal Contract + Money Precision

**Branch:** `phase/2`
**Base (frozen):** `9aef4d0` (Stage 2.1 FROZEN; `main` untouched at `846a777`)
**Date:** 2026-09-09
**Authoritative scope:** Stage 2.2 authorization + Phase 0 §1.8 / §3.11–3.12 / §16.4
**Status:** IMPLEMENTED · TESTED · EXECUTED · EVIDENCE READY · **AWAITING USER REVIEW**

Evidence classification: `EXECUTED` / `OBSERVED` / `VERIFIED` / `INFERRED` / `NOT VERIFIED` / `DEFERRED`.

---

## A. Scope — what was implemented

1. `JournalEntry`: `currency` FK→Currency (PROTECT), stored `total_debit`/`total_credit`,
   `afn_total`, rate snapshot (`rate` 4dp + `rate_date` + `rate_direction`), nullable
   `created_by` (SET_NULL). `EXECUTED`
2. `JournalLine`: optional `reference` (default `""`). `EXECUTED`
3. `backend/core/money.py`: the ONE rounding engine — Half-Up `line_total`,
   `cogs`, `fx_equivalent` (2dp), `normalize_rate`/`format_rate` (4dp),
   `to_decimal` (float rejected). `EXECUTED`
4. `post_journal`: currency required; base→rate 1 + AFN snapshot; foreign→rate,
   rate_date required + AFN equivalent via `fx_equivalent`; totals stored;
   line `reference` supported. All Phase 1 validation logic preserved. `EXECUTED`
5. `verify_entry_totals(entry)`: recomputes line sums, rejects mismatch/missing. `EXECUTED`
6. Migrations `0003_journal_currency_contract` (9 additive AddFields) and
   `0004_backfill_journal_totals` (totals from own lines; currency untouched). `EXECUTED`
7. 23 new tests: `core/money_tests.py` (6 incl. golden vectors),
   `accounting/journal_tests.py` (17 incl. legacy + reconciliation). `EXECUTED`

## B. Explicit non-scope

Idempotency keys, reversal, posted immutability (2.3); balances/trial balance/
traceability (2.4); FX realization (2.5); fiscal periods, master data, parties,
inventory, purchase, sales, payments, returns, cash/exchange, remittance,
printing, reporting, backup. None implemented or prepared. `DEFERRED`

## C. Baseline (frozen, verified at start)

```text
branch → phase/2 | HEAD → 9aef4d07931a00e0994c895a2a5a684bd0a92fba
status → clean except untracked docs/phase-0/
post_journal call sites → tests.py + coa_tests.py only; no journal API/views exist
```

`VERIFIED`

## D. Design decisions (frozen-contract impact — review carefully)

1. **Legacy currency is NULL, never fabricated.** Pre-2.2 rows get `currency/
   afn_total/rate/rate_date = NULL`, `rate_direction = ""`. Backfilling "AFN"
   would invent history (G6/G10). Only totals are backfilled (derived from the
   row's own lines). `OBSERVED` (design) + `EXECUTED` (migration demo, §H).
2. **`currency` is behaviorally required** (missing/inactive/non-Currency →
   `JournalValidationError`). Consequence: the 8 existing `post_journal` call
   sites in the FROZEN test files needed mechanical `currency=self.afn`
   additions — strictly-required 2.2 compatibility per the freeze memo.
   All frozen ASSERTIONS are byte-identical (proof: removed-lines audit in §K —
   only signatures, call lines, and one stale docstring line changed).
   `coa.py`, seed, COA oracle, old migrations: untouched. `VERIFIED`
3. **Single `afn_total`** (not a debit/credit pair): journals balance by G2, so
   one AFN figure is exact. `INFERRED`, documented.
4. **Direction format** `{SRC}->{BASE}` ASCII (`USD->AFN`; base journals
   `AFN->AFN`), computed by the service, never caller-supplied. `INFERRED`, documented.
5. **`created_by` SET_NULL**: journals must survive user deletion. `INFERRED`, documented.
6. **Base journals**: rate fixed `1.0000`, `rate_date` defaults to posting date
   (explicit override allowed), non-1 rate rejected. `EXECUTED`
7. **Foreign journals**: base currency must exist (else explicit error — no
   assumption); rate required, quantized 4dp Half-Up, must be > 0; `rate_date`
   required and preserved exactly (may differ from posting date, §3.6). `EXECUTED`

## E. Schema changes

- `models.py`: JournalEntry +8 fields, JournalLine +1 field (additive only).
- `0003_journal_currency_contract`: 9 × AddField, dependencies auto-resolved
  (accounting 0002, currencies 0001, auth user). No alters/deletes. `OBSERVED`
- `0004_backfill_journal_totals`: RunPython totals-from-lines + honest reverse
  (zero totals). `OBSERVED` + `EXECUTED` (§H).
- `makemigrations --check --dry-run`: `No changes detected`. `EXECUTED`

## F. Golden rounding vectors (all EXECUTED — `core/money_tests.py`, 6/6 pass)

```text
line_total(2, 10.005) = 20.01 | (1, 2.345) = 2.35 [banker's: 2.34]
(1, 2.325) = 2.33 [banker's: 2.32] | (2.5, 10.00) = 25.00
(3, 0.005) = 0.02 | (2, 3) = 6.00 | (0, 99.99) = 0.00
cogs(2, 1.2325) = 2.47 [banker's: 2.46] | (1, 10.004) = 10.00
(5, 2.00) = 10.00 | (1, 0.005) = 0.01
fx_equivalent(1000, 70) = 70000.00 [contract §1.12] | (1, 70.005) = 70.01 [banker's: 70.00]
(100, 68.5) = 6850.00 | (250.50, 70.25) = 17597.63 [banker's: .62]
normalize_rate(70) = 70.0000 | (70.00005) = 70.0001 [0.5-up at 4dp]
(70.00004) = 70.0000 | format_rate: 70 -> "70.0000", 68.5 -> "68.5000"
float/bool inputs -> TypeError (5 cases) | to_decimal("abc") -> InvalidOperation
```

## G. Journal contract tests (all EXECUTED — `accounting/journal_tests.py`, 17/17 pass)

AFN full snapshot · AFN explicit rate_date · USD Half-Up AFN (1.00 @ 70.005 →
70.01, rate 70.0050, rate_date ≠ posting date preserved, `USD->AFN`) · rate 4dp
quantization (70.00005 → 70.0001) · line reference stored/default · created_by
stored/nullable/invalid-rejected · currency required (None/str/int → error, 0
persisted) · inactive currency rejected · foreign requires rate+rate_date (missing/
zero/negative/garbage/float → error, 0 persisted) · base rejects rate≠1, accepts
explicit 1 · stored totals verified · corrupted totals rejected · missing totals
rejected · failed post persists nothing · foreign-without-base rejected ·
legacy readability + real-0004 backfill (totals filled, currency stays NULL,
draft 0/0) · 3-entry reconciliation (totals + AFN agree everywhere).

## H. Historical preservation (real migration execution on scratch DB)

Legacy journal written with the 0002 column set via raw SQL, then migrated: `EXECUTED`

```text
after 0003+0004: number=JE-OLD-1 status=POSTED desc=pre-2.2 journal
totals: debit=100.00 credit=100.00 | line sums: debit=100.00 credit=100.00
currency=None afn=None rate=None rate_date=None direction='' created_by=None
lines=2 refs=['', '']
reverse 0004 -> totals=0.00/0.00 lines=2 (journals/lines intact)
re-apply 0004 -> totals=100.00/100.00 lines=2
```

## I. Regression (all EXECUTED)

```text
manage.py check                    → 0 issues
manage.py test (Django)            → Ran 17 — OK (Phase 1 suite, assertions unchanged)
pytest (full)                      → 61 passed (38 frozen + 23 new), 0 failed
pytest money+journal               → 23 passed
makemigrations --check --dry-run   → No changes detected
npm run build / npm test           → ✓ built; 4 tests, 4 pass, 0 fail
PostgreSQL / Tauri                 → NOT EXECUTED (no server; backend-only change)
```

## J. Database integrity

- Every rejected post (12 failure probes across tests): entry count unchanged,
  attempted number absent. `EXECUTED`
- Seed-failure atomicity (2.1) still green; `post_journal` atomic block unchanged
  in structure (entry+lines created inside one transaction). `EXECUTED`
- Backfill touches only totals; reverse verified; no DELETE anywhere. `EXECUTED`

## K. Change scope proof

```text
M backend/accounting/models.py | M backend/accounting/services.py
M backend/accounting/tests.py (mechanical currency kwargs only)
M backend/accounting/coa_tests.py (+8/-1: import, 3 setups, 3 kwargs, 1 docstring)
?? backend/accounting/journal_tests.py | ?? migrations/0003_* | ?? migrations/0004_*
?? backend/core/money.py | ?? backend/core/money_tests.py
?? docs/phase-reports/PHASE_2_STAGE_2.2_EVIDENCE.md (this file)
shortstat (pre-report): 4 files, 112 insertions(+), 7 deletions(-)
removed-lines audit: ONLY the old post_journal signature+docstring, 4 single-line
  call sites (re-added with currency kwarg), 1 stale docstring line. Zero assertions removed.
coa.py, seed, old migrations, frontend, all other apps: UNTOUCHED (verified via git diff --quiet)
main branch: untouched at 846a777
```

## L. Known issues (genuine findings)

1. **Frozen-test mechanical updates** (§D.2): required, minimal, assertion-identical.
   Needs review acknowledgement, not rework.
2. **TECHNICAL DEBT (observed, not changed):** `post_journal` line amounts still use
   frozen Phase-1 `Decimal(str(...))` coercion (accepts float input like `0.1`),
   while `money.py` rejects float. Deliberately NOT aligned here (frozen behavior).
   Candidate for a future hardening stage with its own authorization.
3. **Test-artifact fix during development** (`EXECUTED`): `test_usd_post_computes_afn_half_up`
   first failed asserting `entry.posting_date == date(...)` on the in-memory instance
   (string passthrough is frozen behavior). Fixed by `refresh_from_db()` — now also
   proves DB round-trip. Product code was never at fault.
4. No blockers. No out-of-scope fixes made.

## M. Deferred work

Stages 2.3 → 2.4 → 2.5, each with verify→review→freeze; Phases 3–18 per §16.4.
No 2.3+ code written. `DEFERRED`

## N. Final status

```text
IMPLEMENTED
TESTED
EXECUTED
EVIDENCE READY
AWAITING USER REVIEW
```

(APPROVED / FROZEN / COMPLETE are the user's to declare — not claimed here.)
