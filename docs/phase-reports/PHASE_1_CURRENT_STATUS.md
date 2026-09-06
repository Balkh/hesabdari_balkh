# ERP_Afghanistan / hesabdari_balkh — Phase 1 Current Status

Date: 2026-09-06

## Overall status

```text
IN PROGRESS / BLOCKED
```

The verified local foundation is healthy, but Phase 1 is not complete because Tauri build verification, PostgreSQL compatibility verification, and remote CI execution are still unavailable in the current environment.

## Verified locally

- Clean Git repository foundation
- Django backend foundation
- SQLite test database
- DRF API root and health endpoint
- Currency and historical exchange-rate foundation
- Central Jalali/Gregorian date boundary
- Document numbering foundation
- Double-entry journal foundation
- Atomic journal posting checks
- Idempotency reservation foundation
- API error envelope and request logging
- Authentication/permission foundation
- Audit event foundation
- React + TypeScript build
- Relative frontend API proxy
- Persian/English resources
- RTL/LTR shell
- Central design tokens and reusable primitives
- Local Django + Vite runtime integration
- Reproducible verification scripts

## Latest evidence

```text
Django system check: 0 issues
Django tests: 17 passed
Backend pytest: 25 passed
Frontend build: PASS
Frontend tests: 4 passed
Local runtime API health: PASS
```

## Blocking items

1. Rust/Cargo is not installed; Tauri `cargo check` and packaging are not tested.
2. PostgreSQL is not installed; SQLite is the approved current development database.
3. GitHub remote is configured but the initial push is blocked by missing authentication.
4. Complete Phase 1 end-to-end and desktop packaging verification remains pending.

## Boundary

No purchasing, sales, inventory transactions, payments, returns, remittance, or financial reporting workflows have been implemented. This is intentional for Phase 1.
