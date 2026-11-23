# W0-2E — Append-Only Audit and Hash-Chain Pre-Implementation Plan

**Date:** 2026-11-23  
**Status:** Read-only source inventory and implementation plan. No W0-2E application code, migration, setting, trigger, or runtime change is made by this document.  
**Contract:** Owner-approved W0-2A Item 5 and the technical contract in W0-2A §§8, 17–19, 21 and 23.  
**Implementation gate:** Do not start W0-2E code until the SQLite transaction-start decision and UQ-6/UQ-7 owner parameters below are resolved.

## 1. Current exact repository evidence

### 1.1 W0-2D latest branch/CI state

- Branch: `security/w0-2d-account-lockout`
- Exact current HEAD used by CI: `df248bd43a502c399d799363d1d7a58371c856f5`
- PR #60: open, Draft, unmerged; base is W0-2C branch `security/w0-2c-mfa-session-recovery`.
- Exact-head Actions run: [#45239547929](https://github.com/Balkh/hesabdari_balkh/actions/runs/45239547929) — completed, conclusion **success**, all seven jobs successful.
- Backend: 471 Django tests passed (2 skipped); pytest **1,385 passed, 17 skipped**.
- PostgreSQL 17.11: 471 Django tests passed; pytest **1,395 passed, 7 skipped**; verifier emitted `POSTGRESQL VERIFICATION: PASS`.
- Frontend, Tauri shell, Windows Server 2022 x64, Windows Server 2025 x64, and Windows 11 ARM64 jobs all succeeded.

This is CI evidence for W0-2D's exact source head, not an owner review, merge, freeze, physical Windows acceptance, or W0-2E evidence. PR #60 remains Draft and unmerged.

### 1.2 Existing audit schema and writer

At W0-2D HEAD, `backend/security/models.py` defines `AuditEvent` with these fields:

- `user`, `action`, `entity`, `entity_id`, `reference`;
- `previous_state`, `new_state`, `reason`; and
- `created_at`.

It does **not** yet contain `event_uuid`, `prev_event_hash`, `event_hash`, an actor-role snapshot, an authorization-context snapshot, or an audit-chain head.

`backend/security/services.py::record_audit_event()` is still a thin writer that directly calls `AuditEvent.objects.create()`. It validates the action string but does not create chain metadata, serialize a canonical payload, lock/update a chain head, or verify integrity.

The action field is still `CharField(max_length=20)`. W0-2D added the failed-login/lock/unlock actions through migration 0014 but did not implement the W0-2E action inventory or widen the field.

### 1.3 Existing business writer call sites

A GitHub source search against unchanged `main` SHA `6498f37c3b37fd802676a11fd8012b98bad1c754` identified at least 23 business service modules using the shared `record_audit_event()` contract:

1. `uom/services.py`
2. `parties/services.py`
3. `warehouses/services.py`
4. `categories/services.py`
5. `cash_accounts/services.py`
6. `exchange_houses/services.py`
7. `products/services.py`
8. `payments/services.py`
9. `fiscal_periods/services.py`
10. `purchases/services.py`
11. `accounting/services.py`
12. `goods_in_transit/services.py`
13. `customer_custody/services.py`
14. `party_ledger/services.py`
15. `inventory/services.py`
16. `sales/returns_services.py`
17. `sales/services.py`
18. `purchases/landed_cost_reversal.py`
19. `purchases/landed_cost_services.py`
20. `purchases/supplier_refund_services.py`
21. `purchases/landed_cost_posting.py`
22. `supplier_advances/services.py`
23. `allocations/services.py`

This is a discovery inventory, not yet a complete call-graph or transaction-boundary proof. The list must be re-run and reconciled against the exact implementation head immediately before migration work. It must also include any raw SQL, alternate managers, fixtures, bootstrap commands, and future modules that write audit rows.

### 1.4 Direct security audit producers added before W0-2E

Inspection of the current W0-2D branch shows at least 15 direct `AuditEvent.objects.create()` call sites outside the central writer:

| File | Direct writes | Events |
|---|---:|---|
| `security/auth_views.py` | 2 | successful login, logout |
| `security/mfa_service.py` | 5 | MFA enrollment/confirmation/disable and recovery-code lifecycle |
| `security/mfa_policy.py` | 1 | employee MFA policy change |
| `security/login_lockout.py` | 3 | failed login, account lock, GM unlock |
| `security/emergency_owner_key_service.py` | 2 | offline emergency owner-key lifecycle/recovery |
| `security/management/commands/bootstrap_gm.py` | 1 | initial GM bootstrap |
| `security/management/commands/issue_gm_bootstrap_token.py` | 1 | one-time bootstrap-token issuance |
| **Total** | **15** | |

All direct security producers must move through the same chain-aware writer. They cannot be left as a second append path. Audit events emitted by management commands must use the same chain protocol and be safe when no HTTP request context exists.

### 1.5 Legacy test/command compatibility

- `backend/accounting/test_bootstrap.py` currently deletes an audit event in `test_rerun_refuses_when_bootstrap_audit_event_is_missing` and updates an existing event's `action` in `test_rerun_refuses_when_bootstrap_audit_action_is_wrong`. Both violate the no-mutation/no-test-bypass contract once triggers are installed. Rewrite these tests to express their intent without mutating or deleting audit rows.
- The same test file contains legitimate INSERT-only fixtures for duplicate/orphan bootstrap markers. INSERT remains compatible with append-only protection, but fixture semantics must be reconsidered once all audit inserts require valid chain metadata.
- `backend/accounting/management/commands/bootstrap_fresh_database.py` reads the bootstrap marker and creates it through `record_audit_event()` inside its atomic bootstrap transaction. This is a critical first-database path: chain-head genesis/backfill must be initialized before the command writes the first new chained event.
- No test flag, setting, fixture, or database table may disable append-only triggers. Test databases must receive the protections through migrations.

## 2. Binding W0-2A technical design to implement

### 2.1 Event fields and canonical hash

W0-2A §18.2 specifies these required event fields:

- `event_uuid`: application-generated UUID, unique;
- `prev_event_hash`: 64-character lowercase SHA-256 hex digest; genesis uses 64 zeroes;
- `event_hash`: 64-character lowercase SHA-256 hex digest.

Uniqueness is required for event UUID, event hash, and previous-event hash. The immutable canonical payload must include every persisted immutable audit field other than the database primary key and the two chain fields. It must be versioned and deterministic: UTF-8 JSON, recursively sorted keys, compact separators, explicit nulls, no NaN/Infinity, UTC timestamps with fixed precision and a Z suffix, canonical Decimal/UUID encodings, and rejection of unsupported values rather than `repr()`.

The event digest is exactly:

```text
payload_bytes = canonical_json_bytes(versioned_immutable_event_payload)
previous_hash_bytes = bytes.fromhex(prev_event_hash)
event_hash = SHA256(
    b"HESABDARI-AUDIT-CHAIN-V1\x00"
    + previous_hash_bytes
    + payload_bytes
).hexdigest()
```

The previous hash must be part of the digest input. A per-database `AuditChainHead` singleton (fixed id=1) stores the current head hash and last event locator. The verifier follows hash links, detects missing events/forks/duplicate successors, recomputes each digest, and checks the head against the final verified event. Primary-key/timestamp ordering is not a substitute for link verification.

### 2.2 Actor and authorization context

W0-2A §8.2 requires historical interpretation to retain the actor identity and the role/permission context applicable when the event happened; current user roles must not be used as a substitute for historical context. The current `AuditEvent` schema stores only a user FK plus generic snapshots.

Before implementation, the schema/writer design must therefore specify and test an immutable actor/authorization context captured at write time. At minimum the design must identify:
- actor identity (including explicit system/anonymous actor semantics);
- role assignment context at that time;
- operation/permission context when the writer is invoked from an authenticated API operation;
- target/entity/reference and timestamp; and
- request-source metadata consistent with the privacy rules (no passwords, TOTP secrets, recovery codes, key material, or raw network address).

The snapshot must be captured in the same business/audit transaction and must not be retroactively reconstructed from today's assignments.

### 2.3 AuditAction inventory and field width

W0-2A §17 is binding:
- preserve the existing seven action values unchanged (`LOGIN`, `LOGOUT`, `CREATE`, `UPDATE`, `POST`, `REVERSE`, `APPROVE`);
- add the full §17.3 action inventory, including account lifecycle, role/permission changes, session/MFA/recovery, access lifecycle, `AUDIT_CHECKPOINT`, and `DELETE` where approved;
- widen `AuditEvent.action` to `CharField(max_length=40)` in the same migration; and
- enforce the UPPER_SNAKE_CASE naming convention and maximum length through tests.

The W0-2D values `LOGIN_FAILED`, `ACCOUNT_LOCKED`, and `ACCOUNT_UNLOCKED` must be reconciled with this full inventory. Existing historical `LOGIN` rows must not be rewritten merely to rename an action. New login success events should follow the finalized W0-2E action semantics.

### 2.4 Single audited append writer

One application service must be the only production write path:
1. enforce the action/payload schema and canonical serialization;
2. ensure the business operation already runs in the approved outermost transaction;
3. acquire the correct chain serialization boundary before reading the current head;
4. construct UUID, previous hash and event hash;
5. INSERT the fully chained event once (never INSERT then UPDATE the event);
6. update the singleton chain head in the same transaction; and
7. propagate any failure so the business mutation, audit event and head all roll back together.

No direct `AuditEvent.objects.create()`, `bulk_create()`, queryset update, delete, second writer, post-commit logging, or partial-transaction retry is permitted for production events.

## 3. Database concurrency and append-only protection

### 3.1 SQLite transaction-start gate

W0-2A §18.4 is explicit: SQLite's outermost transaction for **every audit-producing business operation** must begin with `transaction_mode="IMMEDIATE"` before any business/audit-head read. A late UPDATE inside `record_audit_event()` cannot upgrade an already-started DEFERRED transaction. Nested `atomic()` blocks are savepoints and do not change the outer transaction mode.

The current SQLite setting in `backend/config/settings/base.py` has no explicit `OPTIONS.transaction_mode`. Services use multiple outer transaction shapes, including `@transaction.atomic`, `with transaction.atomic()`, nested atomic blocks, idempotency wrappers and management commands. Therefore W0-2E must:
- inventory the true outermost callers for every audit-producing path (not merely the function that calls the writer);
- configure explicit SQLite busy timeout;
- prohibit entry into a supported audit-producing flow from an ambient DEFERRED transaction;
- retry only the complete outer business operation, and only when its idempotency contract permits it; and
- prove the boundary with real SQLite concurrency, unsafe-DEFERRED negative-control and rollback tests.

**Owner consent is mandatory before changing the global SQLite mode.** `transaction_mode="IMMEDIATE"` affects all outermost atomic transactions on that SQLite connection, including transactions unrelated to audit, and can reduce write concurrency. If the owner declines, implementation must stop and return with a different technically proven transaction-boundary architecture; it must not use a late UPDATE or claim a DEFERRED path is safe.

### 3.2 PostgreSQL writer serialization

For PostgreSQL, the singleton chain-head row must be updated/locked before the head is read, under the repository's tested READ COMMITTED behavior. Do not silently rely on this strategy under REPEATABLE READ/SERIALIZABLE. Concurrency tests must use independent database connections and verify one unbranched chain and exact head agreement.

### 3.3 Database triggers

Install vendor-guarded migration operations:
- SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers on `security_auditevent` using `SELECT RAISE(ABORT,...)`;
- PostgreSQL trigger function plus `BEFORE UPDATE OR DELETE` row trigger that raises an exception.

Insert is allowed only through the chain writer and must include all chain fields from the start. Trigger migration must be applied after any required data backfill and must have rollback-safe reverse SQL. No test/production bypass flag is allowed.

Migration, rollback/reapply, backup/restore, SQLite table rebuild and PostgreSQL trigger persistence must be explicitly tested.

## 4. Historical database migration and first-run behavior

Existing SQLite/PostgreSQL databases may already contain legacy `AuditEvent` rows without UUID/hash fields. The implementation plan must specify a safe one-time backfill:
- deterministic historical ordering for the unchained legacy set;
- event UUID and canonical payload generation for every legacy row;
- genesis link and sequential previous/event hashes;
- exact AuditChainHead initialization from the final backfilled event;
- migration locking/maintenance assumptions so no legacy writer races the backfill; and
- only then installation of append-only triggers.

New empty databases must initialize the genesis head before the first `bootstrap_fresh_database` / GM bootstrap / login event. Fresh install and existing-database upgrade paths must both be tested. If a pre-existing audit row cannot be canonicalized without inventing data, the migration must stop and report the affected row rather than silently drop/alter it.

## 5. Required tests and evidence

The W0-2A §18.6 minimum matrix is mandatory on both SQLite and PostgreSQL:

| Test | Required assertion |
|---|---|
| Concurrent PostgreSQL writers | Independent connections produce one unbranched chain; all hashes verify; head equals final event |
| Concurrent SQLite writers | IMMEDIATE outer transactions prevent stale-head/fork/partial-commit behavior; timeout is honored |
| SQLite unsafe DEFERRED negative control | A read-before-first-write DEFERRED path demonstrates the unsupported upgrade/race; no safe-path claim is made |
| Rollback injection | Business mutation, event insert and chain-head update all roll back together |
| Tampering fixtures | Changed payload/hash/link, deleted middle event, duplicate successor and fork are all detected by verifier |
| Cross-engine canonicalization | Same logical event produces identical canonical bytes/digest on SQLite and PostgreSQL |
| Existing business regressions | Audit rollback, idempotency, accounting golden tests and representative domain transactions remain intact |
| Trigger integration | INSERT succeeds through writer; ORM/raw UPDATE and DELETE fail; rollback/reapply preserves protections |

Additional required evidence:
- `makemigrations --check` clean;
- migration from both empty database and existing pre-chain fixture containing historical events;
- all writer call sites migrated and no unexplained direct production write remains;
- legacy mutation tests rewritten without bypass;
- chain verification command and health/startup diagnostic;
- signed offline checkpoint creation, verification, restore and key-custody proof; and
- explicit threat-model statement: unrestricted OS/database-owner access can still replace local database/files; hash chaining and offline signed checkpoints provide detection/resilience, not absolute protection against a fully privileged machine attacker.

## 6. Owner decisions required before implementation

### Decision A — global SQLite transaction mode

**Recommended:** approve `transaction_mode="IMMEDIATE"` for the SQLite desktop database connection, with an explicit busy timeout, fail-safe behavior and whole-operation retries restricted to idempotent operations. This follows the owner-approved W0-2A design and is the most direct implementation of the stated single-computer SQLite architecture.

**Trade-off:** all outermost SQLite atomic transactions acquire the write reservation at transaction start, not only those that eventually write an audit event. This can serialize writers earlier and reduce concurrency. We must test busy behavior and ensure read-only paths do not unnecessarily open atomic write transactions.

If declined, W0-2E is blocked until a different proven architecture is designed and demonstrated; a late audit-head UPDATE is not an acceptable substitute.

### Decision B — UQ-6 backup/checkpoint operations

W0-2A recommends a daily signed checkpoint and an additional checkpoint per work shift on high-activity days, but leaves retention and operational parameters to the owner. Proposed policy for owner review (not adopted):
- encrypted offline database backup at the end of each business day and before schema upgrades;
- signed audit-chain checkpoint daily and after each shift on high-activity days;
- retain daily backups for 30 days, plus one month-end copy for 12 months;
- perform a restore-and-chain-verification drill monthly on a disposable copy; and
- keep backup encryption/signing material separate from the live database and the ordinary user profile.

The retention periods, checkpoint cadence, backup destination and separate-key custody details require owner approval before implementation.

### Decision C — UQ-7 audit visibility and masking

**Recommended initial boundary:** GM-only audit review/export for W0-2E; no separate Auditor role or Accountant audit-report grant in this batch. Include actor/role/permission context, event action, timestamp, entity/identifier/reference, reason, and the permitted before/after snapshots needed for traceability. Never record or reveal passwords, TOTP seeds/codes, recovery codes, encryption keys, or raw IP addresses. Any later Auditor role must have an owner-approved category/field masking matrix and a separate permission review.

This recommendation preserves W0-2A's GM-only first audit report boundary; owner confirmation is still required for UQ-7.

## 7. W0-2E implementation gates

1. Owner resolves decisions A–C.
2. Finalize the caller/transaction inventory against the approved W0-2E implementation base SHA.
3. Implement canonical serializer, models and single writer; migrate every business/security writer.
4. Backfill historical events and initialize the chain head.
5. Install SQLite/PostgreSQL append-only triggers with no bypass.
6. Rewrite legacy mutation tests.
7. Implement verifier, diagnostics and signed offline checkpoint workflow.
8. Pass exact-head SQLite/PostgreSQL tests, concurrency/tamper/rollback/migration/restore evidence.
9. Present the complete PR to the owner for review. No merge/freeze until explicit approval.

---
**Scope statement:** This plan does not change application code or settings, does not approve the SQLite mode or backup/auditor parameters, and does not authorize the W0-2E implementation. It makes the known blockers and evidence requirements explicit so the next implementation batch does not guess at policy or weaken the audit boundary.
