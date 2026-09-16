# Phase 4 — Stage 4.1 Closure: APPROVED → FROZEN

**User verdict:** "Approved" — 2026-09-15 (recorded at freeze time below)
**Freeze time (UTC):** 2026-09-15T18:27Z
**Branch:** `phase/4` (local-only; `origin/main` unchanged @
`646e35ed1982087d25ee99d65a6cf2c6b07e6a82`)

## Frozen commits (code)

- `3602b07a1b3e5191384abc56c459187842819027` — feat: 3 apps + 65 unit tests
- `5ef2e36c172bca5d7db79118b677cec16cff4c15` — test: golden G41-01..G41-10

Prior frozen state (unchanged, re-verified green as part of the suite):
Phase 3.2 code `b520c1f` + `59e2438` @ closure `a43725e`, and everything
below it. Decisions `f007b50` + evidence `e5a3a9a` + this closure doc are
the 4.1 record commits.

## Freeze-time re-verification (freshly executed, all green)

| Check | SQLite | PostgreSQL 17.10 (real server) |
|---|---|---|
| `pytest -q` | 401 passed | 401 passed |
| `manage.py test` | Ran 17 — OK | Ran 17 — OK |
| `manage.py test --pattern="*_tests.py"` | Ran 384 — OK | Ran 384 — OK |
| `manage.py check` | 0 issues | 0 issues |
| `makemigrations --check` | No changes detected | n/a |
| Golden `-s` re-run | 10 PASS, 0 FAIL | n/a |
| Verify scripts | all four 100755, contents == recorded fix-mode hashes | n/a |

Note: the workspace snapshot had again stripped the verify-script
executable bits and wiped `backend/.venv`. Contents were proven identical
to the recorded fix-mode sha256 hashes, the approved mode fix re-applied,
venv rebuilt, tree clean — all BEFORE the runs above. PostgreSQL 17.10
with role/db survived this snapshot intact.

## Frozen surface (4.1 additions on top of the Phase 3 frozen surface)

- `backend/categories/`, `backend/uom/`, `backend/products/` — models,
  services, 0001_initial migrations, `*_tests.py`, golden tests.
- `backend/config/settings/base.py` — the single INSTALLED_APPS line.
- Interpretation record `PHASE_4_STAGE_4.1_DECISIONS.md` (U-1..U-4, R-1..R-12):
  no Category/UOM codes, flat categories, numeric-only 4dp reference prices,
  stored-never-applied factor/thresholds, recorded NON-decisions (R-4),
  domain-only (no REST), audit CREATE/UPDATE via existing writer.
- Fix-mode record: verify scripts at 100755 with frozen contents (zero
  content bytes changed; drift was environmental, twice observed).

## Unfreeze rule

Any change to the frozen surface above requires explicit user **unfreeze**
stating the reason — same rule as Phases 1–3. Merge to `main`, and any
Phase 4.2 work, are user-driven only.

**STAGE 4.1: APPROVED → FROZEN. STOP.**
