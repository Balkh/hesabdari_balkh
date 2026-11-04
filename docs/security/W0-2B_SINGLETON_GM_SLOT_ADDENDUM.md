# W0-2B / R2 — Singleton GM Slot Addendum (Owner Decision: At Most ONE Active GM)

**Branch:** `security/w0-2b-r2-enforcement` (PR #57 — Draft/Open; not merged, not frozen)
**Base main:** `6498f37c3b37fd802676a11fd8012b98bad1c754`
**Scope:** additive implementation of the binding owner decision below. The approved W0-2A architecture document on `security/w0-2a-rbac-architecture` (`e0d7db4505b7c04b1093c07e953aa4b1a3944f1d`) is NOT edited by this addendum.

## 1. Owner decision implemented

**At most ONE user may hold the active General Manager (GM) role in the entire ERP at any time.**

- Zero active GM users are permitted during initial setup or a controlled recovery interval; two active GM users are never permitted.
- The policy is global — never per department, warehouse, device, or organization unit.
- A second user must never receive GM merely because they are a Django superuser or staff user.
- Existing GM role assignments are reconciled without silently choosing an account.

## 2. Why a singleton slot

Role rows alone cannot express "exactly one holder": `UserRoleAssignment` is a temporal grant table and cannot enforce a global cardinality of one. The new `security.GMRoleSlot` is a fixed-identity database singleton:

- `code` is unique and check-constrained to exactly `"GM"` → at most one slot row can exist.
- `assignment` is a nullable `OneToOneField(UserRoleAssignment, PROTECT)` → at most one holder; one assignment cannot be linked twice; deleting a linked assignment is database-blocked.
- `NULL` assignment is a VALID state (fresh system / controlled recovery interval).
- The slot is the authoritative identity of the single GM holder; nothing in this batch overwrites, clears, or transfers it.

## 3. Resolver behavior (linked vs unlinked)

`security/authorization.py` — the ten-step sequence is unchanged; only GM recognition is re-based onto the slot:

- Step 5 recognizes GM ONLY through the slot's linked assignment: the linked row must belong to the requesting user, carry the ACTIVE `GM` role, and satisfy the existing §14.2 ACTIVE predicate evaluated on the LINKED row.
- An ordinary unlinked `UserRoleAssignment(role=GM)` grants NO protected GM capability and NO GM permission keys (the GM role is excluded from the ordinary role-grant union; `_gm_capability_keys()` is unioned only for the proven slot holder).
- Fail-closed: missing/corrupt slot, missing/wrong linked assignment, wrong or inactive role, revoked/expired/not-yet-effective link → "not GM"; unexpected database errors reach the resolver's FAIL_CLOSED boundary. Missing slot does not break non-GM authorization paths.
- Non-GM roles (Accountant, Warehouse Keeper) are unchanged; the R1 key-only resolver's early protected-GM decision semantics are preserved once a valid holder is established; R2 operation-aware target validation still runs before a GM allow.

## 4. Migration 0005 (additive; 0001–0004 untouched)

`security/migrations/0005_gmroleslot.py`:

1. Creates the singleton slot row with no assignment.
2. Inspects all non-closed GM assignments (`role__code="GM"`, `revoked_at IS NULL`) left by history.
3. Zero candidates → slot stays empty (expected before provisioning).
4. Exactly one currently ACTIVE candidate → linked through a CAS update that only fires while the slot is empty.
5. More than one candidate → the migration STOPS with an actionable error (run `manage.py gm_slot_preflight`). It never picks the lowest ID, earliest account, or first superuser; the atomic migration rolls everything back.
6. No historical `UserRoleAssignment` row is deleted, rewritten, merged, or silently revoked. Reverse removes only the slot structure/record and preserves all assignment rows.

Read-only operator preflight: `manage.py gm_slot_preflight [--database alias]` reports all non-closed legacy assignments and separately counts currently ACTIVE candidates used for migration readiness, plus per-candidate user IDs and safe account status fields (`is_active` / `is_staff` / `is_superuser`, temporal window, grant reason) and whether migration can proceed automatically. It never prints passwords, tokens, TOTP secrets, recovery codes, usernames, or e-mails, and exits non-zero when manual reconciliation is required.

System check `security.E004` (registered with `Tags.database`) enforces post-migration slot consistency: missing slot row, invalid/duplicated identity, non-GM or revoked link, a linked assignment outside its temporal ACTIVE window (expired or not-yet-effective), and any currently ACTIVE GM assignment not represented by the slot. The same temporal-inactivity finding is emitted by `gm_slot_preflight`; it exits non-zero and requires manual reconciliation. Neither check modifies or clears the slot. A valid EMPTY slot on a database with no GM provisioned is NOT an error. A database on which `security.0005` is not yet applied is skipped entirely (unmigrated state — the pending migration owns the reconciliation), so the check never pre-blocks the linking migration.

Bootstrap guard alignment: `security.GMRoleSlot` joins the §24.5 migration-seeded reference models in `bootstrap_fresh_database` (its row is written by 0005 on every migrated database, operator-independent). The user-specific assignment/override/scope models keep blocking first-time bootstrap.

## 5. Concurrency strategy

`security.gm_slot.claim_gm_slot(assignment)` is the only writer:

- Fresh re-read + validity verification (active GM role, non-closed, temporally ACTIVE).
- Claim via a single conditional update — `UPDATE ... WHERE code='GM' AND assignment IS NULL` — a database-atomic compare-and-set. Exactly one competing claim succeeds; a repeated claim by the same assignment is idempotent; an existing holder is never overwritten.
- Conflict raises the domain-specific `GMSlotClaimError`. The helper owns a nested `transaction.atomic()` block/savepoint: it rolls back its own block. If the caller created the assignment inside an outer atomic block, that outer work is rolled back only when the exception propagates out of the outer block (or the caller explicitly rolls it back there). Catching and suppressing the exception inside the outer block allows work created before the helper savepoint to commit. A grant service must preserve propagation/rollback semantics and test them explicitly. `select_for_update()` alone is deliberately NOT relied upon.
- Engine-neutral: on SQLite the write is serialized database-wide; on PostgreSQL the loser blocks on the winner's row lock and re-evaluates the predicate against committed state (READ COMMITTED) → clean domain conflict.
- Evidence: threaded two-connection tests run on SQLite (invariant: never two holders) and — following the repo's concurrency-test convention — a `skipUnless(postgresql)` strict test asserting exactly one `claimed` + one `conflict` outcome, executed against real PostgreSQL (locally PostgreSQL 16.2 smoke; CI job = PostgreSQL 17.11).

## 6. Deferred (NOT in this batch)

- First-run GM account creation / provisioning endpoint (none exists; the slot is created empty).
- GM recovery, password reset, MFA/TOTP, sessions, recovery codes (W0-2C/W0-2D).
- GM transfer/revocation/grant services; Django Admin activation (W0-2E and later). Expired/future linked assignments are now detected as E004/preflight consistency failures, but no automatic slot clearing, recovery, or transfer is introduced by this diagnostic fix.
- Permission-denial audit persistence; production enforcement activation (ERP_RBAC_ENFORCEMENT stays False; the production startup guard remains unimplemented on this branch).
- Single-vs-multiple recovery operators, physical/OS-level recovery design — owner decisions still open.

**This implementation does not create or recover the GM account.** First-run provisioning, MFA, recovery, and GM-only Admin are NOT complete and are not claimed here.
