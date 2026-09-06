# ERP_Afghanistan

Professional, offline-first, bilingual ERP foundation for an Afghan trading company.

## Phase 1 status

**BLOCKED** — clean baseline created; technical dependencies and Phase 0 approval are still required before implementation of business workflows.

## Scope of this baseline

This increment creates the repository structure, documentation locations, environment configuration strategy, and verification scaffolding. It intentionally does not implement purchasing, sales, inventory transactions, payments, returns, remittance, or reporting workflows.

## Planned stack

- Backend: Python, Django, Django REST Framework
- Database: PostgreSQL for the Phase 1 development baseline; SQLite remains a future offline deployment decision
- Frontend: React, TypeScript
- Desktop: Tauri

## Development

See `docs/architecture/PHASE_1_BASELINE.md` and `.env.example`.
