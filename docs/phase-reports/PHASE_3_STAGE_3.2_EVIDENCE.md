# Phase 3 — Stage 3.2 Evidence: Fiscal Period Operational/API Integration

**Date (UTC):** 2026-09-12T18:54Z
**Branch:** `phase/3` (local-only; `origin/main` unchanged @ `646e35e`)
**Commits:**
- `b520c1fabc4d9939b29f8512f9cdf265dc4bda30` — feat(api): thin REST boundary + 24 API tests (5 files, +568)
- `59e2438dd5f222e024fa8fadee87480b4d29d` — test(api): golden G32-01..G32-10 (1 file, +249)
- (this doc + golden output → docs commit, below)
**Parent chain:** `… → 2a52ae7 (3.1 closure) → b520c1f → 59e2438`

**Verdict: IMPLEMENTED per inspected scope — awaiting user review. NOT frozen, NOT merged.**

---

## A. Scope decision (from INSPECT — §8/§40)

Inspection found: zero backend `serializers.py` anywhere; only endpoints are
health/root/security-me (all function-based); auth = Session+Basic with
`IsAuthenticatedForERP` (anonymous → exactly 403, pinned by security tests);
the single error contract `{"error": {code, message}}`; frontend = foundation
shell with ZERO domain pages (its About page states business modules arrive
only after approved contracts).

Therefore Stage 3.2 = **thin DRF API only**. Manufacturing a full periods UI
(list/create/actions/i18n/RTL/forms) for the first and only domain module
would invent the app's entire UI feature architecture — exactly what the
stage prompt forbids. The frozen 3.1 services are now safely usable through
authenticated HTTP; a future UI consumes this API unchanged.

## B. What changed (new files + 1 line)

| File | Lines | Role |
|---|---|---|
| `backend/fiscal_periods/serializers.py` | 60 | Shape-only serializers; Jalali display via `core.dates` |
| `backend/fiscal_periods/views.py` | 120 | Thin delegation; domain errors → `http_400` shape |
| `backend/fiscal_periods/urls.py` | 11 | 6 routes (collection + 4 lifecycle actions) |
| `backend/config/urls.py` | +1 | `api/v1/fiscal-periods/` include |
| `backend/fiscal_periods/api_tests.py` | 376 | 24 API tests |
| `backend/fiscal_periods/api_golden_tests.py` | 249 | 10 golden scenarios |

Untouched (verified via `git status`): all frozen 3.1/Phase 2 files, all
migrations, all existing tests, frontend (0 diff), CI/scripts.

Single-source proofs: no second gate (posting still via `post_journal` only);
no status-write surface (no PUT/PATCH/DELETE anywhere → 405); no new auth,
audit writer, date utility, or error taxonomy — all reused. Write
serializers are plain `Serializer` (never model-bound).

## C. Executed evidence matrix (all green)

| Check | SQLite | PostgreSQL 17.10 (real server) |
|---|---|---|
| `pytest -q` | **326 passed** (292 frozen + 34 new) | **326 passed** |
| `manage.py test` | Ran 17 — OK | Ran 17 — OK |
| `manage.py test --pattern="*_tests.py"` | Ran 309 — OK (275 + 34) | Ran 309 — OK |
| `manage.py check` | 0 issues | 0 issues |
| `makemigrations --check` | No changes detected (no migration) | n/a |
| Golden `-s` capture | 10 PASS, 0 FAIL, G32-01..10 all present | n/a |
| Frontend (untouched) | npm test 4 pass / 0 fail; build ✓ | n/a |

Golden trail: `docs/phase-reports/PHASE_3_STAGE_3.2_GOLDEN_OUTPUT.txt` (50 lines).

## D. API contract (frozen by tests)

- `GET /api/v1/fiscal-periods/` → 200 array (authoritative order; Jalali fields)
- `POST /api/v1/fiscal-periods/` → 201 OPEN (+CREATE audit) | 400 shape | 403 anon
- `POST /api/v1/fiscal-periods/<pk>/{close,reopen,lock,unlock}/` → 200 (+UPDATE
  audit) | 400 domain message | 403 anon | 404 unknown id
- PUT/PATCH/DELETE anywhere on this surface → 405; no `status` write field exists
- Domain 400: `{"error": {"code": "http_400", "message": "<service message>"}}`
- Idempotent repeats (close→close) → 200 with NO new audit row

## E. D1 bootstrap (§5) + rollback/failure (§21/§28)

- Empty DB: repeated GETs return `[]` and create zero rows / zero audits (G32-10).
- First create via API → 201, enforcement from then on (service rule, cited as-is).
- Every 400 leaves DB + audit untouched (asserted per rejection test).
- Corrupt-journal close → 400, period stays OPEN, no close audit.
- Rollback: atomic service transactions; no partial writes observed in any test.

## F. Security (§10) + failure behavior (§28)

- Reused `IsAuthenticatedForERP`; anonymous → 403 on all 6 endpoints (G32-06),
  no rows/audits created. Reason-required actions reject blank with 400.
- No new roles/permissions (V1 single-user; roles = Phase 15, unchanged).
- Frontend: zero changes, zero new calls; `ApiError` shape already compatible.

## G. Forbidden-scope compliance (§14/§29)

No Phase 4/master-data/numbering work; no migration; no frozen-file edits
(`git status` shows only the 6 listed paths); no second engines; no UI
manufactured; no auto-freeze/merge. 3.1 evidence files untouched.

## H. Reviewer checklist (§37)

1. Endpoints behave per §D — see 24 API tests + golden trail.
2. Lifecycle truth stays in services — views contain zero rules (120 lines,
   inspectable); bypass tests prove no alternate path.
3. Errors uniform — every rejection asserts the `{"error"}` shape + code.
4. D1 intact — G32-10 + empty-state tests; no auto-creation anywhere.
5. Rollback/failure — §E; atomicity inherited from frozen services.
6. No scope creep — §G; diff is 6 paths, +817 lines, zero modifications
   outside the one include line.
7. Frontend untouched — `git status frontend/` empty; npm 4/0 + build ✓.
8. Evidence executed — every number above from real runs on 2026-09-12.

**STOP — awaiting explicit user review/approval. No freeze, no merge, no Phase 4.**
