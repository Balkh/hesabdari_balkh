# Stage 3.1 — Closure & Freeze Record
### Fiscal Period & Posting Date — the complete Phase 3 scope (§16.4)

> ## 🔒 STATUS: **APPROVED → FROZEN**
> **Frozen by explicit user verdict ("Approved") on 2026-09-12 18:34 UTC.**
> **Frozen commit:** `490ddba50358b207a856a7835667c899061ed120` (short `490ddba`)
> `fix(fiscal): enforce journal line balance on period close`
> Branch `phase/3` · `main` untouched at `646e35ed1982087d25ee99d65a6cf2c6b07e6a82`
> (CI run 34709157794, all four jobs success).
> From this point the Stage 3.1 surface is immutable. Any change to it
> requires an explicit **unfreeze ruling** from the user — never a silent edit.
> (Recorded by the agent on the user's instruction; the verdict itself is the
> user's, not self-declared.)

This document is committed as a docs-only record on `phase/3` (same
convention as the Phase 2 closure records). The frozen code commit remains
`490ddba`; this record changes zero lines of implementation.

---

## 1. Frozen surface

| File | Role |
|---|---|
| `backend/fiscal_periods/__init__.py`, `apps.py` | App registration |
| `backend/fiscal_periods/models.py` | `FiscalPeriod` + `PeriodStatus`, `start≤end` CHECK, `(start,end)` index |
| `backend/fiscal_periods/services.py` | Single posting-date gate + atomic lifecycle + audit + close validation (incl. FIX-1 actual-balance check) |
| `backend/fiscal_periods/migrations/0001_initial.py` | Minimal initial migration (creation only, no backfill) |
| `backend/fiscal_periods/period_tests.py` | 34 unit + integration tests (incl. G31-12 regression) |
| `backend/fiscal_periods/period_golden_tests.py` | 12 printed golden scenarios G31-01..G31-12 |
| `backend/config/settings/base.py` | One line: `INSTALLED_APPS += "fiscal_periods"` |
| `backend/accounting/services.py` | Exactly 3 added lines: 1 import + 2 gate calls (the single genuine frozen dependency, §26) |
| `docs/phase-reports/PHASE_3_STAGE_3.1_EVIDENCE.md` | Stage 3.1 evidence report (incl. FIX-1 section) |
| `docs/phase-reports/PHASE_3_STAGE_3.1_GOLDEN_OUTPUT.txt` | Golden-suite printout, 12 blocks |

Change scope measured from the green baseline `646e35e` → `490ddba`:
new fiscal app + tests + evidence, plus 4 added lines in 2 existing
files, **0 deletions, 0 alterations** anywhere. No frozen Phase 1/Phase 2
file was otherwise touched (models, balances, COA, FX, money, dates,
idempotency, security, documents, currencies, migrations `0001`–`0007`
all verified untouched; no frozen test modified).

## 2. Evidence at the moment of freeze (`EXECUTED` 2026-09-12 ~18:34 UTC)

```text
SQLite      pytest 292 passed   · Django runner 275 + 17 OK   · check OK · makemigrations clean
PostgreSQL  pytest 292 passed   · Django runner 275 + 17 OK   · migrate 0001 OK
            PostgreSQL 17.10 (Debian 17.10-0+deb13u1)
Fiscal new  46 passed (34 unit/integration + 12 golden) on BOTH backends
Golden      G31-01..G31-12, all PASS, 0 FAIL (pre-fix proof: G31-12 pair FAILED
            on old code, verified via temporary stash, fix restored byte-identical)
Frozen      246/246 Phase 2 tests green on BOTH backends, byte-identical
Frontend    build ✓ · 4/4 tests (untouched, verified during implementation)
Working tree clean; branch phase/3 at 490ddba
```

Chain of commits on `phase/3` at freeze:

```text
490ddba  fix(fiscal): enforce journal line balance on period close          ← FROZEN
48b782c  docs(evidence): record Phase 3.1 implementation evidence and golden output
d327b91  test(fiscal): add Phase 3.1 golden coverage (G31-01..G31-11)
a76bd62  feat(fiscal): implement Phase 3.1 fiscal period model, lifecycle and posting gate
646e35e  fix: restore executable bit on verify scripts                      ← green main, untouched
```

## 3. Frozen rulings carried by Stage 3.1

| Ruling | Content |
|---|---|
| **D1** (user-approved) | Empty period table → legacy-open/bootstrap posting allowed. From the first period on, every posting date must resolve to exactly one OPEN period; uncovered dates rejected with no fallback. |
| **R1** | Reversals obey the gate (same posting date); correction path for closed periods is reopen → reverse → close. |
| **R2/FIX-1** | Close verifies per-entry stored totals AND actual `Σdebit == Σcredit` from live line data; per-entry only, never cross-currency aggregation. |
| **R3** | Overlapping periods rejected at the service boundary (contract silent; ambiguity forbidden). |
| **R4** | Audit reuses frozen `CREATE`/`UPDATE` actions with full snapshots; zero `security/*` changes. |
| **R5** | Reopen/unlock require authenticated user + reason; close/lock require user; roles deferred to Phase 15 (§13.1 V1 single-user). |
| **R6** | Repeat transition to current state = audited no-op. |
| **R7** | No duration-shape enforcement; `closed_at` set on close, cleared on reopen/unlock. |
| **R8** | No future-date special-casing (recorded policy gap; no hard reject invented). |
| **R9** | No period FK on journals (date-based resolution; zero backfill, zero frozen model change). |

## 4. Explicitly NOT implemented (deferred — documented, not skipped)

Master data / party ledgers / AVCO / purchase / sales / payments /
returns / cash / exchange-house / remittance / printing / reporting /
tax / bank / unrealized FX / RBAC expansion / any UI or API endpoint for
periods (backend services only, Phase 2 precedent) / any Phase 4 work.

## 5. Phase 3 status — complete

| Stage | Commit | State |
|---|---|---|
| 3.1 — Fiscal period & posting date (§16.4 items 1–5) | `490ddba` | APPROVED → FROZEN |

Stage 3.1 is the complete Phase 3 scope per §16.4 (model,
OPEN/CLOSED/LOCKED, posting-date validation, reopen/unlock, historical
queries). Phase 3 (Fiscal Period Control) is therefore complete and
frozen by explicit user verdict.

## 6. Administrative items still open (do not affect the freeze)

1. Branch `phase/3` is local-only; merge to `main` (PR) happens only via
   the user's push flow and only when the user authorizes it.
2. PostgreSQL and the virtualenv live outside the workspace snapshot and
   are rebuilt per session; evidence above is from real execution, not
   simulation.
3. Snapshot restores may strip worktree executable bits and `.git/config`;
   git objects (the frozen commits) are unaffected.

## 7. Unfreeze rule

Any future change to the Stage 3.1 surface requires the user to state an
explicit **unfreeze** for Stage 3.1, naming the reason. Until then:

* the frozen surface (§1) is immutable;
* the documented rulings (§3) stand;
* new work — including any Phase 4 module — is a separate phase with its
  own INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW gate, built on
  top of (never instead of) the frozen foundations.

**No Phase 4 work has been started.**
