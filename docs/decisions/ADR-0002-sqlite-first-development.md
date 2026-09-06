# ADR-0002: SQLite-first development

- Status: Accepted for current development stage
- Date: 2026-09-06

## Decision

Use SQLite for the current local development and foundation stage because PostgreSQL is not installed in the development environment and the application is intended to operate offline initially.

The domain and persistence code must avoid SQLite-only assumptions and remain portable to PostgreSQL. PostgreSQL integration will be a later verification step before a networked or production deployment.

## Consequences

- Foundation tests can run without a database server.
- SQLite is suitable for the current single-user offline development target.
- PostgreSQL compatibility must be checked before production/network deployment.
- This decision does not authorize changing Phase 0 accounting rules.
