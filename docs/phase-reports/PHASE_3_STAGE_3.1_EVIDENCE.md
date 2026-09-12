# PHASE 3 — STAGE 3.1 IMPLEMENTATION EVIDENCE: Fiscal Period & Posting Date

**Branch:** `phase/3` (from green `main@646e35e`, CI run 34709157794 all-success)
**Contract:** `PHASE_0_CONTRACT_V2.1.md` §12 + §16.4/§16.5, user-approved D1 bootstrap rule
**Status:** IMPLEMENTED · TESTED · EXECUTED · EVIDENCE READY · **AWAITING USER REVIEW**
**No merge, no freeze claimed.** Phase 2 chain untouched (`9aef4d0→ff03fce→720ac03→ad5359b→6817212`).

---

## Scope

Fiscal Period model (OPEN/CLOSED/LOCKED), lifecycle transitions, one
authoritative posting-date gate enforced at the backend posting boundary
(`post_journal` + `reverse_journal`), atomic close with integrity
validation, reopen/unlock authorization + audit. No frontend, no API
endpoints, no admin screens (Phase 2 precedent: journals have none), no
CI changes, no Phase 4+ modules.

## Files

| Change | File | Purpose |
|---|---|---|
| NEW | `backend/fiscal_periods/__init__.py`, `apps.py` | App registration |
| NEW | `backend/fiscal_periods/models.py` | `FiscalPeriod` + `PeriodStatus`, `start≤end` CHECK, `(start,end)` index |
| NEW | `backend/fiscal_periods/services.py` | Gate + lifecycle + audit (reuses frozen `_as_date`, `verify_entry_totals`, `record_audit_event`, `utc_timestamp`) |
| NEW | `backend/fiscal_periods/migrations/0001_initial.py` | Minimal initial migration |
| NEW | `backend/fiscal_periods/period_tests.py` | 33 unit + integration tests |
| NEW | `backend/fiscal_periods/period_golden_tests.py` | 11 printed golden scenarios G31-01..G31-11 |
| EDIT (+1) | `backend/config/settings/base.py` | `INSTALLED_APPS += "fiscal_periods"` (single place, all profiles) |
| EDIT (+3) | `backend/accounting/services.py` | 1 import + 2 gate calls (the single genuine frozen dependency, §26) |
| DEL | `backend/fiscal_periods/.gitkeep` | Replaced by the real app |

Total diff on `phase/3`: **+1104 / −0** (implementation + tests;
evidence pair adds docs on top). Frozen behavior diff: exactly 3 added
lines in `accounting/services.py`, 0 removed, 0 altered.

## Database

- `fiscal_periods.0001_initial`: creates `FiscalPeriod` only. No data
  rewrite, no backfill (date-based resolution needs none), no historical
  migration touched.
- SQLite: forward + reverse + forward all OK; `makemigrations --check` clean.
- PostgreSQL 17.10: forward + reverse + forward all OK. Catalog proof:
  index `fp_start_end_idx` present; `CHECK ((start_date <= end_date))`
  present as `fiscal_period_valid_range`.

## Backend

- `assert_posting_date_open(date)` — the ONE gate (§19): OPEN→allow;
  CLOSED/LOCKED→reject; uncovered-with-periods→reject (D1: no fallback);
  empty table→allow, return None (D1 bootstrap, user-approved).
- `find_period_for_date` — ≤1 match by construction; multiple matches
  raise `Ambiguous` (never guessed).
- `create_period` (always OPEN; overlap rejected), `close_period`,
  `reopen_period`, `lock_period`, `unlock_period` — all `atomic()` +
  `select_for_update` + audit; only §8 transitions allowed; repeats are
  audited no-ops; reopen/unlock require authenticated user + reason.
- Close validation (§12.5): per-entry `verify_entry_totals` over
  POSTED/REVERSED journals in range (frozen L3 respected — no
  cross-journal currency summing; balanced entries imply a balanced
  range). First mismatch → `PeriodValidationError` → rollback.
- Reversals obey the gate (R1): correction path for closed periods is
  reopen → reverse → close. Posted immutability never weakened.

## Audit

Reuses frozen `AuditEvent` + `record_audit_event` (CREATE on create,
UPDATE on transitions) with user, UTC timestamp, entity/id, reference
(period name), previous/new state snapshots, reason, and
`journals_verified` count on close. No new audit table, no new actions
(zero frozen `security/*` changes).

## Frontend

Zero changes. Verified untouched: `npm run build` ✓, `npm test` 4/4.

## Tests (executed, SQLite)

```text
pytest -q                                   290 passed (246 frozen + 44 new)
manage.py test                              Ran 17 — OK
manage.py test --pattern="*_tests.py"       Ran 273 — OK   (229 frozen + 44 new)
manage.py check                             no issues
makemigrations --check                      No changes detected
```

New: 33 unit/integration (`period_tests.py`) + 11 golden
(`period_golden_tests.py`). One test-authoring bug found and fixed
during execution (overlapping fixture in the forbidden-transition
test); implementation untouched by the fix.

## Golden (executed, printed)

`pytest -s fiscal_periods/period_golden_tests.py` → **11 passed**,
11/11 `GOLDEN G31-xx` blocks printed, 13 PASS verdicts, **0 FAIL**.
Full printout: `PHASE_3_STAGE_3.1_GOLDEN_OUTPUT.txt` (this folder).

## PostgreSQL (executed, real server 17.10)

```text
check (postgres settings)                   no issues
migrate                                     fiscal_periods.0001_initial ... OK
pytest -q --ds=config.settings.postgres     290 passed
manage.py test                              Ran 17 — OK
manage.py test --pattern="*_tests.py"       Ran 273 — OK
migrate fiscal_periods zero → 0001          reverse OK, forward OK
```

## Rollback/Failure (executed)

- Tampered stored totals → close rejected, period stays OPEN,
  `closed_at` NULL, no close audit, tamper NOT repaired (test +
  golden G31-09).
- Audit outage (mocked) mid-close → exception → rollback, status OPEN.
- Post/reverse into CLOSED/LOCKED/uncovered → rejected, zero rows leaked.
- Invalid transitions (CLOSED→LOCKED etc.) → rejected, state unchanged.
- Migration reverse/forward on SQLite and PostgreSQL → OK both ways.

## Regression

All 246 frozen Phase 2 tests pass byte-identical on SQLite AND
PostgreSQL (bootstrap rule: they define no periods). Zero frozen test
files modified. Zero frozen migrations modified.

## Git

```text
d327b91  test(fiscal): add Phase 3.1 golden coverage (G31-01..G31-11)
a76bd62  feat(fiscal): implement Phase 3.1 fiscal period model, lifecycle and posting gate
646e35e  fix: restore executable bit on verify scripts   ← green main, untouched
```

Branch `phase/3`, local only (push via user flow). Scope: app + 2
minimal edits + tests + this evidence pair.

## Remaining issues / explicit interpretations (for review)

- D1 bootstrap (approved): empty table → allow; first period activates
  enforcement; no fallback afterwards.
- R1–R9 as inspected (reversal gated; per-entry close check; service-level
  no-overlap; CREATE/UPDATE audit reuse; authenticated-user auth, roles
  deferred to Phase 15; no-op repeats; no duration-shape enforcement;
  `closed_at` set on close, cleared on reopen/unlock; no future-date
  special-casing — policy gap, no hard reject invented).
- Known residual: close-vs-post race at the millisecond level (no period
  row lock on the post path — proportionate for V1 offline/single-user;
  hardening path documented: lock the covering row in `post_journal`).
- No Phase 4 work started. No unrelated refactors.
