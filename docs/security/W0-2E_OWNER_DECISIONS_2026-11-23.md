# W0-2E — Owner Decision Record

**Decision date:** 2026-11-23  
**Decision authority:** ERP owner  
**Implementation base:** `security/w0-2d-account-lockout` at `df248bd43a502c399d799363d1d7a58371c856f5`  
**Work branch:** `security/w0-2e-audit-chain`  
**Status:** Owner-approved policy; implementation and verification remain pending.

This record captures the owner's explicit approval of all three W0-2E proposals. It does not claim that runtime code, backups, hash chaining, database triggers, or restore drills have already been implemented.

## Decision A — SQLite transaction start

**APPROVED.** Configure the SQLite connection with outermost transaction mode `IMMEDIATE` and an explicit busy timeout. Apply this at the connection settings layer, not as a late operation inside the audit writer.

Consequences and implementation constraints:

- This applies to every outermost SQLite `atomic()` transaction on the configured connection, not only to transactions that eventually emit audit events.
- The implementation must inventory transaction callers, avoid unnecessary atomic blocks around read-only work, and fail closed when an audit-producing operation is entered under an incompatible ambient transaction.
- Retry is permitted only by retrying the complete outer operation and only where the business operation has a proven idempotency boundary. Never retry only the audit append or chain-head update.
- Busy/locked behavior and timeout handling must be tested on SQLite. SQLite write reservation may be acquired earlier and writer concurrency may be reduced; this trade-off is accepted.

No production claim is made until the actual outer transaction boundaries and real SQLite concurrency tests have been verified.

## Decision B — backup and signed checkpoint policy (UQ-6)

**APPROVED.** Adopt the following operating policy:

1. Create an encrypted offline database backup at the end of each business day and before every schema upgrade.
2. Create a signed audit-chain checkpoint daily and after each shift on high-activity days.
3. Retain daily backups for 30 days and retain one month-end backup copy for 12 months.
4. Perform a restore-and-full-chain-verification drill monthly against a disposable copy, never by overwriting the live database.
5. Keep backup encryption and checkpoint-signing key material separate from the live database and the ordinary employee user profile.

Implementation must document the backup destination and owner-controlled custody procedure before enabling scheduled production backups. The repository must not silently store encryption/signing keys beside the database or in source control. Backup success is not established merely by producing a file; the restore drill and chain verification are required evidence.

## Decision C — audit visibility and masking (UQ-7)

**APPROVED.** W0-2E audit review and export are GM-only. Do not create an Auditor role or grant Accountant an audit-report permission in this batch.

The initial GM view may expose only the information required for traceability: event actor identity, event-time role/authorization context, action, timestamp, entity, entity identifier/reference, reason, and appropriately bounded before/after snapshots.

Never store or disclose passwords, TOTP secrets or codes, recovery codes, encryption keys, raw IP addresses, forwarded network headers, or user-agent strings. Any future Auditor role or Accountant audit visibility requires a separate owner-approved field/category masking matrix and permission review.

## Required implementation gates

- Preserve the W0-2D authentication compatibility contract; do not reorder or silently replace SessionAuthentication/BasicAuthentication behavior.
- All production audit producers must use one chain-aware append service. Direct ORM create/update/delete/bulk-write paths are not acceptable.
- Historical rows must be deterministically backfilled before append-only triggers are installed. If a row cannot be canonicalized without inventing or dropping data, the migration must stop and identify it.
- SQLite and PostgreSQL must both enforce UPDATE/DELETE rejection at the database layer.
- Canonical serialization, concurrency, fork/tamper detection, rollback atomicity, migration upgrade/fresh-install, restore, and trigger persistence must be covered by tests on both engines.
- The verifier must validate the linked chain and singleton head, not merely sort events by primary key or timestamp.
- OS/database-owner compromise remains outside the absolute prevention boundary; offline signed backups/checkpoints are intended to provide detection and recovery resilience, not an impossible guarantee against a fully privileged local attacker.

## Approval boundary

The owner has approved decisions A, B, and C and authorized W0-2E implementation work on the dedicated branch. This is not approval to merge, release, deploy, or freeze. Any such transition still requires exact-head evidence and a separate explicit owner decision.
