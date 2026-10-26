# Security Batch 2 — Freeze Record

## Status

FROZEN by owner declaration (Balkh, review chat, 2026-10-26).
Recorded in the shared audit worklog at 2026-10-26T18:17:01Z.

Lifecycle completed: INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → **FROZEN**.

## Frozen content

| Item | Value |
|---|---|
| Frozen commit | `12c8581e2d747be8d0244796775b7ec02fd2b64f` (current `main`) |
| Frozen tree | `62eacdfdd8e2019b5f12f367832b4820469f1771` |
| Source PR | #43 "Security Batch 2: production fail-safe and auth regression tests" |
| PR head reviewed | `f84a29d163a564c5e6c71d16915969048503d366` (tree **identical** to the frozen tree — byte-for-byte) |
| PR base | `e9ef0436fdebce68dcd12f895e67aa024d2f8500` |
| Merge | squash, by `Balkh`, 2026-10-26T18:03:18Z |
| Changed files | 6 files, +238/−3 |

## Evidence at freeze time

- CI run [40232743152](https://github.com/Balkh/hesabdari_balkh/actions/runs/40232743152) on the reviewed PR head `f84a29d`: backend, frontend, postgresql, tauri — all SUCCESS.
- CI run [40374311974](https://github.com/Balkh/hesabdari_balkh/actions/runs/40374311974) on post-merge `main` `12c8581`: backend, frontend, postgresql, tauri — all SUCCESS.
- Local verification matrix on `f84a29d`:
  - `scripts/verify_backend.sh` EXIT 0 — Django runner 80 tests OK (1 skip); pytest 989 passed / 9 skipped.
  - `scripts/verify_postgresql.sh` EXIT 0 on local PostgreSQL 16.2 — runner 80 OK (0 skips); pytest 998 passed (the 9 PostgreSQL-only concurrency tests ran).
  - `manage.py makemigrations --check --dry-run` clean.
  - `manage.py check --deploy` with production settings: only the two intentional HSTS warnings (security.W005, security.W021) retained from the owner-approved Batch 1 decision.

## Scope frozen by this record

Batch 2 security scope only, as reviewed:

1. Explicit `DJANGO_SETTINGS_MODULE` requirement for WSGI/ASGI startup (fail-fast; `manage.py` keeps its local-development default).
2. Production `SECRET_KEY` guard: rejects the development-only default, empty, and sub-50-character values; the key is never logged.
3. Production `STATIC_ROOT` (`<BASE_DIR>/staticfiles`) for `collectstatic`.
4. Real HTTP Basic authentication regression tests (valid + invalid credentials, no `force_authenticate`), including the pinned deterministic 403 mapping.
5. Session-authentication CSRF regression test pinning the `CSRF Failed` mechanism.
6. Negative production-startup subprocess tests for missing `DJANGO_SETTINGS_MODULE` (WSGI/ASGI) and short `DJANGO_SECRET_KEY`, plus the fixture-pinning test for the 50-character minimum.
7. `docs/operations/PRODUCTION_DEPLOYMENT.md` — deployment preconditions documentation.

All pre-existing frozen accounting and business contracts (double-entry, journal immutability, reversal-only corrections, Phase 8 Sales, Phase 10B cross-currency settlement, Phase 11 costing) are untouched by Batch 2 and remain frozen under their own records.

## Explicitly out of scope (verified at audit)

No accounting/domain logic changes, no migrations, no remittance/hawala functionality, no RBAC/JWT/OAuth/MFA, no frontend authentication, no Redis/shared cache, no admin login throttling, no dependency changes, no CI workflow changes.

## Known limitations carried forward (Batch 3 candidates — owner-gated)

1. Remaining F-10 negative-path tests: missing `POSTGRES_*`, `DJANGO_DEBUG=true`, empty `ALLOWED_HOSTS`, missing `DJANGO_SECRET_KEY`.
2. Admin exposure / application-level admin login throttling strategy.
3. Shared-cache decision for multi-worker throttle counters (current local-memory cache is per-process).
4. Real TLS termination, reverse-proxy header hygiene, and static-file serving verification — deployment-dependent, NOT VERIFIED.

These follow-ups do NOT invalidate this freeze; they are enhancements requiring separate owner-approved scope. **Batch 3 must not begin until this record is merged.**

## Not claimed by this record

Passing CI and the verification matrix prove code-level contracts only. No production infrastructure (TLS, proxy, DNS, static serving, real deployment) exists or has been verified. This freeze is not a production-readiness claim.
