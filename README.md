# Hesabdari Balkh

Bilingual (English and Persian/Dari) ERP for an Afghan trading company.

## Repository status

This repository has progressed beyond the original Phase 1 foundation. The current `main` branch contains accounting, purchasing, inventory/costing, security, and sales-domain work. However, the presence of backend services and tests does **not** mean every business workflow is available through an end-to-end API or frontend.

Use the phase contracts, freeze records, pull requests, and exact-head CI evidence in this repository as the authority for the status and scope of each capability. In particular:

- Frozen accounting and inventory contracts must be preserved; posted financial history is corrected through the approved reversal mechanisms, not edited in place.
- Phase 8 Sales is not wholly complete or frozen. Its remaining fulfillment, custody-accounting, FUTURE-sale COGS, cancellation/reversal, and return decisions remain gated where the authoritative contract documents say so.
- Security batch freezes are limited to their recorded scope and do not constitute production-readiness approval.
- No production deployment, operational recovery capability, or full end-to-end ERP readiness should be inferred from passing CI alone.

For current implementation and decision status, start with `docs/phase-reports/`, the relevant phase contract documents, and the merged PR history. Historical reports should be read as records of their stated date, not as current status unless reaffirmed by a current authoritative record.

## Technology

- Backend: Python, Django, Django REST Framework
- Database: PostgreSQL for deployment; SQLite for local/offline development where specified by the project baseline
- Frontend: React, TypeScript
- Desktop: Tauri
- Languages and direction: English/Persian-Dari, RTL/LTR
- Date handling: Gregorian storage with Jalali presentation where specified by the contracts

## Development and verification

See `docs/architecture/`, `docs/decisions/`, the phase contracts, and `.env.example`.

```bash
make verify
scripts/verify_postgresql.sh   # requires a PostgreSQL server
```

CI results are tied to specific commits and should be checked on the exact PR head or `main` SHA under review. A green CI run is necessary evidence for code changes, but it does not replace accounting-owner review or approval of business contracts.
