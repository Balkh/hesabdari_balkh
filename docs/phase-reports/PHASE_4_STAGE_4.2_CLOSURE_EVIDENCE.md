# Phase 4 — Stage 4.2 Closure: APPROVED → FROZEN

**User verdict:** "Approved" — 2026-09-15 (recorded at freeze time below)
**Freeze time (UTC):** 2026-09-15T19:23Z
**Branch:** `phase/4` (local-only; `origin/main` unchanged @
`646e35ed1982087d25ee99d65a6cf2c6b07e6a82`)

## Frozen commits (code)

- `b2f1995e484fef7c9513ffc2446980394342f7b3` — feat: party master + 27 tests
- `6b47ff9c963b9d8227fd5446ca041380a073eb5d` — test: golden G42-01..G42-08

Prior frozen state (unchanged, re-verified green as part of the suite):
4.1 code `3602b07` + `5ef2e36` @ closure `60dfaf7`, and everything below
it. Decisions `a35402d` + evidence `c0a499f` + this closure doc are the
4.2 record commits.

## Freeze-time re-verification (freshly executed, all green)

| Check | SQLite | PostgreSQL 17.10 (real server) |
|---|---|---|
| `pytest -q` | 436 passed | 436 passed |
| `manage.py test` | Ran 17 — OK | Ran 17 — OK |
| `manage.py test --pattern="*_tests.py"` | Ran 419 — OK | Ran 419 — OK |
| `manage.py check` | 0 issues | 0 issues |
| `makemigrations --check` | No changes detected | n/a |
| Golden `-s` re-run | 8 PASS, 0 FAIL | n/a |
| Verify scripts | all four 100755 | n/a |

Note: this freeze needed zero environment repair — tree was clean, modes
intact, venv present, PostgreSQL online with role/db. Final targeted
verification (8/8 PASS) was separately executed and reported pre-approval.

## Frozen surface (4.2 additions on top of the 4.1 frozen surface)

- `backend/parties/` — model, services, 0001_initial migration,
  `party_tests.py` (27), `golden_tests.py` (G42-01..08).
- `backend/config/settings/base.py` — the single INSTALLED_APPS line.
- Interpretation record `PHASE_4_STAGE_4.2_DECISIONS.md` (FR-1..FR-9):
  Option A shared Party + boolean roles, dual-role allowed, ≥1-role
  invariant at service + DB layers, no code/numbering, name required +
  name_fa optional, inert contact trio, single is_active, financial
  layer deferred to Phase 5.
- No-`updated_at` inspection finding (real master convention has none).

## Remote CI honesty (unchanged fact)

```text
Remote CI for Phase 4.1: NOT RUN
```

Carried as the separate release/integration gate per user order. This
freeze claims local verification only — never remote execution.

## Unfreeze rule

Any change to the frozen surface above requires explicit user **unfreeze**
stating the reason — same rule as all prior phases. Merge to `main`, and
any Phase 4.3 work, are user-driven only.

**STAGE 4.2: APPROVED → FROZEN. STOP.**
