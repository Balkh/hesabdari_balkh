# Phase 1 Baseline

## Date

2026-09-06

## Scope

This document records the first clean-repository increment for ERP_Afghanistan. No existing ERP repository was found in `/home/user`; only the attached planning document was present.

## Intended architecture

```text
Tauri -> React/TypeScript -> local Django REST API -> domain/application services -> PostgreSQL
```

The backend remains the authority for accounting, inventory, posting, validation, and data integrity. No business workflow is implemented in this baseline.

## Important open decision

The project brief describes an offline Windows deployment and the Phase 0 blueprint says SQLite initially / PostgreSQL-ready, while the Phase 1 prompt requires PostgreSQL. This baseline follows the explicit Phase 1 development requirement for PostgreSQL. The offline packaging choice must be resolved before database integration and packaging.

## Boundary rules

- No production business modules in this increment.
- No secrets committed.
- No claim of PASS without executed evidence.
- Empty domain directories are structural placeholders only; they are not implementations.
