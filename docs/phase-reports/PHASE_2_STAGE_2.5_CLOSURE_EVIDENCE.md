# Stage 2.5 — Closure & Freeze Record
### Realized FX Pattern + §1.13 Golden Suite — the final Phase 2 stage

> ## 🔒 STATUS: **APPROVED → FROZEN**
> **Frozen by explicit user verdict on 2026-09-10 19:51 UTC.**
> **Frozen commit:** `6817212b21dcccd646520f1ff979ce7907bb412b` (short `6817212`)
> `feat(accounting): persist manual FX settlement rate as structured transaction data`
> Branch `phase/2` · `main` untouched at `846a777438e1375331a7ce2821c9483ef5f77fc7`
> From this point the Stage 2.5 surface is immutable. Any change to it requires an
> explicit **unfreeze ruling** from the user — never a silent edit.
> (Recorded by the agent on the user's instruction; the verdict itself is the user's,
> not self-declared.)

This document is deliberately **untracked** (like
`PHASE_2_STAGE_2.4_CLOSURE_EVIDENCE.md`), so that the commit the user reviewed and
approved — `6817212` — remains the frozen commit and its SHA stays valid.

---

## 1. Frozen surface

| File | Role |
|---|---|
| `backend/accounting/fx.py` | Realized-FX calculation + posting; manual-rate conversion; structured-record persistence |
| `backend/accounting/fx_tests.py` | 95 tests (vectors, directions, validation, L1 manual rate, idempotency, rollback, reversal) |
| `backend/accounting/golden_tests.py` | 24 tests: 16 §1.13 goldens + R1–R5 regressions + R6A–R6C manual-rate blocks |
| `backend/accounting/models.py` | `FXSettlement` model (additive: 79 insertions, 0 deletions) |
| `backend/accounting/migrations/0007_fx_settlement_record.py` | Minimal additive migration (forward + reverse verified on PostgreSQL) |
| `docs/phase-reports/PHASE_2_STAGE_2.5_EVIDENCE.md` | Stage 2.5 evidence report (35 sections) |
| `docs/phase-reports/PHASE_2_STAGE_2.5_GOLDEN_OUTPUT.txt` | Golden-suite printout, 24 blocks, PostgreSQL |

Change scope measured from the Stage 2.4 baseline `ad5359b` → `6817212`:
**4566 insertions, 0 deletions.** No frozen file of Stages 2.1–2.4 was touched
(`coa.py`, `services.py`, `balances.py`, `core/money.py`, `core/idempotency.py`,
`core/dates.py`, `security/*`, migrations `0001`–`0006` all verified untouched).

## 2. Evidence at the moment of freeze (`EXECUTED` at 19:51 UTC)

```
SQLite      pytest 246 passed   · Django runner 229 + 17 OK   · check OK · makemigrations OK
PostgreSQL  pytest 246 passed   · Django runner 229 + 17 OK   · migrate 0007 OK · check OK
            PostgreSQL 17.11 (Debian 17.11-0+deb13u1)
Stage 2.5 focused  119 passed (95 FX + 24 golden) on BOTH backends
Golden suite       16/16 + 8 regression blocks = 24 blocks, all PASS
Frontend           npm test 4/4 · npm run build ✓   (npm ci re-run first)
Working tree       clean (tracked); only untracked docs remain
```

Chain of commits on `phase/2` at freeze:

```
6817212  feat(accounting): persist manual FX settlement rate as structured transaction data   ← Stage 2.5 (FROZEN)
ca59078  feat(accounting): complete Phase 2 Stage 2.5 realized FX                             ← Stage 2.5 implementation
ad5359b  feat(accounting): implement balances trial balance and source traceability           ← Stage 2.4 (FROZEN)
720ac03  feat(accounting): implement Phase 2 Stage 2.3 posting integrity                      ← Stage 2.3 (FROZEN)
ff03fce  feat(accounting): complete journal contract and money precision                      ← Stage 2.2 (FROZEN)
9aef4d0  docs(evidence): record Stage 2.1 conditional approval rulings                        ← Stage 2.1 (FROZEN)
53391be  feat(accounting): implement canonical chart of accounts
846a777  docs: mark Phase 1 foundation verified; record CI evidence for INC 22-24             ← main, untouched
```

## 3. Frozen rulings carried by Stage 2.5

| Ruling | Content |
|---|---|
| **L1** | The settlement rate is a **manual transaction-time rate**, persisted as structured data on the immutable `FXSettlement` row (`settlement_rate`, 4dp) with source/target currency + amount, direction, date and accounts. Never taken from the `ExchangeRate` table; never stored only in description/reference. `JournalEntry.rate` keeps its own `1.0000 / AFN->AFN` snapshot. |
| **L2** | Revenue posts to **4110**; `4100` stays a non-posting group account in the frozen COA. |
| **L3** | Trial balance / account balances are proven on single-currency fixtures (the frozen Stage 2.4 read layer refuses to merge currencies); FX scenarios are reconciled at entry level plus dedicated all-USD / all-AFN fixtures. |
| **L4** | Over-settlement (`settlement_amount > obligation_amount`) is rejected — V1 has no overpayment/advance semantics. |
| **L5** | Gain/loss accounts are locked to the canonical 8100 / 8200. |
| **Currency** | Cross-currency settlement is rejected; no hidden bridge journals, no silent conversion. The settlement journal is denominated in base-currency AFN book values. |
| **Rules** | The four realized-FX directions and the zero-FX rule are exactly as verified in the golden suite. |

## 4. Explicitly NOT implemented (deferred — documented, not skipped)

Unrealized / period-end FX revaluation (V2, §1.10) · cross-currency settlement ·
party subledgers and allocation (Phase 5) · AVCO engine (Phase 6) ·
purchase/sales/payment/return workflows (Phases 7–10) · exchange-house and
remittance ledgers (Phases 11–12) · printing (Phase 13) · reporting (Phase 14) ·
fiscal periods (Phase 3) · master data (Phase 4) · any UI.

No business document (Purchase, Sale, Customer, Supplier, Exchange House) is
created anywhere in Stage 2.5.

## 5. Phase 2 status — complete

| Stage | Commit | State |
|---|---|---|
| 2.1 — Canonical chart of accounts | `9aef4d0` | APPROVED → FROZEN |
| 2.2 — Journal contract & money precision | `ff03fce` | APPROVED → FROZEN |
| 2.3 — Posting integrity | `720ac03` | APPROVED → FROZEN |
| 2.4 — Balances, trial balance, source traceability | `ad5359b` | APPROVED → FROZEN |
| 2.5 — Realized FX + §1.13 golden suite | `6817212` | APPROVED → FROZEN |

Every stage was reviewed and frozen by explicit user verdict, one gate at a time.
Phase 2 (Accounting Core) is therefore complete.

## 6. Administrative items still open (do not block the freeze)

1. This document and `PHASE_2_STAGE_2.4_CLOSURE_EVIDENCE.md` are **untracked**;
   `docs/phase-0/` is untracked by design. If the user wants them in history, each
   becomes its own `docs(evidence)` commit — which must never be swept into a
   later stage's commit.
2. Commits `ff03fce`, `720ac03`, `ad5359b`, `ca59078`, `6817212` are **local
   only** — `git push` has no credentials in this environment. The user pushes, or
   provides an auth mechanism.
3. PostgreSQL and the virtualenv live outside the workspace snapshot; they were
   reinstalled for this evidence run and will not survive a snapshot restore.

## 7. Unfreeze rule

Any future change to the Stage 2.5 surface requires the user to state an explicit
**unfreeze** for Stage 2.5, naming the reason. Until then:

* `fx.py`, `fx_tests.py`, `golden_tests.py`, the `FXSettlement` model and
  migration `0007` are immutable;
* the documented rulings (§3) stand;
* new work — including Phase 3 (fiscal periods) — is a separate stage with its own
  INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW gate.

**No Phase 3 work has been started.**
