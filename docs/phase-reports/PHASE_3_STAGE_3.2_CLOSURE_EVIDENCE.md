# Phase 3 — Stage 3.2 Closure: APPROVED → FROZEN

**User verdict:** "Approved" — 2026-09-13 (~03:25 UTC; recorded at freeze time below)
**Freeze time (UTC):** 2026-09-13T18:31Z
**Branch:** `phase/3` (local-only; `origin/main` unchanged @
`646e35ed1982087d25ee99d65a6cf2c6b07e6a82`)

## Frozen commits (code)

- `b520c1fabc4d9939b29f8512f9cdf265dc4bda30` — feat(api): thin REST boundary + 24 API tests
- `59e2438dd5f222e024fa8fadee87480b4d2d29d3` — test(api): golden G32-01..G32-10

Prior frozen state (unchanged, re-verified green as part of the suite):
3.1 code `490ddba50358b207a856a7835667c899061ed120` + closure `2a52ae7`.

Evidence commits: `2fea49d` (3.2 evidence + golden output) + this closure doc.

## Freeze-time re-verification (freshly executed, all green)

| Check | SQLite | PostgreSQL 17.11 (real server, reinstalled after snapshot restore) |
|---|---|---|
| `pytest -q` | 326 passed | 326 passed |
| `manage.py test` | Ran 17 — OK | Ran 17 — OK |
| `manage.py test --pattern="*_tests.py"` | Ran 309 — OK | Ran 309 — OK |
| `manage.py check` | 0 issues | 0 issues |
| `makemigrations --check` | No changes detected | n/a |
| Golden `-s` re-run | 10 PASS, 0 FAIL | n/a |

Note: the workspace snapshot had wiped `backend/.venv`, the PostgreSQL
installation, and the verify-script executable bits; all were rebuilt/
restored (mode-only script drift reverted via `git checkout HEAD --`,
contents identical) BEFORE the runs above. Tree was clean at freeze.

## Frozen surface (3.2 additions on top of the 3.1 frozen surface)

- `backend/fiscal_periods/serializers.py` — shape-only; Jalali via `core.dates`
- `backend/fiscal_periods/views.py` — delegation-only; domain errors → `http_400`
- `backend/fiscal_periods/urls.py` — 6 routes, no PUT/PATCH/DELETE surface
- `backend/config/urls.py` — the single include line
- `backend/fiscal_periods/api_tests.py` (24) + `api_golden_tests.py` (G32-01..10)
- API contract §D of the 3.2 evidence doc; D1 bootstrap rule; 403-anonymous;
  idempotent no-op repeats; `{"error": {code, message}}` convention.

## Unfreeze rule

Any change to the frozen surface above requires explicit user **unfreeze**
stating the reason — same rule as 3.1. Merge to `main`, and any Phase 4
work, are user-driven only.

**STAGE 3.2: APPROVED → FROZEN. STOP.**
