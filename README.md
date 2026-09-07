# hesabdari_balkh

Professional, offline-first, bilingual ERP foundation for an Afghan trading company.

## Phase 1 status

```text
FOUNDATION COMPLETE AND VERIFIED — all CI jobs green
```

Phase 1 delivered the complete technical foundation: Django backend, DRF API
boundary, currencies + historical exchange rates, Jalali/Gregorian date
boundary, Jalali-aware document numbering, double-entry journal foundation,
atomicity/idempotency infrastructure, security/audit foundation, and a
React/TypeScript frontend shell with Persian/English i18n and RTL/LTR.

Verification (GitHub Actions run 34149040085):

```text
✓ backend    Django check + 17 tests + 25 pytest
✓ frontend   tsc + Vite build + 4 node tests
✓ postgresql full foundation suite on a real PostgreSQL 16 server
✓ tauri      cargo check PASS (Tauri v2 desktop shell compiles)
```

Business workflows (purchasing, sales, inventory transactions, payments,
returns, remittance, reporting) are intentionally NOT implemented yet. They
start only after the Foundation is approved and the Phase 0 domain contracts
are defined.

Remaining open item: desktop installer packaging (`tauri build`) and the
Windows target are deferred until a suitable packaging environment is used.

## Planned stack

- Backend: Python, Django, Django REST Framework
- Database: PostgreSQL for deployment; SQLite is the approved local/offline
  development baseline (ADR-0002)
- Frontend: React, TypeScript
- Desktop: Tauri

## Development

See `docs/architecture/PHASE_1_BASELINE.md`, `docs/decisions/`, and
`.env.example`.

```bash
make verify        # local backend + frontend verification
scripts/verify_postgresql.sh   # full suite against PostgreSQL (needs a server)
```
