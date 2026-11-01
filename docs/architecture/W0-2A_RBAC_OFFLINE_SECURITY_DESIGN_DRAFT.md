# W0-2A — RBAC Architecture & Offline Security Design Contract

**Repository:** `Balkh/hesabdari_balkh`  
**Baseline:** `main` at `99579d99f4b7c668118ad7e2add2a2ef91d04fba`  
**Working branch:** `security/w0-2a-rbac-architecture`  
**Status:** FIVE DESIGN ITEMS OWNER-APPROVED; ACCOUNTANT ROLE EXPANSION OWNER-APPROVED; TECHNICAL MODEL MAPPING AND IMPLEMENTATION PLAN REMAIN OPEN; OWNER REVIEW PENDING  
**Date:** 2026-10-31  
**Revision 2:** 2026-10-31 — technical design correction, pushed to the working branch for owner review.  
**Revision 3:** 2026-10-31 — documentation-only corrections to the audit hash-chain and SQLite transaction contract.
**Revision 4:** 2026-10-31 — documentation-only corrections to mandatory object-scope enforcement, Django Admin GM-only access, MFA/BasicAuthentication interaction, resolver fail-closed behavior, SQLite transaction consistency, and stale evidence. No application code, model, migration, API, frontend, test, settings, or runtime behavior changes. No PR, merge, deployment, or implementation authorization.
**Revision 5:** 2026-10-31 — documentation-only complete permission-scope audit: evidence-backed registry of all 162 keys (§15A: scope policy, source, basis, resolver context, evidence, status per key), Warehouse Keeper matrix reconciliation, seed-total recount with corrections, evidence-error corrections (including the `sales.refund.*` misclassification), and stale-evidence repairs. No application code, model, migration, API, frontend, test, settings, or runtime behavior changes. No PR, merge, deployment, or implementation authorization.

## 1. Purpose and boundary

Define a minimal, additive architecture for identity, role-based authorization, per-user access, offline GM authentication/recovery, session controls, and security audit.

This document does not authorize code changes to authentication behavior, API permissions, database schema, frontend routes, or deployment. W0-2A implementation starts only after this design is reviewed and explicitly approved.

Security Batch 2 and Batch 3 remain frozen and unchanged. Existing accounting, inventory, document, posting, reversal, and audit contracts remain authoritative. No authorization design may bypass domain invariants, including posted-document immutability.

## 2. Verified baseline observations

At the baseline SHA above:

- Django's default User model is in use; no custom `AUTH_USER_MODEL` was found in the inspected settings.
- DRF uses SessionAuthentication followed by BasicAuthentication.
- `IsAuthenticatedForERP` checks authentication only; it does not resolve roles or action permissions.
- Existing `AuditEvent` and `record_audit_event()` provide an audit foundation.
- The existing audit model has no demonstrated database-level append-only protection.
- The security API currently exposes `/api/v1/security/me/`; no ERP login, logout, password-recovery, MFA, user-administration, or session-management API was found in the inspected routes.
- The frontend currently has no login screen, auth context, or route-level permission guards.
- Base settings configure Django's default LocMem cache for throttling; Batch 3 explicitly characterized this behavior. Redis/shared-cache adoption is not part of this workstream.

These are baseline observations, not claims about any later commit. **[Rev 2]** All baseline claims re-verified independently during this revision (see §13.3).

## 3. Deployment target — one standalone offline computer

The current target is one standalone computer with no internet dependency and no multi-computer/LAN access.

Required properties:

- Frontend, Django backend, PostgreSQL database, authentication, authorization, audit, and backup/restore operate locally.
- No mandatory Google/SSO, cloud identity, internet API, email, or SMS service.
- No LAN/public listener by default. Backend binding and browser/Tauri origin/transport details must be verified during implementation planning; do not assume a network topology not yet tested.
- Local authentication, password changes, MFA enrollment/verification, account recovery, and user administration remain usable offline.
- Local audit and backup/restore remain functional offline.
- TOTP authenticators on a mobile phone can generate codes offline; reliable local clock time is required.
- Any future multi-computer, LAN, or internet deployment requires a separate security review and owner approval.
- Offline operation does not remove the need for a controlled, authenticated offline software/security-update procedure; that procedure remains a later operational design item.

## 4. Identity and role foundations

### 4.1 Identity

Retain Django's default User model (owner decision D1). Do not introduce a custom user model or replace Django authentication absent a demonstrated technical blocker and separate owner approval.

Every employee has an individual account. Shared employee accounts are prohibited. Account lifecycle actions must be attributable and audited.

**[Rev 2]** User hard-deletion is outside the ERP domain by design: users are **deactivated** (`is_active=False`), never deleted. All foreign keys that reference users in authorization tables use `PROTECT` (§14.8). This preserves authorization and audit history permanently.

### 4.2 Initial roles

The initial role catalog is limited to:

- **GM** — General Manager.
- **Accountant** — accounting/finance duties, subject to an explicit permission matrix.
- **Warehouse Keeper** — warehouse/inventory duties, subject to an explicit permission matrix.

Role names are approved. The initial Accountant permission matrix is owner-approved as a broad operational role, as amended in the owner decision record below. Exact permission keys, object scopes, and per-user configuration must still be mapped during implementation planning. Warehouse Keeper remains limited to warehouse duties unless the GM explicitly grants additional per-user permissions.

Django Admin is GM-only (owner decision D5). Employee workflows must be provided through controlled ERP interfaces, not Django Admin. This is a server-side gate, not a navigation/UI rule; see the binding AdminSite contract in §5.1.

**[Rev 2]** The exact permission-key catalog is now defined: §15 (162 keys across 20 domains; seeds GM = 150, Accountant = 101, Warehouse Keeper = 12). **[Rev 5 correction]** Recount with row-level audit: seeds GM = 152, Accountant = 102, Warehouse Keeper = 12 (§15.4); scope registry: §15A.

### 4.3 Proposed additive authorization entities

Subject to implementation review, prefer additive models referencing Django User:

- **Role** — stable role identity and active state.
- **Permission** — stable machine key for a specific resource/action.
- **RolePermission** — permission granted to a role.
- **UserRoleAssignment** — user-to-role assignment with effective dates and actor/audit metadata.
- **UserPermissionOverride** — explicit per-user allow/deny, optional start/end time, reason, granting actor, and revocation metadata.
- **TemporaryAccess** — if not represented directly by dated overrides, a separately auditable bounded grant with automatic expiry. **[Rev 2]** Resolved (UQ-2): represented by time-bounded dated rows on `UserRoleAssignment`/`UserPermissionOverride`/`UserWarehouseScope`; no separate `TemporaryAccess` model. Temporal semantics fully specified in §14.

Avoid duplicate permission engines or using Django Groups as a second competing source of truth. A final model mapping must be chosen before migration creation. Historical actor/role/permission context must be preserved for past audit events. **[Rev 2]** Final model mapping: §14 (six additive models; supersedes the open model questions of Revision 1).

### 4.4 Authorization evaluation

Default decision is **deny** unless a valid permission is positively established. The owner selected deny precedence for conflicts (D3), and GM authority is protected from ordinary employee overrides.

The owner-approved resolver ordering and edge cases are specified in Section 9A, Item 2. Implementation must encode those semantics exactly and test explicit user deny vs role grant, explicit user allow, multiple-role union, protected GM authority, expiry/revocation, and hard domain invariants.

Authorization must be enforced on the backend for every protected operation. Frontend hiding/disabled controls are usability only and never security boundaries. Object-level checks are required wherever access depends on ownership, assigned warehouse, document state, or another business boundary.

Permission checks must not bypass accounting/business-service validation. Existing API 403 behavior for denied protected requests is preserved (D6); do not change frozen Batch 2/3 authentication behavior.

**[Rev 2]** The technical encoding of the resolver — including the corrected evaluation sequence (authentication and account/session validity strictly before any permission-grant lookup), conflict rules, and fail-closed handling — is specified in §16. It implements Item 2 exactly; it does not change it.

## 5. GM authority and employee administration

GM has full ERP administrative authority within hard domain invariants. GM may create and approve the GM's own operations; a second approver is not required. No ordinary per-user deny/override may remove protected GM authority.

### 5.1 Binding Django Admin access contract (Revision 4)

Django Admin access MUST be checked by a custom `AdminSite.has_permission()` (or equivalent centralized server-side gate) on every admin request. Require authenticated user, `is_active=True`, an active GM role assignment at the current time, and `is_staff=True` only as an additional Django admission flag—not as the authorization decision. Non-GM staff is denied. `is_superuser=True` MUST NOT bypass the GM-role check. Inactive or locked GM is denied.

Apply the same GM gate to admin index, app/model permissions, changelist, add/change/delete/history, autocomplete, actions, custom admin URLs, and exports. Tests: non-GM staff denied; non-GM superuser denied; active GM staff admitted; inactive/locked GM denied; direct/custom URLs denied for non-GM; actions cannot bypass the gate. Provisioning sets `is_staff` only for GM; never use `is_superuser` to grant ERP authority. Inspect and explicitly reconcile existing superuser accounts before enabling this gate.

GM's authority remains subject to hard accounting/document invariants.

GM administration must eventually support:

- Create, activate/deactivate, and manage individual employee accounts.
- Assign/change/revoke roles.
- Grant/review/revoke/extend temporary access.
- Review account activity, security events, failed logins, and active sessions.
- Unlock accounts and terminate sessions.
- Record employee departure/role-change handover and revoke old access.

Django Admin access is restricted to GM. Exact bootstrap and account-management UI/API details are to be specified before their implementation batch.

## 6. Authentication, MFA, and sessions

- GM MFA is mandatory; employee MFA is configurable by GM (D2).
- **BasicAuthentication/MFA boundary:** DRF `BasicAuthentication` verifies username/password only and MUST NOT be a complete authentication path for protected ERP operations after MFA is introduced. W0-2A leaves the current stack untouched. Before W0-2C enables GM MFA, inventory every route accepting BasicAuthentication and prove Basic-only requests cannot reach protected ERP operations. Protected sessions must be established only after password + required MFA (or another separately owner-approved MFA-bound mechanism). Do not silently alter frozen Batch 2/3 behavior; any auth-class transition requires route-by-route compatibility review and owner approval.
- Offline-capable TOTP is the preferred MFA direction; no internet validation service.
- Strong password validation is required.
- Failed logins are recorded; lockout is configurable and GM-reviewable.
- Idle timeout and pre-expiry warning are configurable.
- Multiple sessions may be allowed, but sessions/devices must be visible, auditable, and terminable by GM.
- Permission revocation and account deactivation must take effect promptly, including termination/invalidation of affected sessions where required.
- Preserve 403 for denied protected requests (D6); do not change Batch 2/3 status-code contracts.
- The numeric defaults in Section 9A, Item 4 are owner-approved starting values. Any change requires an explicit owner decision.

## 7. GM account provisioning and easy recovery

No hardcoded/default GM password, hidden master password, permanent bypass, or internet-based recovery.

### 7.1 First-run provisioning

- Use a controlled local first-run setup flow with a one-time setup capability.
- The setup capability must be unpredictable, short-lived, single-use, and invalidated permanently after successful GM provisioning.
- Require the GM to set a strong password and enroll MFA during setup.
- Generate recovery codes and present them once for offline safekeeping.
- Do not leave an unauthenticated setup endpoint active after provisioning.

Exact local bootstrap mechanism (installer token vs. locally authorized setup utility) requires technical validation before implementation.

### 7.2 Recovery paths

**Forgot password, mobile authenticator available:** local recovery flow verifies username and current TOTP, allows password reset, invalidates existing sessions, and records the recovery event.

**Mobile lost, password still available:** verify password plus one unused single-use recovery code; revoke the old MFA enrollment; enroll a replacement authenticator; invalidate relevant sessions; issue a new recovery-code set.

**Password and mobile both lost:** require physical/local access plus a separately stored offline emergency owner recovery key. Use a controlled one-time recovery utility to reset password, revoke old MFA and sessions, enroll new MFA, and write an auditable recovery record. The emergency key is not a routine login credential and must not create a permanent backdoor.

### 7.3 Recovery-code/key protection

- Generate 10 single-use recovery codes; display/print once; store only secure hashes in the database (owner-approved direction).
- Used codes are invalidated; reissuing a set invalidates all previous unused codes.
- Store the emergency owner key separately from the computer, in a protected offline location.
- Protect TOTP secrets encrypted at rest. Encryption-key handling must be designed with OS secure storage/TPM where available and must include a documented recovery/backup strategy.
- Database backups alone may not be sufficient if encryption keys are required; key recovery material must be handled separately and securely.
- If the database is unavailable during emergency recovery, preserve a protected local recovery record and reconcile it into the central audit after database restoration.

The three recovery paths are the accepted direction; exact UX, key custody, cryptographic implementation, and recovery testing remain technical design items.

## 8. Audit and integrity

- Keep the existing AuditEvent foundation unless inspection proves it cannot meet the contract.
- Audit sensitive security actions, including successful/failed login, logout, account lifecycle, role/permission changes, temporary access, MFA enrollment/revocation, recovery, session creation/termination, and denied sensitive operations by authenticated users (D8).
- Record actor identity and the role/permission context applicable at the time; do not rely only on the user's current roles for historical interpretation.
- Audit records must be append-only and protected at the database level (D7). Exact database enforcement mechanism must be selected and tested for SQLite development and PostgreSQL deployment. **[Rev 2]** Design specified in §18–§19, including the corrected concurrency protocol and a strict no-test-bypass rule.
- Ordinary application permissions must not allow audit deletion or mutation.
- Audit failure behavior for sensitive actions must be explicit and fail safely; never silently omit required audit events.
- Do not change existing financial audit semantics without a separate impact review.

## 9. Offline operational controls and remaining policy parameters

Accepted requirements:

- Local/offline backup and recovery capability (D12).
- Trusted-origin policy (D13).
- Restrictive Content Security Policy for future Tauri packaging (D14); Tauri packaging is not current scope.
- Restricted read-only auditor access (D11).
- Local/shared-cache capability considered in architecture (D10); do not assume Redis is needed for the one-computer deployment.

Still to specify before implementation:

- Backup frequency, retention, encryption, restore verification, and separate key custody. *(UQ-6 — deferred to W0-2E; see §21.)*
- Exact trusted local origins and browser/Tauri origin strategy. *(UQ-8 — deferred to W0-2F; see §21.)*
- CSP directives for the eventual deployment/package. *(D14 — future scope.)*
- Auditor-visible data categories and masking rules. *(UQ-7 — deferred to W0-2E; see §21.)*
- ~~Exact audit database protection mechanism and cross-database test strategy.~~ **[Rev 2]** Resolved at design level: §18 (hash-chain concurrency) and §19 (append-only protection, no test bypass).
- ~~Numeric lockout/idle/session values and clock-drift policy.~~ **[Rev 2]** Corrected: numeric defaults were already owner-approved in §9A Item 4; what remains is implementation mapping, deferred to W0-2C/D.
- ~~Final permission taxonomy and role matrix.~~ **[Rev 2]** Resolved: exact catalog registry in §15 (162 keys / 20 domains).
- ~~Final resolver precedence details and multi-role conflict semantics.~~ **[Rev 2]** Resolved: technical encoding in §16 (Item 2 semantics unchanged; ordering corrected so grant lookup never precedes authentication/account/session checks).

## 9A. Owner-approved concrete security decisions — five items

The five items below were explicitly approved by the owner in the conversation on 2026-10-31. The Accountant permission matrix was subsequently amended and approved by the owner on 2026-10-31 as recorded in Section 9C. These decisions are approved policy boundaries; implementation details explicitly marked open still require technical validation and must not be invented in code.

*(Sections 9A, 9B, and 9C are owner-approved records and are reproduced verbatim; Revision 2 does not modify their policy content. Technical encodings live in §14–§20.)*

### Item 1 — Initial permission taxonomy and role matrix (owner-approved, with Accountant amendment)

Use action-level permission keys in the form `<domain>.<resource>.<action>`. Permission catalog is explicit and default-deny. UI visibility never implies API authorization.

| Domain / action | GM | Accountant | Warehouse Keeper |
|---|---:|---:|---:|
| Dashboard and operational summaries | Full | Full operational and finance summaries within assigned permissions | Warehouse summaries only |
| Customers / suppliers / party master data | Full | Create, view, edit, and manage operational master data | View minimum fields needed for warehouse execution |
| Chart of accounts, currencies, exchange rates, fiscal periods | Full | View and perform routine maintenance only where explicitly delegated; structural accounting configuration and period lock/reopen remain GM-controlled unless separately authorized | No access |
| Sales documents | Full | Create, view, edit, submit, and post eligible operational sales documents when the user's permission allows; manage routine sales workflow | View assigned fulfillment data; perform authorized warehouse handover/release steps only |
| Purchase documents and supplier settlements | Full | Create, view, edit, submit, and process routine purchase/supplier workflows; payment execution remains subject to explicit treasury permission and controls | View minimum receiving data; record physical receipt and quantity/condition evidence |
| Journals, posting, reversal, trial balance, financial reports | Full within immutable accounting rules | Create/manage journal drafts; view balances, trial balance, and reports; post eligible routine entries only when explicitly permitted; posted history remains immutable and reversal/correction is controlled | No access |
| Inventory, stock movements, receiving, transfers, counts | Full | Full routine inventory and warehouse operations, including receiving, movements, transfers, counts, and physical handover, subject to assigned scope and stock controls | View assigned warehouse; record receipts, movements, counts, and release execution |
| Cash, bank/exchange-house, treasury, reconciliation | Full | Record/manage routine receipts and payments and prepare treasury/reconciliation operations; execution, settlement, and reconciliation permissions are individually configurable by GM | No access |
| Approvals / evidence review | Full; GM may approve own operations as owner-approved | Perform operational reviews and evidence completion; cannot approve own submitted item where workflow requires independent approval; additional approval rights only by explicit GM grant and workflow rules | No financial/document approval; may confirm physical evidence |
| Cancel / reverse posted financial or stock history | Full authority to initiate approved correction only; never direct edit/delete of posted history | Cancel eligible unposted documents with reason; prepare and, only if explicitly delegated, execute controlled reversal/correction workflows. Never directly edit/delete posted history | No |
| Print / export / download | Full | Operational, financial, party, and warehouse documents needed for assigned duties; bulk export and sensitive data export remain separately permissioned | Assigned warehouse operational documents only; no financial export |
| User, role, permission, session, MFA, recovery, security administration | Full | No | No |
| Audit/security logs | Full | Restricted read-only finance-relevant subset only if separately granted | No |
| Django Admin | GM only | No | No |

**Important constraints:**

- GM's full administrative authority never bypasses accounting/domain invariants, evidence gates, immutable posted records, or reversal-only correction.
- Accountant receives broad operational permissions across finance, sales, purchases, parties, inventory, warehouse, and routine company administration. High-impact permissions (treasury execution, structural accounting configuration, period close/reopen, bulk export, sensitive security administration, and posted-history reversal) remain individually configurable/restricted by GM.
- Warehouse Keeper remains focused on warehouse execution; all unlisted actions are denied.
- The Accountant role may perform routine posting and operational approvals only where the action is part of the approved workflow and the user's explicit permission allows it. Treasury execution, period close/reopen, bulk export, user/security administration, and reversal of posted history are not blanket grants of the role.
- Access to sensitive customer/employee data must be field- and purpose-limited where supported.
- Object-level scope (assigned warehouse, assigned documents, permitted parties) must be enforced server-side.
- Any additional role or permission requires a documented owner-approved matrix change.

### Item 2 — Resolver precedence and multiple roles (owner-approved)

Recommended deterministic resolver:

1. Inactive user, inactive account, expired session, or missing authentication: deny.
2. Protected GM authority: grant only the protected GM administrative capability set; it cannot be removed by ordinary user overrides. Domain invariants still apply.
3. For non-GM users, an active explicit user **DENY** overrides every role grant.
4. Otherwise, an active explicit user **ALLOW** grants the permission.
5. Otherwise, active role grants are combined additively (union of grants).
6. If no active role grants the permission, deny.

Additional rules:

- Expired, revoked, future-dated, or inactive role assignments/overrides are ignored.
- Multiple active roles combine by union; any explicit user DENY still wins.
- A user ALLOW may add a permission absent from their roles, but cannot override a user DENY or a hard domain invariant.
- Temporary access is an explicit time-bounded ALLOW, with mandatory reason, granting GM, start/end timestamps, and audit trail; explicit DENY and domain invariants still win.
- All decisions must be explainable in a diagnostic trace (subject, action, object scope, matched rule, result), without exposing secrets to the frontend.
- Unknown permission keys, malformed scope, and resolver errors fail closed.

This owner-approved resolution satisfies D3 deny precedence while preserving explicit per-user grants.

**[Rev 2]** §16 is the binding technical encoding of Item 2. It adds the explicit step ordering (authentication → account state → session validity → protected GM → explicit deny → explicit allow → role union → scope → default deny), places the permission-key catalog lookup strictly after the first three steps so unauthenticated callers learn nothing about the catalog, and adds the `ACCOUNT_LOCKED` account state from Item 4's approved lockout semantics. No approved rule is weakened.

### Item 3 — GM first-run bootstrap and recovery key custody (owner-approved direction; implementation details open)

**First-run bootstrap:**

- Use a local management command, not an always-open public setup endpoint.
- The command creates a cryptographically random, one-time setup token, stores only its hash, and displays it once.
- Token expires after 10 minutes, can be used once, and is invalidated on successful setup or expiry.
- A loopback-only local setup screen consumes the token to set the GM password and enroll mandatory TOTP; the application refuses all subsequent setup attempts once the GM is provisioned.
- If local browser origin/loopback isolation cannot be proven in the actual packaging, use a local CLI provisioning utility instead. Do not expose bootstrap over LAN.
- No hardcoded password or default credentials.

**Recovery:**

- Issue 10 random single-use recovery codes at initial setup; show/print once; persist only strong salted hashes. Each successful use consumes one code; regeneration revokes all previous codes.
- Store one separate high-entropy emergency owner recovery key offline, on paper or removable offline media, in a sealed location separate from the computer. It is used only with physical/local access through a controlled recovery utility, never for routine login.
- Forgotten password + working TOTP: verify TOTP and reset password.
- Lost phone + known password: verify password plus one unused recovery code, revoke old TOTP, enroll replacement, rotate recovery codes.
- Lost password + lost phone: physical/local recovery utility plus emergency owner key; reset password, revoke old MFA and all sessions, enroll new MFA, issue new recovery codes, and create a high-severity audit record.
- No email/SMS/cloud dependency and no permanent master password/backdoor.

**Encryption and backup key custody:**

- Encrypt TOTP secrets at rest using authenticated encryption; never store plaintext TOTP seeds.
- Keep the encryption key outside the ordinary database where OS-protected secret storage is available (Windows DPAPI/Credential Manager or equivalent OS facility). Validate availability on the actual target OS before selecting the implementation.
- Recovery/backup must include a separately protected export/recovery mechanism for the encryption key; otherwise a restored database could make MFA secrets unrecoverable.
- The emergency owner key and encryption-key recovery material must be stored separately from the computer and separately from ordinary database backups.
- Recovery utility use must be one-time, locally authorized, logged, and must invalidate prior sessions and MFA factors.

### Item 4 — Numeric security and session defaults (owner-approved)

Recommended initial single-computer defaults:

| Control | Owner-approved default | Behavior |
|---|---:|---|
| Failed password attempts | 5 consecutive failures | Trigger temporary account lock |
| Lock duration | 15 minutes | GM may manually unlock sooner; each attempt remains audited |
| Failure counter reset | 15 minutes after last failure, or successful authentication | No permanent lockout from typo-only events |
| Idle session timeout | 15 minutes | Require re-authentication after inactivity |
| Pre-expiry warning | 2 minutes | Warn before idle session expires |
| Absolute session lifetime | 12 hours | Require full sign-in again |
| Concurrent sessions per user | 2 | GM may inspect and terminate; new session does not silently hide old sessions |
| TOTP period | 30 seconds | Standard time-based code period |
| TOTP accepted clock drift | Current step ±1 step | 30 seconds tolerance on either side; require local clock correction if outside |
| Recovery codes | 10 single-use codes | Rotate after recovery or suspected exposure |

These defaults are owner-approved starting values. TOTP remains mandatory for GM; employee MFA remains configurable by GM. Lockout must not provide an unauthenticated denial-of-service lever: rate-limit by account and local source, use bounded lock duration, and allow GM recovery through the controlled local administration path. Exact rate-limit implementation must remain compatible with the one-computer/no-Redis architecture.

### Item 5 — Database append-only audit mechanism (owner-approved direction; implementation details open)

Use a layered, cross-database design:

1. **Application contract:** all audit writes go through one audited append service; normal application code has no update/delete path for audit rows.
2. **Database enforcement:** install SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers, and PostgreSQL equivalent triggers, that reject mutation/deletion of audit rows. Migration tests must prove both operations fail.
3. **Tamper evidence:** each event stores a canonicalized payload hash and previous-event hash, forming a per-database append chain. Verify the chain on startup/health diagnostics and in a dedicated audit-integrity command.
4. **Independent offline evidence:** periodically export a signed audit checkpoint to a separately stored offline backup location; a database administrator with full machine access may still bypass local controls, so do not describe triggers alone as absolute tamper-proofing.
5. **Failure policy:** security-critical actions must fail closed if their required audit write cannot be committed atomically. Do not allow a successful role grant, MFA reset, recovery, or sensitive administrative change without its audit event.
6. **Compatibility:** prove behavior on SQLite (development) and PostgreSQL (deployment); ensure normal migrations and backup/restore preserve triggers and chain continuity.

The threat model must explicitly state that an attacker with unrestricted operating-system and database-owner access can potentially replace local files or database objects. Hash chaining and offline signed checkpoints provide detection/resilience, not magical prevention against a fully privileged machine attacker.

**[Rev 2]** §18 corrects the hash-chain concurrency mechanism (Revision 1's reliance on `select_for_update()` is rejected for SQLite, where Django silently ignores it) and §19 adds the binding no-test-bypass rule for the trigger layer.

## 9B. Owner decision checklist for these five items

Owner approval status:

- [x] Item 1 — role/permission matrix, including the Accountant operational-role amendment in Section 9C.
- [x] Item 2 — resolver precedence and multiple-role behavior.
- [x] Item 3 — local GM bootstrap, recovery codes, emergency key, and encryption-key custody direction.
- [x] Item 4 — numeric lockout/session/TOTP defaults.
- [x] Item 5 — SQLite/PostgreSQL append-only triggers, hash chain, and offline signed checkpoints direction.

The five design decisions are owner-approved. This does not authorize W0-2B onward or permit implementation to bypass the W0-2A architecture-first inspection, technical validation, migration review, tests, or owner review gate.

## 9C. Owner decision record — Accountant operational-role expansion

**Decision date:** 2026-10-31  
**Decision:** APPROVED by the project owner  
**Applies to:** Initial RBAC role/permission matrix in W0-2A

The owner clarified that, in the target operating environment, one employee commonly performs several company duties. The Accountant role must therefore be designed as **Accountant / Operations**, not as a finance-only or read-mostly role.

The Accountant / Operations role is intended to support broad day-to-day company work, including:

- Accounting and routine finance operations, financial records, balances, and reports.
- Sales, purchases, customer and supplier management, and related document workflows.
- Warehouse and inventory operations, including receiving, movements, transfers, counts, and physical handover, subject to business and stock controls.
- Routine receipts, payments, treasury preparation, and company administration, with sensitive execution rights configurable per user by the GM.
- Creation, viewing, editing, and management of ordinary operational records and documents.

**Draft and experimental records:** The Accountant must be able to create trial/test transactions and ordinary drafts, edit them repeatedly, and delete them before they become approved/posted or otherwise financially/operationally effective. Such deletion must be audited and must not create journal entries or affect stock, party balances, cash, or other live business state. The system must distinguish disposable Draft/Test records from Pending Evidence or approved workflow records. A Pending Evidence record must be cancelled with a reason and retained in the audit/history trail, not silently deleted. Editing an approved record must revoke its approval according to OD-6.

**Posted and effective records:** Once a transaction has been posted or has otherwise created an irreversible financial/stock effect, it must not be directly edited or deleted. Corrections must follow the approved cancellation, reversal, or controlled correction workflow; the original record and its audit history remain preserved. This role expansion does not alter accounting, inventory, posting, reversal, or document-integrity contracts.

**Per-user configuration:** The GM can tailor an individual Accountant's permissions to the employee's actual duties. The role should provide broad operational capability, while high-impact permissions—such as treasury execution, period close/reopen, structural accounting configuration, bulk export, security/user administration, and reversal of posted history—remain individually grantable/restrictable and subject to domain invariants. No Accountant permission can bypass backend authorization, evidence requirements, atomicity/idempotency, or posted-history immutability.

This amendment supersedes the narrower Accountant entries in the original Section 9A Item 1 proposal. It does not expand the Warehouse Keeper role or change the GM role.

## 10. Implementation sequence after design approval

W0-2A is architecture-first and additive:

1. Inspect the current branch, repository models, migrations, tests, and existing audit/authentication services; map the owner-approved policy to the smallest compatible additive model design.
2. Resolve remaining technical details for first-run provisioning, TOTP encryption/key recovery, database-specific audit triggers/hash chaining, and migration behavior. Any change to an owner-approved policy requires a separate owner decision.
3. Prepare the exact schema/model mapping and migration plan, with no endpoint authorization behavior changes; present the plan and impact for owner review before implementation.
4. After the bounded model plan is approved, implement additive RBAC models/migration and deterministic tests for resolver precedence, expiry, deny precedence, protected GM authority, and multi-role cases.
5. Verify migrations and existing security/accounting regressions on SQLite and PostgreSQL, then present evidence for owner review.

Backend enforcement, login/MFA/recovery endpoints, employee administration, audit hardening, and frontend authorization are separate bounded workstreams (W0-2B onward). Do not bundle them into W0-2A.

## 11. Explicit non-goals

- No standalone hawala/remittance business.
- No changes to frozen Security Batch 2 or 3.
- No changes to accounting, inventory, posting, reversal, or document contracts.
- No public/LAN/multi-computer deployment.
- No mandatory internet, cloud identity, email, or SMS.
- No Tauri packaging implementation in W0-2A.
- No speculative Redis adoption.
- No merge, deployment, or freeze by an agent.

## 12. Acceptance gate

Before W0-2A code implementation, complete and present for owner review:

1. Exact additive model mapping and migration plan, preserving Django's default User model and avoiding duplicate permission engines. *(Delivered: §14, §15.)*
2. Technical implementation design for one-time local GM bootstrap and offline recovery, including TOTP encryption and key-backup/restore behavior. *(Direction approved (Item 3); implementation parameters remain open — UQ-4/UQ-5.)*
3. SQLite and PostgreSQL audit enforcement details, hash-chain canonicalization, signed checkpoint handling, and restore continuity tests. *(Design delivered: §18, §19; cadence/retention parameters open — UQ-6.)*
4. Exact permission-key catalog and object-scope mapping for the owner-approved Accountant / Operations role and Warehouse Keeper role. *(Delivered: §15.)*
5. A bounded W0-2A implementation plan proving existing endpoint authorization behavior and frozen Security Batch 2/3 contracts remain unchanged. *(Boundary delivered: §24.)*

The five policy decisions and Accountant-role amendment are already owner-approved; this remaining review is technical design and implementation planning, not a request to re-approve those decisions.

---

# REVISION 2 — TECHNICAL CORRECTIONS (sections 13–24)

The sections below are the Rev 2 technical deliverable. They correct identified architectural defects, contradictions, and incomplete specifications. They do not reopen, weaken, or re-litigate any owner-approved decision. Status labels used: **VERIFIED** (evidence path given), **NOT FOUND** (searched, absent), **NOT VERIFIABLE** (evidence unobtainable — recorded as unavailable, never as success), **CONTRACT-ONLY** (design contract for a future approved batch; NOT implemented), **ENFORCED-TODAY** (verified present in baseline code), **UNRESOLVED** (insufficient grounding — not guessed).

## 13. Revision 2 record — scope, method, and evidence

### 13.1 Mission type

Revision 4 is a documentation-only correction to the already-pushed Revision 3 design. It resolves findings K–O in §22: mandatory object scope, Django Admin GM-only gate, MFA/BasicAuthentication boundary, resolver fail-closed coverage, SQLite transaction consistency, and repository evidence. **No application code, models, migrations, APIs, frontend, tests, settings, or runtime behavior changed.** This revision updates only this document on the existing branch; no PR, merge, deployment, or implementation authorization. W0-2A implementation remains blocked on explicit owner approval.

### 13.2 Mandatory repository inspection and revision evidence

The following is the historical GitHub state immediately before the Revision 3 document update (retained for audit history, not current branch status):

| Item | Verified value | Method | Status |
|---|---|---|---|
| Live `main` SHA | `99579d99f4b7c668118ad7e2add2a2ef91d04fba` | GitHub compare base | VERIFIED |
| W0-2A branch | `security/w0-2a-rbac-architecture` | GitHub branch lookup | VERIFIED |
| Branch ↔ main | 5 commits ahead, 0 behind; merge-base equals main | GitHub compare endpoint | VERIFIED |
| Branch content delta vs main | Exactly one file added: `docs/architecture/W0-2A_RBAC_OFFLINE_SECURITY_DESIGN_DRAFT.md`; 1,152 additions, 0 deletions in the pre-Rev-3 compare | GitHub compare endpoint | VERIFIED |
| Retrieved document | 1,153 lines; blob SHA `9699bab8b143ae64ca8a3a15e39496893524ed9d` | GitHub file fetch | VERIFIED |
| Related W0-2A PR | No matching PR returned by repository PR search | GitHub PR search | NOT FOUND (search result only; not a statement about unrelated PRs) |
| Exact pre-update branch commit SHA | Not exposed by the available branch/compare response | Connector response inspection | NOT VERIFIABLE |
| CI for pre-update branch tip | No exact branch-tip SHA was exposed for a reliable check lookup in this inspection | Connector response inspection | NOT VERIFIABLE |

Revision 3's post-update evidence is superseded by the current Revision 4 evidence in §24.3. No CI success is inferred from an empty or unavailable status response.

### 13.3 Independent re-verification of cited code facts (not trusted from prior reports)

| Claim used by this revision | Re-verified evidence | Status |
|---|---|---|
| 62 migrations in backend | `find . -path "*/migrations/[0-9]*.py" \| wc -l` = 62 | VERIFIED |
| `AuditAction` has exactly 7 members; `action = CharField(max_length=20)` | `security/models.py:5-18` | VERIFIED |
| `AuditEvent.user` FK PROTECT; no DB-level protection | `security/models.py:15-28`; no triggers/RunSQL in any of 62 migrations | VERIFIED |
| `record_audit_event` keyword-only, `ValueError` on unknown action | `security/services.py:6-15` | VERIFIED |
| `IsAuthenticatedForERP` = authentication-only, 8 lines | `security/permissions.py:4-8` | VERIFIED |
| Tests mutate/delete AuditEvent rows | `accounting/test_bootstrap.py:55-58` (`.delete()`), `:116-121` (`event.action = AuditAction.UPDATE; event.save(...)`) | VERIFIED |
| Only service-level draft deletion is purchase-draft **lines** | `purchases/services.py:349` (`current.lines.all().delete()`) | VERIFIED |
| `Warehouse` has no keeper/user FK | `warehouses/models.py:19-34` (fields: name, name_fa, is_active, created_at) | VERIFIED |
| Django `>=5.2,<6.0` (SQLite `transaction_mode` option available) | `requirements.txt:1` | VERIFIED |
| Conditional `UniqueConstraint` precedent exists | `currencies/migrations/0001_initial.py:29` (one_base_currency) | VERIFIED |
| `exchange_houses` services = create/update house only (no settlements) | `exchange_houses/services.py:68,90` | VERIFIED |
| No `currencies` services module | `currencies/` = models/tests only | VERIFIED (NOT FOUND) |
| No sales refund service | grep `refund` in `sales/services.py` = 0 hits | VERIFIED (NOT FOUND) — **[Rev 5 correction]** the search scope was incomplete: `sales/returns_services.py` (not scanned) contains `create_refund` (:500-636) and `reverse_refund` (:637-667) and `Refund` model (returns_models.py:87-130), all present on main `99579d9`. The claim was true of the file searched, false of the sales domain. Corrected at §15.3/§15.5 |

### 13.4 Revision 5 record — complete permission-scope audit (documentation-only)

Revision 5 performs the evidence-backed scope audit required before implementation: every one of the 162 permission keys now carries a `scope_policy` classification grounded in actual repository evidence or explicitly marked `UNRESOLVED` (§15A). Work performed, in order:

1. **INSPECT** — live GitHub re-verification (main `99579d99…`, branch tip `33fd1a1f…`, document blob `bf36e6c3…`, 10 ahead / 0 behind, no W0-2A PR, zero check-runs on the exact commit → CI NOT VERIFIABLE). The working environment had been reset between sessions; the repository was re-cloned and every baseline value re-verified live against GitHub before any work.
2. **TRACE EVIDENCE** — five read-only evidence sweeps over the actual app layout (22 Django apps under `backend/`; only 5 URLconfs exist): security/config/audit; warehouses+inventory; purchases+sales; parties/payments/allocations/advances/cash/treasury/exchange/currencies; accounting/fiscal/products/catalog/documents/reporting. Every model, FK, service function, route, and permission class was recorded with file:line; every absence was verified with a stated search.
3. **RECONCILE** — the registry (§15.3) was compared against the code: 20 evidence-error corrections were applied (§15.3 `[R5]` rows; §22 rows Q–V), the Warehouse Keeper matrix was reconciled (§15.4), and the seed totals were recounted (§15.4).
4. **CLASSIFY** — all 162 keys classified `NONE` / `WAREHOUSE_REQUIRED` / `OBJECT_REQUIRED` / `UNRESOLVED` (§15A); `UNRESOLVED` is a design-time fail-closed classification only — never a runtime policy and never seedable.
5. **DOCUMENT / VALIDATE** — registry inserted (§15A); totals, headings, and stale GitHub evidence repaired; counts re-verified programmatically (162 rows, 162 unique, 0 duplicates, 0 omissions).

No code, models, migrations, API, frontend, tests, settings, or runtime behavior changed. W0-2A implementation remains blocked on explicit owner approval (§23).

## 14. Technical model mapping (Rev 2) — temporal semantics, uniqueness, and deletion policies

Six additive models (M1–M6) referencing `settings.AUTH_USER_MODEL`. No User model change (D1). No Django Groups/Permissions reuse. This section supersedes the open model questions of Revision 1.

### 14.1 Uniform temporal grant-row pattern (M4, M5, M6)

All three user-scoped grant tables share one temporal shape:

| Field | Type | Notes |
|---|---|---|
| `user` | FK → User | **PROTECT** (§14.8) |
| target (role / permission / warehouse) | FK | PROTECT (§14.8) |
| `start_at` | DateTime, default now | May be future (scheduling legitimate for temporary access, OD-5 §2) |
| `end_at` | DateTime, null | NULL = indefinite. Bounded grants (temporary access) REQUIRE `end_at` and `reason` (service-enforced) |
| `reason` | Char(500) | Required for bounded grants; recorded for all grants |
| `granted_by` | FK → User, null | PROTECT; null = system/migration |
| `revoked_at` | DateTime, null | Closure timestamp (manual revoke OR expiry settlement) |
| `revoked_by` | FK → User, null | PROTECT; NULL when closed by settlement/system |
| `revocation_kind` | TextChoices(`MANUAL`, `EXPIRED`, `SUPERSEDED`), null | NEW in Rev 2 — distinguishes closure causes (defect A fix) |
| `created_at` | DateTime, auto | |

### 14.2 Derived lifecycle states (computed at read; never stored redundantly)

- **SCHEDULED**: `start_at > now` (not yet effective; still occupies the live slot)
- **ACTIVE (effective)**: `revoked_at IS NULL AND start_at <= now AND (end_at IS NULL OR end_at > now)`
- **EXPIRED (unsettled)**: `revoked_at IS NULL AND end_at IS NOT NULL AND end_at <= now`
- **REVOKED (manually/superseded)**: `revoked_at IS NOT NULL AND revocation_kind IN (MANUAL, SUPERSEDED)`
- **CLOSED**: `revoked_at IS NOT NULL` (covers settled-expired and revoked rows)
- Resolver active-predicate = ACTIVE only. SCHEDULED, EXPIRED, and CLOSED rows never grant (Item 2 rule).

### 14.3 Expiry settlement operation (defect A fix — answers A.1, A.2)

An expired-but-unrevoked row must never block a future grant. Every grant-writing service begins its transaction with an idempotent **settlement** for the affected slot:

```sql
UPDATE <grant_table>
SET revoked_at = end_at, revocation_kind = 'EXPIRED', revoked_by = NULL
WHERE <slot predicate> AND revoked_at IS NULL
  AND end_at IS NOT NULL AND end_at <= now();
```

- After settlement, the expired row is CLOSED with explicit cause `EXPIRED` and system attribution (`revoked_by = NULL`, reason text untouched; the cause is machine-readable in `revocation_kind`).
- Settlement is idempotent and cheap (indexed on the slot columns and `revoked_at`).
- A new assignment can then be created in the same transaction (answers A.2).
- Historical records are preserved verbatim — settlement never deletes or rewrites business content (answers A.5).

### 14.4 Uniqueness strategy (revised — do not assume the partial unique alone solves temporal overlap)

| Model | Live-slot unique constraint |
|---|---|
| M4 `UserRoleAssignment` | `UniqueConstraint(user, role, condition=Q(revoked_at__isnull=True))` |
| M5 `UserPermissionOverride` | `UniqueConstraint(user, permission, condition=Q(revoked_at__isnull=True))` — **REVISED**: spans both effects. One live override per (user, permission) regardless of ALLOW/DENY; prevents an ambiguous simultaneously-live ALLOW+DENY pair at the database level |
| M6 `UserWarehouseScope` | `UniqueConstraint(user, warehouse, condition=Q(revoked_at__isnull=True))` |

- Meaning: **at most one non-closed row per slot** (non-closed = SCHEDULED or ACTIVE).
- The partial unique is the **race backstop**, not the temporal solution. Temporal correctness comes from settlement-before-insert (§14.3). The constraint additionally makes the "duplicate live grant" race physically impossible on both engines.
- Window validity check constraint on all three models: `end_at IS NULL OR end_at > start_at`.

### 14.5 Overlap policy (answers A.3)

- **Overlapping same-slot grants are NOT permitted.** At most one non-closed row per (user, role), per (user, permission), per (user, warehouse). This covers ACTIVE and SCHEDULED rows: scheduling a future grant for a slot requires closing the current row first (replacement, §14.7). Rationale: same-slot duplicates add no capability (role unions already union across roles) but create ambiguous expiry semantics; one-live-row-per-slot is trivially queryable, auditable, and race-safe.
- **Multiple different roles on one user remain fully allowed** and union at resolve time — the restriction is same-slot only.
- For M5, if a GM needs both a DENY and an ALLOW for the same user+permission, the DENY is pointless (deny wins); the design therefore stores one live row per (user, permission). The resolver additionally applies deny-wins defensively (§16, R15).

### 14.6 Grant service algorithm and concurrency strategy (answers A.6, A.7)

Every grant/renewal/replacement/settlement operation runs:

1. `transaction.atomic()` begins.
2. **SQLite transaction boundary:** the outermost transaction MUST already be `IMMEDIATE` before this operation begins; an ambient `DEFERRED` transaction is rejected. Settlement UPDATE then runs before slot-state read. It does not retroactively upgrade a transaction that has already performed reads. On PostgreSQL, settlement updates and locks existing expired rows; the unique constraint remains the race backstop when no row exists.
3. Validate window: `end_at > start_at`; bounded grants require `end_at` and `reason`.
4. Overlap check: `SELECT ... WHERE <slot> AND revoked_at IS NULL` → if found, raise domain error `GrantConflictError`.
5. INSERT the new row.
6. COMMIT. If a concurrent writer wins the same-slot insert race, the partial unique index rejects the losing INSERT with `IntegrityError`, translated to `GrantConflictError`. Do not promise retry will succeed: if the winning row remains ACTIVE/SCHEDULED, retry must return the same conflict. Retry only after a verified transient lock/busy failure or after the conflicting grant is legitimately closed; never retry a business conflict automatically.

**Engine behavior:**

- **SQLite (development):** grant-writing services MUST execute inside an outermost transaction acquiring the SQLite write reservation before business/slot reads. Preferred contract: Django ≥5.2 `"OPTIONS": {"transaction_mode": "IMMEDIATE"}`. A first-statement settlement UPDATE is safe only if no earlier statement/read has begun; it is not safe inside an ambient DEFERRED transaction. Reject entry from ambient DEFERRED transactions; nested `atomic()`/savepoints do not upgrade them. Configure explicit busy timeout; retry only the whole idempotent outer business operation. The global option affects all outermost SQLite atomic transactions and remains an owner decision before W0-2E; if declined, provide a separately proven design. W0-2A changes no settings.
- **PostgreSQL (deployment):** partial unique index is the authoritative backstop; step 2 row-locks existing rows. Optional refinement (not required): `pg_advisory_xact_lock` keyed on the slot hash for cleaner serialization. Plain `transaction.atomic()` + settlement-first + unique backstop is sufficient and testable.
- **Portability:** partial unique indexes with a `WHERE` condition are supported by SQLite (≥3.8) and PostgreSQL (repo precedent: `currencies/migrations/0001_initial.py:29`).

### 14.7 Renewal vs replacement (answers A.4)

- **Renewal (extension):** `UPDATE end_at` on the ACTIVE row only; `end_at` must remain `> start_at` (and `> now` for bounded rows); row identity and `granted_by` continuity preserved; audited as `ACCESS_EXTENDED`.
- **Replacement:** close the current row (`revocation_kind = SUPERSEDED`, reason mandatory) and INSERT the new row **in the same transaction**; audited as `ACCESS_REVOKED` + `ACCESS_GRANTED`. History contains both rows.
- Editing `start_at` of an ACTIVE row is prohibited (use replacement). Closed rows are never reopened or edited (audit-protection-consistent; attribution fields immutable).

### 14.8 Foreign-key deletion policies (defect F fix)

Revision 1 specified `user → CASCADE` on M4/M5/M6. **REJECTED**: CASCADE could erase authorization history if a user row were ever deleted. Corrected policies:

| Relationship | on_delete | Rationale |
|---|---|---|
| M4/M5/M6 `.user` | **PROTECT** | Users are deactivated, never deleted; history preserved |
| M4/M5/M6 `.granted_by`, `.revoked_by` | **PROTECT** | Grantor/revoker attribution permanent |
| M4 `.role` | PROTECT | Role deactivation (`is_active=False`) is the lifecycle; deletion of a system role is service-guarded |
| M5 `.permission` | PROTECT | Catalog rows never deleted (`is_active=False` instead) |
| M6 `.warehouse` | PROTECT | Warehouse masters are deactivated, not deleted |
| M3 `RolePermission.role` | CASCADE (unchanged) | Deleting a non-system role removes only its structural grant rows; system roles are deletion-guarded at service layer; user/audit history unaffected |
| M3 `RolePermission.permission` | PROTECT | as above |
| `AuditEvent.user` | PROTECT (existing, verified) | Unchanged |

**User deactivation vs deletion (answers F.1):** the ERP domain defines exactly one removal path — `is_active=False` (audited `ACCOUNT_DEACTIVATED` when W0-2C ships). Hard deletion of any User referenced by authorization or audit rows is blocked by the PROTECT chain (defense in depth even against Django Admin misuse — which is itself GM-restricted per D5, §12.5 design). **Behavior when a referenced user no longer exists (F.4):** cannot occur; PROTECT makes it unreachable, and the invariant is asserted by a model-regression test.

### 14.9 Per-model field summary (only deltas from Revision 1 shown; all else unchanged)

- **M1 `Role`**: `code` (unique, case-sensitive), `name`, `name_fa`, `description`, `is_active`, `is_system` (True for GM/ACCOUNTANT/WAREHOUSE_KEEPER seeds), timestamps. No temporal fields.
- **M2 `Permission`**: `key` (unique), `domain`, `resource`, `action`, `description`, `is_sensitive`, `is_active`, timestamps. Catalog seeded from registry (§15).
- **M3 `RolePermission`**: role, permission, `granted_by`, `granted_at`. Unique (role, permission).
- **M4 `UserRoleAssignment`**: §14.1 shape with target = role; unique per §14.4; check constraint §14.4.
- **M5 `UserPermissionOverride`**: §14.1 shape with target = permission and `effect` TextChoices(ALLOW, DENY) (required); unique per §14.4 (one live row per user+permission across effects).
- **M6 `UserWarehouseScope`**: §14.1 shape with target = warehouse; unique per §14.4. Schema only in W0-2A; enforcement via `ScopeContext` from W0-2B+.

### 14.10 What W0-2A does NOT create (unchanged disposition)

TOTP credentials, recovery codes, `UserSession`, login-attempt/lockout state, bootstrap state/tokens → W0-2C/D. Audit chain fields, `AuditChainHead`, triggers, new AuditAction wiring → W0-2E. OD-6 workflow states → OD-6 batch. `record_class` fields → owning domain batches (§20).

## 15. Exact permission-key catalog (Rev 2 — defect B fix)

### 15.1 Registry rules

- **No wildcard keys. No vague entries.** Every key is a literal `<domain>.<resource>.<action>` matching `^[a-z][a-z_]+\.[a-z_]+\.[a-z_]+$` (validated in the registry module and by a migration data assertion).
- Single source of truth: `SECURITY_PERMISSION_CATALOG` in `backend/security/permissions_catalog.py`; a W0-2A migration seeds rows from it; a Django `check` asserts registry == DB (drift fails loudly). Display labels are never authorization identifiers.
- The registry MUST define an explicit `scope_policy` for every key: `NONE`, `WAREHOUSE_REQUIRED`, or `OBJECT_REQUIRED`. Missing/unrecognized metadata is a configuration error and fails closed; it MUST NOT default to `NONE`. **[Rev 5]** The complete enumeration now exists: §15A lists all 162 keys with `scope_policy`, source model/contract, scope basis, resolver context, evidence, and status — the Defect-A contradiction (mapping claimed delivered while this bullet still required enumeration) is resolved. `(W)` markers in the **Accountant** column map to `WAREHOUSE_REQUIRED` for every holder of the key (all ten such keys are inventory keys). `(W)` markers appearing **only in the Warehouse Keeper column** denote a role-conditional, assignment-based data filter for Warehouse Keeper holders; the key itself remains `NONE` because the approved matrix (rows 1/4/5/7) does not warehouse-restrict the Accountant — see §23 item 9 for the modeling confirmation. `OBJECT_REQUIRED` classifications in §15A are grounded in persisted object models or approved contracts; `documents.document.*` and `sales.document.approve` are `UNRESOLVED` — a design-time, fail-closed classification that is never a runtime policy and is never seeded.
- **Status vocabulary (grounding):**
  - `ENDPOINT` — mounted API endpoint exists today (mapping verified).
  - `SERVICE` — service-layer chokepoint exists today (verified); enforceable once wired in W0-2B.
  - `MATRIX` — named by the owner-approved matrix (§9A Item 1/9C); no code chokepoint yet; registered for stability, unenforceable until the owning batch exists.
  - `RESERVED` — OD-6 document workflow dependency; registered, unenforceable, seeded to no one.
  - `UNRESOLVED` — insufficient grounding; **not guessed**; not seeded, not enforced; must be resolved or removed by the owning batch.
- **Seed vocabulary:** `A` = in role seed; `C†` = key exists, NOT seeded, explicit GM grant required; `✕` = prohibited for the role (per-user ALLOW override prohibited); `—` = not applicable.
- **GM seed rule:** GM is seeded with every key whose status ∈ {ENDPOINT, SERVICE, MATRIX} (= the protected GM capability set). RESERVED and UNRESOLVED keys are seeded to no one until their status changes by an approved batch.

### 15.2 Reconciliation of the "20 vs 23 domains" discrepancy

Revision 1's §9 table had **23 presentation rows**; the executive summary said "20-domain catalog". Both described the same registry with different granularity: presentation rows split one domain across multiple rows (e.g., fiscal periods appear in rows 16–18, all domain `fiscal`), and some rows span several domains (row 9 = payments + allocations; row 10 = payments + supplier_advances + purchases). **The definitive registry below has exactly 20 distinct `domain` tokens and 162 keys.** The registry table is authoritative from Rev 2 onward.

### 15.3 Registry — 20 domains, 162 keys

Legend: Sens = `is_sensitive`. Status: E=ENDPOINT, S=SERVICE, M=MATRIX, R=RESERVED, U=UNRESOLVED.

**Domain `security` — 20 keys (GM administration; override-prohibited for Accountant/Keeper per matrix row "User, role, permission …: No")**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `security.account.view_own` | View own profile (GET /api/v1/security/me/) | – | A | A | E (`security/views.py:7-11`) |
| `security.account.view` | List/view employee accounts | Y | ✕ | ✕ | M (W0-2C) |
| `security.account.create` | Create employee account | Y | ✕ | ✕ | M (W0-2C) |
| `security.account.activate` | Activate account | Y | ✕ | ✕ | M (W0-2C) |
| `security.account.deactivate` | Deactivate account | Y | ✕ | ✕ | M (W0-2C) |
| `security.account.reset_password` | Reset password (forces change) | Y | ✕ | ✕ | M (W0-2C) |
| `security.account.unlock` | Clear lockout (GM unlock, D9) | Y | ✕ | ✕ | M (W0-2C) |
| `security.account.handover` | Record departure/role-change handover | Y | ✕ | ✕ | M (W0-2C) |
| `security.role.view` | View roles/assignments | Y | ✕ | ✕ | M (W0-2C) |
| `security.role.assign` | Assign role | Y | ✕ | ✕ | M (W0-2C) |
| `security.role.revoke` | Revoke role | Y | ✕ | ✕ | M (W0-2C) |
| `security.permission.view` | View permission catalog/overrides | Y | ✕ | ✕ | M (W0-2C) |
| `security.permission.grant` | Grant ALLOW override | Y | ✕ | ✕ | M (W0-2C) |
| `security.permission.deny` | Grant DENY override | Y | ✕ | ✕ | M (W0-2C) |
| `security.permission.revoke` | Revoke override | Y | ✕ | ✕ | M (W0-2C) |
| `security.session.view` | View active sessions/devices | Y | ✕ | ✕ | M (W0-2D) |
| `security.session.terminate` | Terminate a session | Y | ✕ | ✕ | M (W0-2D) |
| `security.lockout.view` | Review failed logins/lockouts | Y | ✕ | ✕ | M (W0-2C/D) |
| `security.mfa.reset` | Reset employee MFA | Y | ✕ | ✕ | M (W0-2C) |
| `security.mfa.enroll_own` | Self-enroll MFA (employee configurable, D2) | – | A | A | M (W0-2C) |

**Domain `audit` — 2 keys (GM seed only; Accountant subset = UQ-7, deferred)**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `audit.report.view` | Read audit/security reports | Y | ✕ | ✕ | M (W0-2E) |
| `audit.report.export` | Export audit reports | Y | ✕ | ✕ | M (W0-2E) |

**Domain `fiscal` — 6 keys (mounted API today)**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `fiscal.period.view` | List/view fiscal periods | – | A | — | E (`fiscal_periods/views.py:53-70`) |
| `fiscal.period.create` | Create fiscal period | – | C† | — | E |
| `fiscal.period.close` | Close period | Y | C† | — | E |
| `fiscal.period.lock` | Lock period | Y | C† | — | E |
| `fiscal.period.reopen` | Reopen closed period | Y | C† | — | E |
| `fiscal.period.unlock` | Unlock locked period | Y | C† | — | E |

**Domain `purchases` — 17 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `purchases.document.view` | View purchase documents | – | A | A (receiving data, W) | M [R5: no purchase read route/service exists today — evidence §15A] |
| `purchases.document.create` | Create purchase draft | – | A | ✕ | S |
| `purchases.document.edit_draft` | Edit DRAFT purchase | – | A | ✕ | S (`purchases/services.py:300-365`) |
| `purchases.document.delete_draft` | Delete ordinary DRAFT purchase (audited; corrected UQ-9) | – | A | ✕ | M — line-level deletion exists (`purchases/services.py:349`); whole-draft audited delete service = owning batch |
| `purchases.document.post` | Post purchase | – | A | ✕ | S |
| `purchases.document.cancel` | Cancel unposted purchase with reason | – | A | ✕ | M (no cancel service yet) |
| `purchases.document.reverse` | Reverse via approved return/refund paths | – | A | ✕ | S |
| `purchases.document.export` | Export purchases | – | A | ✕ | M |
| `purchases.supplierrefund.view` | View supplier refunds | – | A | ✕ | M [R5: no read service exists — evidence §15A] |
| `purchases.supplierrefund.create` | Create supplier refund | – | A | ✕ | S |
| `purchases.supplierrefund.reverse` | Reverse supplier refund | – | A | ✕ | S |
| `purchases.supplierrefund.export` | Export supplier refunds | – | A | ✕ | M |
| `purchases.landedcost.view` | View landed costs | – | A | ✕ | E (`purchases/landed_cost_views.py:46-79`) |
| `purchases.landedcost.create` | Create landed cost | – | A | ✕ | E |
| `purchases.landedcost.post` | Post landed cost | – | A | ✕ | E |
| `purchases.landedcost.reverse` | Reverse posted landed cost | Y | C† | ✕ | E (`landed_cost_views.py:95-114`) |
| `purchases.landedcost.delete_draft` | Delete landed-cost draft | – | C† | ✕ | M (no delete service exists — verified 405) |

**Domain `sales` — 17 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `sales.document.view` | View sales documents | – | A | A (fulfillment data, W) | M [R5: no sales read route/service exists today — evidence §15A] |
| `sales.document.create` | Create sale draft | – | A | ✕ | S |
| `sales.document.edit_draft` | Edit DRAFT sale | – | A | ✕ | M [R5: no draft-edit service exists — evidence §15A] |
| `sales.document.delete_draft` | Delete ordinary DRAFT sale (audited; corrected UQ-9) | – | A | ✕ | M (ORM-only today) |
| `sales.document.submit` | Submit sale in workflow | – | A | ✕ | M (no submit step in code) |
| `sales.document.approve` | Approve sale (OD-6) | – | C† | ✕ | R (OD-6 batch) |
| `sales.document.post` | Finalize sale (`finalize_sale`) | – | A | ✕ | S |
| `sales.document.cancel` | Cancel unposted sale with reason | – | A | ✕ | M (no cancel service) |
| `sales.document.reverse` | Reverse via approved cancel/return paths | – | A | ✕ | M [R5: prior citation was cancel_warehouse_check's audit tail; no sale-reversal service exists — evidence §15A] |
| `sales.document.export` | Export sales | – | A | ✕ | M |
| `sales.return.view` | View sales returns | – | A | ✕ | S |
| `sales.return.create` | Create sales return | – | A | ✕ | S |
| `sales.return.reverse` | Reverse sales return | – | A | ✕ | S |
| `sales.return.export` | Export sales returns | – | A | ✕ | M |
| `sales.refund.view` | Customer refund views | – | — | ✕ | M [R5: Refund model exists (returns_models.py:87-130); no read service; seed decision §23.8] |
| `sales.refund.create` | Customer refund creation | – | — | ✕ | S [R5: create_refund verified returns_services.py:500-636; seed decision §23.8] |
| `sales.refund.reverse` | Customer refund reversal | – | — | ✕ | S [R5: reverse_refund verified returns_services.py:637-667; seed decision §23.8] |

**Domain `payments` — 10 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `payments.receipt.view` | View customer receipts | – | A | ✕ | M [R5: no read service exists — evidence §15A] |
| `payments.receipt.create` | Create customer receipt | – | A | ✕ | S |
| `payments.receipt.post` | Finalize receipt | – | A | ✕ | S |
| `payments.receipt.reverse` | Reverse receipt (`reverse_payment`) | – | A | ✕ | S |
| `payments.receipt.export` | Export receipts | – | A | ✕ | M |
| `payments.payment.view` | View supplier payments | – | A | ✕ | M [R5: no supplier-payment code exists — evidence §15A] |
| `payments.payment.create` | Create supplier payment | – | A | ✕ | M [R5: no supplier-payment code exists — evidence §15A] |
| `payments.payment.post` | Finalize payment | – | A | ✕ | M [R5: no supplier-payment code exists — evidence §15A] |
| `payments.payment.reverse` | Reverse payment | – | A | ✕ | M [R5: no supplier-payment code exists — evidence §15A] |
| `payments.payment.export` | Export payments | – | A | ✕ | M |

**Domain `allocations` — 4 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `allocations.allocation.view` | View allocations | – | A | ✕ | S |
| `allocations.allocation.create` | Create/execute allocation | – | A | ✕ | S |
| `allocations.allocation.reverse` | Reverse allocation | – | A | ✕ | S |
| `allocations.allocation.export` | Export allocations | – | A | ✕ | M |

**Domain `supplier_advances` — 4 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `supplier_advances.advance.view` | View advances | – | A | ✕ | S |
| `supplier_advances.advance.create` | Create advance | – | A | ✕ | S |
| `supplier_advances.advance.reverse` | Reverse advance | – | A | ✕ | S |
| `supplier_advances.advance.export` | Export advances | – | A | ✕ | M |

**Domain `cash` — 5 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `cash.cashaccount.view` | View cash accounts | – | A | ✕ | M [R5: resolver-only, no read service — evidence §15A] |
| `cash.cashaccount.create` | Create cash account | – | C† | ✕ | S |
| `cash.cashaccount.edit` | Edit cash account | – | C† | ✕ | S |
| `cash.cashaccount.deactivate` | Deactivate cash account | – | C† | ✕ | S |
| `cash.cashaccount.export` | Export cash account data | – | A | ✕ | M |

**Domain `treasury` — 5 keys (no treasury service exists today — all M)**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `treasury.operation.view` | View treasury operations/balances | – | A | ✕ | M |
| `treasury.operation.prepare` | Prepare settlement | – | A | ✕ | M |
| `treasury.operation.execute` | Execute settlement | Y | C† | ✕ | M |
| `treasury.operation.reverse` | Reverse executed settlement | Y | C† | ✕ | M |
| `treasury.operation.export` | Export treasury reports | – | A | ✕ | M |

**Domain `exchange` — 9 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `exchange.house.view` | View exchange houses | – | A | ✕ | M [R5: resolver-only, no read service — evidence §15A] |
| `exchange.house.create` | Create exchange house | – | A | ✕ | S |
| `exchange.house.edit` | Edit exchange house | – | A | ✕ | S (`:90`) |
| `exchange.house.deactivate` | Deactivate exchange house | – | A | ✕ | S |
| `exchange.house.export` | Export exchange data | – | A | ✕ | M |
| `exchange.settlement.view` | View settlements | – | A | ✕ | M (no settlement service — verified) |
| `exchange.settlement.create` | Create settlement | – | A | ✕ | M |
| `exchange.settlement.reconcile` | Reconcile settlement | – | C† | ✕ | M |
| `exchange.settlement.export` | Export settlements | – | A | ✕ | M |

**Domain `accounting` — 12 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `accounting.journal.view` | View journal entries | – | A | ✕ | S |
| `accounting.journal.create_draft` | Create journal draft (future API; auto-posted entries are system-generated) | – | C† | ✕ | M |
| `accounting.journal.edit_draft` | Edit journal draft | – | C† | ✕ | M |
| `accounting.journal.delete_draft` | Delete journal draft (audited; corrected UQ-9) | – | C† | ✕ | M |
| `accounting.journal.post` | Post journal entry (routine, when explicitly permitted) | Y | C† | ✕ | M |
| `accounting.journal.cancel` | Cancel unposted journal | – | C† | ✕ | M |
| `accounting.journal.reverse` | Reverse posted journal (`reverse_journal`) | Y | C† | ✕ | S |
| `accounting.report.view` | View balances/trial balance/reports (`accounting/balances.py`) | – | A | ✕ | S |
| `accounting.report.export` | Export financial reports | – | A | ✕ | M |
| `accounting.coa.view` | View chart of accounts | – | C† | ✕ | M |
| `accounting.coa.create` | Create COA structure | – | C† | ✕ | M |
| `accounting.coa.edit` | Edit COA structure | – | C† | ✕ | M |

**Domain `currencies` — 4 keys (no currencies service module exists — verified; matrix-grounded)**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `currencies.rate.view` | View currencies/rates | – | A | ✕ | M |
| `currencies.rate.create` | Enter exchange rate | – | C† | ✕ | M |
| `currencies.rate.edit` | Edit exchange rate | – | C† | ✕ | M |
| `currencies.rate.export` | Export rates | – | A | ✕ | M |

**Domain `parties` — 5 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `parties.party.view` | View parties (Keeper: minimum fields only) | – | A | A (min fields) | M [R5: no read service exists — evidence §15A] |
| `parties.party.create` | Create party | – | A | ✕ | S |
| `parties.party.edit` | Edit party | – | A | ✕ | S |
| `parties.party.deactivate` | Deactivate party | – | A | ✕ | S |
| `parties.party.export` | Export party data | – | A | ✕ | M |

**Domain `products` — 5 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `products.product.view` | View products (Keeper: name/code/UOM only — no cost/price) | – | A | A (min fields) | M [R5: no read service exists — evidence §15A] |
| `products.product.create` | Create product | – | A | ✕ | S |
| `products.product.edit` | Edit product | – | A | ✕ | S |
| `products.product.deactivate` | Deactivate product | – | A | ✕ | S |
| `products.product.export` | Export products | – | A | ✕ | M |

**Domain `catalog` — 10 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `catalog.category.view` | View categories | – | A | ✕ | M [R5: no read service exists — evidence §15A] |
| `catalog.category.create` | Create category | – | A | ✕ | S |
| `catalog.category.edit` | Edit category | – | A | ✕ | S |
| `catalog.category.deactivate` | Deactivate category | – | A | ✕ | S |
| `catalog.category.export` | Export categories | – | A | ✕ | M |
| `catalog.uom.view` | View UOMs | – | A | ✕ | M [R5: no read service exists — evidence §15A] |
| `catalog.uom.create` | Create UOM | – | A | ✕ | S |
| `catalog.uom.edit` | Edit UOM | – | A | ✕ | S |
| `catalog.uom.deactivate` | Deactivate UOM | – | A | ✕ | S |
| `catalog.uom.export` | Export UOMs | – | A | ✕ | M |

**Domain `warehouses` — 5 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `warehouses.warehouse.view` | View warehouses (Keeper: assigned only) | – | A | A (W) | S |
| `warehouses.warehouse.create` | Create warehouse master | – | C† | ✕ | S |
| `warehouses.warehouse.edit` | Edit warehouse master | – | C† | ✕ | S |
| `warehouses.warehouse.deactivate` | Deactivate warehouse | – | C† | ✕ | S |
| `warehouses.warehouse.export` | Export warehouse data | – | A | ✕ | M |

**Domain `inventory` — 12 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `inventory.movement.view` | View receipts/movements/transfers | – | A (W) | A (W) | S |
| `inventory.movement.create` | Execute receiving/movement/transfer | – | A (W) | A (W) | S |
| `inventory.movement.reverse` | Reversal via approved compensating paths (INV-guarded) | – | A | ✕ | S |
| `inventory.movement.export` | Export movement data | – | A (W) | ✕ | M |
| `inventory.count.view` | View stock counts | – | A (W) | A (W) | M |
| `inventory.count.create` | Record stock count | – | A (W) | A (W) | M |
| `inventory.count.export` | Export counts | – | A (W) | ✕ | M |
| `inventory.adjustment.view` | View adjustments | – | A (W) | ✕ | S |
| `inventory.adjustment.create` | Create adjustment draft | – | A (W) | ✕ | S |
| `inventory.adjustment.post` | Post count adjustment (financial) | – | A (W) | ✕ | S |
| `inventory.adjustment.reverse` | Reverse adjustment (INV-guarded) | – | A | ✕ | M [R5: no adjustment-reversal service exists — evidence §15A] |
| `inventory.adjustment.export` | Export adjustments | – | A (W) | ✕ | M |

**Domain `reporting` — 1 key**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `reporting.dashboard.view` | Dashboard (ACC: operational+finance; WK: warehouse summaries only, W) | – | A | A (W) | M (no dashboard API yet) |

**Domain `documents` — 9 keys (RESERVED — OD-6 dependency; seeded to no one)**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `documents.document.view` | Reserved (OD-6) | – | — | — | R |
| `documents.document.create` | Reserved (OD-6) | – | — | — | R |
| `documents.document.edit_draft` | Reserved (OD-6) | – | — | — | R |
| `documents.document.delete_draft` | Reserved (OD-6) | – | — | — | R |
| `documents.document.submit` | Reserved (OD-6) | – | — | — | R |
| `documents.document.approve` | Reserved (OD-6) | – | — | — | R |
| `documents.document.post` | Reserved (OD-6) | – | — | — | R |
| `documents.document.cancel` | Reserved (OD-6) | – | — | — | R |
| `documents.document.export` | Reserved (OD-6) | – | — | — | R |

### 15.4 Catalog totals (exact — recounted at Revision 5 with a row-level audit)

| Measure | Count |
|---|---|
| Distinct domains | **20** |
| Total registered keys | **162** (programmatically verified: 162 rows, 162 unique, 0 duplicates, 0 omissions, 0 invented keys) |
| Sensitive keys (`is_sensitive=True`) | **29** (security 18, audit 2, fiscal 4, landedcost.reverse 1, treasury execute+reverse 2, journal post+reverse 2) — unchanged |
| Status mix | **E=11, S=53, M=88, R=10, U=0** (after the 20 evidence corrections of §15.3) |
| GM seed (= GM capability set) | **152** (all ENDPOINT/SERVICE/MATRIX keys) |
| Accountant seed | **102** (matrix 'A' cells; Revision 2–4 published 101 without a row-level audit) |
| Warehouse Keeper seed | **12** = 8 warehouse-scoped `(W)` keys + 2 field-restricted keys (`parties.party.view`, `products.product.view` — minimum-fields serializer restriction per matrix row 2, not warehouse scope) + 2 self-scope keys (`security.account.view_own`, `security.mfa.enroll_own`) |
| Seeded to no one | **10** (`documents.*` 9 RESERVED + `sales.document.approve` RESERVED) |
| ENDPOINT-backed keys (enforceable immediately at W0-2B wiring) | 11 |
| Registry-UNRESOLVED (ungrounded) keys | 0 — every key is evidence-grounded or explicitly scope-UNRESOLVED |
| Scope-UNRESOLVED keys (§15A, fail-closed, unseeded) | 10 (`documents.*` 9 + `sales.document.approve`) |
| §15A scope counts | NONE=140, WAREHOUSE_REQUIRED=10, OBJECT_REQUIRED=2, UNRESOLVED=10 |

**Revision 5 reconciliation notes (binding):**

1. **GM seed 150 → 152.** Revisions 2–4 counted `sales.refund.*` as UNRESOLVED (seeded to no one) on the strength of a grep scoped to `sales/services.py` only. The refund services and model existed on main `99579d9` (`sales/returns_services.py:500-667`, `sales/returns_models.py:87-130`). The keys are now grounded (§15.3 `[R5]` rows); per the §15.1 GM rule they join the GM seed. Accountant/WK seed cells are unchanged ("—"/✕) pending owner decision §23 item 8.
2. **Accountant seed 101 → 102.** Recount of the matrix 'A' cells; the corrected count must be used by the W0-2C seed migration.
3. **`sales.document.approve` (ACC=C†, status R).** C† describes its post-OD-6 posture (matrix row 9: approval rights only by explicit GM grant and workflow rules). Today, per §15.1's RESERVED rule, it is seeded to no one and is counted in "seeded to no one" — Revision 2–4's total of 12 omitted it.
4. **17 keys carried status S without an existing service-layer chokepoint** (e.g., `payments.payment.*` — no supplier-payment code exists anywhere; `parties/products/catalog/cash/exchange` view rows — resolver-only apps). Corrected to M with `[R5]` markers; per-key evidence in §15A; issue record in §22 row T.
5. **Warehouse Keeper reconciliation (Defect E).** The two vocabularies are distinct and both correct: **12** = WK seeded keys; **14** = keys carrying `(W)`/assignment semantics anywhere in the matrix (10 with ACC-column markers → `WAREHOUSE_REQUIRED`; 4 with WK-column-only markers → role-conditional data filter). The 12 WK seeds comprise 8 of the W-scope keys plus the 2 field-restricted and 2 self-scope keys.

### 15.5 Resolution status of previously-unresolved keys (Rev 5)

- **`sales.refund.view/create/reverse` — grounded at Revision 5.** The `Refund` model (`sales/returns_models.py:87-130`) and the `create_refund`/`reverse_refund` services (`sales/returns_services.py:500-636`, `:637-667`) existed on main `99579d9` at the time Revision 2 declared them ungrounded; Revision 2's verification grep was scoped to `sales/services.py` only and never scanned `sales/returns_services.py` (§13.3 corrected row). Statuses corrected to M/S/S with `[R5]` markers. Seeds: GM only (per §15.1); Accountant assignment is owner decision §23 item 8. Enforcement remains with the owning sales-API batch (W0-2B).
- **`documents.document.*` (9) and `sales.document.approve` — scope-UNRESOLVED (§15A).** The OD-6 document workflow is unimplemented (the documents app contains only `NumberSequence`; no attachment models or file fields exist repo-wide). Their object scope cannot be established without the OD-6 design, so they are classified `UNRESOLVED` — fail-closed, seeded to no one, a design-time classification only. **No business permission has been invented without grounding.**

### 15A Evidence-backed scope registry — all 162 keys (Revision 5)

**Purpose (Defects A/B fix).** This registry is the authoritative per-key scope mapping. It contains exactly one row per registered key — 162 rows, 162 unique keys, no duplicates, no omissions, no invented keys. Column `scope_policy` is the server-owned resolver metadata required by §16.1 step 8; `UNRESOLVED` is a design-time classification only — it is not a fourth runtime policy, it denies by default, and it is not eligible for seeding. Column `status` records the classification grounding (`EVIDENCE_CONFIRMED` = grounded in code/approved-contract evidence cited in the row; `UNRESOLVED` = insufficient grounding, fail-closed).

**Classification framework.** `NONE` = the approved policy places no warehouse/object restriction on holders of the key; target/parent objects are still resolved server-side from persisted rows (§16.1 step 8) — `NONE` is never a shortcut for unknown scope. `WAREHOUSE_REQUIRED` = access is limited to warehouses assigned to the user (M6 registry); used exactly where the approved matrix carries a `(W)` marker in the **Accountant** column (all ten inventory keys — the restriction applies to every holder). `OBJECT_REQUIRED` = access is constrained to a specific persisted object tied to the caller (the two self-scope keys). For the four keys whose `(W)` marker appears only in the **Warehouse Keeper** column (`warehouses.warehouse.view`, `purchases.document.view`, `sales.document.view`, `reporting.dashboard.view`), the registry records `NONE` plus the role-conditional WK data filter, because the approved matrix does not warehouse-restrict the Accountant; the alternative modeling is owner decision §23 item 9.

**Evidence method.** Rows cite exact repository paths and symbols current at branch tip `33fd1a1f90fc49ccdbaf081b8a2ef9fbd45d4e27` (baseline main `99579d99f4b7c668118ad7e2add2a2ef91d04fba`). Absences (e.g., "no supplier-payment code exists") were verified by stated searches recorded in the Revision 5 evidence sweeps (§13.4).

| permission_key | domain | scope_policy | source_model_or_contract | scope_basis | resolver_context | evidence | reason | status |
|---|---|---|---|---|---|---|---|---|
| `security.account.view_own` | security | **OBJECT_REQUIRED** | security/views.py current_user endpoint (GET /api/v1/security/me/) returning only request.user | self-object: response is limited to the authenticated user's own identity (matrix row 12 self-service) | request.user obtained from the authenticated session; no client id parameter | security/views.py:7-11; security/permissions.py:4-8; config/urls.py:7 | endpoint returns {id, username} of the caller only; self scope is inherent to the operation | EVIDENCE_CONFIRMED |
| `security.account.view` | security | **NONE** | Django default User model (AUTH_USER_MODEL not set; config/settings/base.py); W0-2C admin API future | employee-account administration is company-global by approved matrix row 12 (Accountant/Keeper: No); no warehouse/party dimension exists in the approved policy | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | config/settings/base.py (no AUTH_USER_MODEL set repo-wide); §9A Item 1 row 12; §15.3 M (W0-2C) | listing employee accounts is a GM administration view; no assignment concept approved | EVIDENCE_CONFIRMED |
| `security.account.create` | security | **NONE** | Django default User model; W0-2C admin API future | employee-account administration is company-global by approved matrix row 12 (Accountant/Keeper: No); no warehouse/party dimension exists in the approved policy | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §9A Item 1 row 12; §5.1; §15.3 M (W0-2C) | account creation is company-global administration | EVIDENCE_CONFIRMED |
| `security.account.activate` | security | **NONE** | Django User.is_active flag; W0-2C admin API future | employee-account administration is company-global by approved matrix row 12 (Accountant/Keeper: No); no warehouse/party dimension exists in the approved policy | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §9A Item 1 row 12; §15.3 M (W0-2C) | lifecycle action on any employee account | EVIDENCE_CONFIRMED |
| `security.account.deactivate` | security | **NONE** | Django User.is_active flag; W0-2C admin API future | employee-account administration is company-global by approved matrix row 12 (Accountant/Keeper: No); no warehouse/party dimension exists in the approved policy | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §9A Item 1 row 12; §14.8 deactivation-not-deletion policy | deactivation is the approved user lifecycle end | EVIDENCE_CONFIRMED |
| `security.account.reset_password` | security | **NONE** | Django password machinery; W0-2C admin API future | employee-account administration is company-global by approved matrix row 12 (Accountant/Keeper: No); no warehouse/party dimension exists in the approved policy | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §9A Item 1 row 12; §15.3 M (W0-2C) | forced-change reset for any employee account | EVIDENCE_CONFIRMED |
| `security.account.unlock` | security | **NONE** | W0-2D lockout counters; Item 4 approved lockout semantics | employee-account administration is company-global by approved matrix row 12 (Accountant/Keeper: No); no warehouse/party dimension exists in the approved policy | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §9A Item 4 (GM may manually unlock); §15.3 M (W0-2C/D) | GM unlock clears lockout for any account | EVIDENCE_CONFIRMED |
| `security.account.handover` | security | **NONE** | W0-2C admin API future | employee-account administration is company-global by approved matrix row 12 (Accountant/Keeper: No); no warehouse/party dimension exists in the approved policy | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §5.1 GM administration duties; §15.3 M (W0-2C) | departure/role-change handover recorded per employee, company-wide | EVIDENCE_CONFIRMED |
| `security.role.view` | security | **NONE** | W0-2A models M1/M4 (design §14); W0-2C admin API future | role administration is company-global (matrix row 12) | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §14.1-14.9; §9A Item 1 row 12 | roles and assignments have no warehouse/party dimension | EVIDENCE_CONFIRMED |
| `security.role.assign` | security | **NONE** | M4 UserRoleAssignment grant service contract (§14.6) | company-global administration | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §14.6-14.7; §9A Item 1 row 12 | role assignment acts on user+role, not on scoped objects | EVIDENCE_CONFIRMED |
| `security.role.revoke` | security | **NONE** | M4 revocation contract (§14) | company-global administration | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §14; §9A Item 1 row 12 | revocation acts on the assignment row | EVIDENCE_CONFIRMED |
| `security.permission.view` | security | **NONE** | M2/M5 models + Permission catalog (§15); W0-2C admin API future | catalog/override administration is company-global | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §15.1; §9A Item 1 row 12 | viewing the catalog/overrides is an administration read | EVIDENCE_CONFIRMED |
| `security.permission.grant` | security | **NONE** | M5 UserPermissionOverride grant service contract (§14.6) | company-global administration | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §14.5-14.7; §9A Item 2; §15.1 C† rule | ALLOW override targets user+permission | EVIDENCE_CONFIRMED |
| `security.permission.deny` | security | **NONE** | M5 UserPermissionOverride deny contract (§14) | company-global administration | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §14.4-14.5; §9A Item 2 (D3 deny precedence) | DENY override targets user+permission | EVIDENCE_CONFIRMED |
| `security.permission.revoke` | security | **NONE** | M5 revocation contract (§14) | company-global administration | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §14; §15.1 C† rule | override revocation acts on the override row | EVIDENCE_CONFIRMED |
| `security.session.view` | security | **NONE** | W0-2D session registry future; Item 4 concurrent-session visibility | session administration is company-global (matrix row 12) | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §9A Item 4 (concurrent sessions visible/terminable); §15.3 M (W0-2D) | GM inspects any user's sessions; no object scope approved | EVIDENCE_CONFIRMED |
| `security.session.terminate` | security | **NONE** | W0-2D session registry future | company-global administration | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §9A Item 4; §6; §15.3 M (W0-2D) | GM terminates any session | EVIDENCE_CONFIRMED |
| `security.lockout.view` | security | **NONE** | W0-2D lockout counters future | company-global administration | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §9A Item 4 (each attempt audited; GM review); §15.3 M (W0-2C/D) | failed-login/lockout review is a security-administration read | EVIDENCE_CONFIRMED |
| `security.mfa.reset` | security | **NONE** | W0-2C MFA services future; D2 | company-global administration | target account/role/override/session pk resolved server-side by the W0-2C admin service; no client-supplied scope claims | §6 (D2); §9A Item 1 row 12; §15.3 M (W0-2C) | GM resets any employee's MFA enrollment | EVIDENCE_CONFIRMED |
| `security.mfa.enroll_own` | security | **OBJECT_REQUIRED** | W0-2C MFA self-enrollment future (employee configurable, D2) | self-object: enrollment creates/updates the caller's own MFA factors | request.user from the authenticated session | §15.3 meaning (employee configurable, D2); §9A Item 4; §6 | self-service enrollment; the only affected factors belong to the caller | EVIDENCE_CONFIRMED |
| `audit.report.view` | audit | **NONE** | AuditEvent model (security/models.py:15-28); W0-2E report layer future | audit/security reports are company-global; Accountant exclusion per matrix row 13 (subset = UQ-7, deferred) | report queries executed server-side over AuditEvent; no client scope claims | security/models.py:15-28; §9A Item 1 row 13; §15.3 header (UQ-7 deferred) | no warehouse/party dimension in audit reporting; ACC subset remains an open owner decision (UQ-7) | EVIDENCE_CONFIRMED |
| `audit.report.export` | audit | **NONE** | W0-2E report layer future; no export infrastructure exists repo-wide (verified) | company-global; matrix row 11 routes bulk/sensitive export through separate permission | export job executed server-side | absence check (E1/E5: no csv/xlsx/stream endpoints in backend/); §9A Item 1 row 11 | export of audit reports; no export infrastructure exists today (registered future capability) | EVIDENCE_CONFIRMED |
| `fiscal.period.view` | fiscal | **NONE** | FiscalPeriod model (fiscal_periods/models.py:10-39) + real endpoints (views.py:53-120; urls.py:5-11) | fiscal periods are company-global calendar objects; the single posting gate (assert_posting_date_open) serves every domain; no warehouse/party dimension | period pk resolved from the URL by the view; date-based period resolution inside services (find_period_for_date) | fiscal_periods/views.py:53-70,91-120; fiscal_periods/urls.py:5-11; fiscal_periods/services.py:103-138 | list/read periods is global master data (ENDPOINT-backed today) | EVIDENCE_CONFIRMED |
| `fiscal.period.create` | fiscal | **NONE** | FiscalPeriod model (fiscal_periods/models.py:10-39) + real endpoints (views.py:53-120; urls.py:5-11) | fiscal periods are company-global calendar objects; the single posting gate (assert_posting_date_open) serves every domain; no warehouse/party dimension | period pk resolved from the URL by the view; date-based period resolution inside services (find_period_for_date) | fiscal_periods/views.py:53-70,91-120; fiscal_periods/urls.py:5-11; fiscal_periods/services.py:103-138 | period creation is global configuration (ENDPOINT-backed) | EVIDENCE_CONFIRMED |
| `fiscal.period.close` | fiscal | **NONE** | FiscalPeriod model (fiscal_periods/models.py:10-39) + real endpoints (views.py:53-120; urls.py:5-11) | fiscal periods are company-global calendar objects; the single posting gate (assert_posting_date_open) serves every domain; no warehouse/party dimension | period pk resolved from the URL by the view; date-based period resolution inside services (find_period_for_date) | fiscal_periods/views.py:53-70,91-120; fiscal_periods/urls.py:5-11; fiscal_periods/services.py:103-138 | close is global; balanced-range verification first (services.py:181-215) | EVIDENCE_CONFIRMED |
| `fiscal.period.lock` | fiscal | **NONE** | FiscalPeriod model (fiscal_periods/models.py:10-39) + real endpoints (views.py:53-120; urls.py:5-11) | fiscal periods are company-global calendar objects; the single posting gate (assert_posting_date_open) serves every domain; no warehouse/party dimension | period pk resolved from the URL by the view; date-based period resolution inside services (find_period_for_date) | fiscal_periods/views.py:53-70,91-120; fiscal_periods/urls.py:5-11; fiscal_periods/services.py:103-138 | lock is global; LOCKED blocks all posting domain-wide | EVIDENCE_CONFIRMED |
| `fiscal.period.reopen` | fiscal | **NONE** | FiscalPeriod model (fiscal_periods/models.py:10-39) + real endpoints (views.py:53-120; urls.py:5-11) | fiscal periods are company-global calendar objects; the single posting gate (assert_posting_date_open) serves every domain; no warehouse/party dimension | period pk resolved from the URL by the view; date-based period resolution inside services (find_period_for_date) | fiscal_periods/views.py:53-70,91-120; fiscal_periods/urls.py:5-11; fiscal_periods/services.py:103-138 | reopen is global and reason-audited (services.py:253-280) | EVIDENCE_CONFIRMED |
| `fiscal.period.unlock` | fiscal | **NONE** | FiscalPeriod model (fiscal_periods/models.py:10-39) + real endpoints (views.py:53-120; urls.py:5-11) | fiscal periods are company-global calendar objects; the single posting gate (assert_posting_date_open) serves every domain; no warehouse/party dimension | period pk resolved from the URL by the view; date-based period resolution inside services (find_period_for_date) | fiscal_periods/views.py:53-70,91-120; fiscal_periods/urls.py:5-11; fiscal_periods/services.py:103-138 | unlock is global and reason-audited (services.py:310-333) | EVIDENCE_CONFIRMED |
| `purchases.document.view` | purchases | **NONE** | Purchase model (purchases/models.py:68-102; document-level warehouse FK :75); only landed-cost routes mounted today | key-level NONE: Accountant unrestricted per matrix row 5; the WK cell carries (W) 'receiving data' - an assignment-based data filter for WK holders only, not a key-level restriction (role-conditional; see §23 item 9) | document pk resolved server-side by the owning API batch; WK list queries filtered to assigned warehouses via M6 | purchases/models.py:75; §9A Item 1 row 5; absence of purchase read routes (E1/E3) | Purchase.warehouse FK (models.py:75) provides the persisted relation the WK filter will use; ACC view is unrestricted by approved policy | EVIDENCE_CONFIRMED |
| `purchases.document.create` | purchases | **NONE** | create_purchase service (purchases/services.py:253-294) creating status=DRAFT (:282) | no target object exists at creation; the warehouse argument is document data, not an authorization scope (ACC create unrestricted per matrix row 5; WK prohibited) | service creates the object; created_by = authenticated actor; warehouse resolved server-side via resolve_warehouse before insert | purchases/services.py:253-294; purchases/models.py:75 | create/list operations without a persisted target are not object-scoped (task-book rule); draft creation has no parent context to scope to | EVIDENCE_CONFIRMED |
| `purchases.document.edit_draft` | purchases | **NONE** | update_purchase service (purchases/services.py:300-362; DRAFT-only gate :310-311) | acts on the company's own draft documents; no assignment restriction in approved policy | purchase resolved server-side (instance or pk :307); DRAFT status gate enforced in service | purchases/services.py:300-362 | draft editing is status-gated, not scope-gated | EVIDENCE_CONFIRMED |
| `purchases.document.delete_draft` | purchases | **NONE** | corrected UQ-9 audited delete service (owning batch); today: line deletion inside update_purchase (:349) and ORM-only draft delete (models.py:99-102) | owner decision UQ-9 (§20.3): ordinary drafts deletable with authorization+audit; no object-scope restriction | purchase resolved server-side; audited whole-document delete contract | §20.3; purchases/services.py:349; purchases/models.py:99-102 | deletion is lifecycle/audit-gated, not scope-gated | EVIDENCE_CONFIRMED |
| `purchases.document.post` | purchases | **NONE** | post_purchase service (purchases/services.py:531-551; DRAFT→POSTED :514-516; fiscal gate :464; receive_stock :489-502) | posting acts on the company document; fiscal-period gate applies; stock received into the document warehouse (data, not authz scope) | purchase resolved server-side (instance or pk); period gate inside service | purchases/services.py:531-551,464,489-502 | no per-user warehouse restriction approved for ACC posting | EVIDENCE_CONFIRMED |
| `purchases.document.cancel` | purchases | **NONE** | no cancel service exists today (verified); corrected UQ-9 cancel-with-reason contract (owning batch) | matrix row 10: ACC cancels eligible unposted documents with reason; no object-scope restriction | document resolved server-side; reason-audited contract | absence check (E3: no cancel/CANCELLED in purchases); §20.3; §9A Item 1 row 10 | registered contract capability; lifecycle-gated | EVIDENCE_CONFIRMED |
| `purchases.document.reverse` | purchases | **NONE** | posted purchases are immutable (models.py:92-102); correction via PurchaseReturn/post_purchase_return (services.py:570-672) and reverse_purchase_return (:748-823) | matrix row 10: controlled correction only, never direct edit/delete of posted history | return resolved server-side; compensating flows derive warehouse from the source document | purchases/models.py:92-102; purchases/services.py:570-823 | reversal capability is the approved return/refund path | EVIDENCE_CONFIRMED |
| `purchases.document.export` | purchases | **NONE** | no export infrastructure exists repo-wide (verified); W0-2B future | matrix row 11: operational exports permitted; bulk export separately permissioned; no object scope | export job executed server-side | absence check (E1/E5); §9A Item 1 row 11 | registered future capability | EVIDENCE_CONFIRMED |
| `purchases.supplierrefund.view` | purchases | **NONE** | SupplierRefund/CrossCurrencySupplierRefund/SupplierRefundReversal models (purchases/models.py:218-305); no read service/endpoint today | supplier refund claims are company-global financial records; no warehouse dimension | refund pk resolved server-side by the owning API batch | purchases/models.py:218-305; supplier_refund_services.py | no read chokepoint exists today; status corrected to M | EVIDENCE_CONFIRMED |
| `purchases.supplierrefund.create` | purchases | **NONE** | create_supplier_refund (purchases/supplier_refund_services.py:174-336; requires POSTED return :188-189; claim cap :217-221) | refund creation acts on the company's claim against a posted return; no object-scope restriction approved | purchase_return resolved server-side; cap computed from persisted rows | purchases/supplier_refund_services.py:174-336 | claim cap prevents over-refund; scope is not user-assignment-based | EVIDENCE_CONFIRMED |
| `purchases.supplierrefund.reverse` | purchases | **NONE** | reverse_supplier_refund (purchases/supplier_refund_services.py:339-400; POSTED→REVERSED :384) | matrix row 10 controlled reversal; no object-scope restriction approved | refund resolved server-side; reason-audited | purchases/supplier_refund_services.py:339-400 | reversal is lifecycle-gated | EVIDENCE_CONFIRMED |
| `purchases.supplierrefund.export` | purchases | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11; company-global financial export | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `purchases.landedcost.view` | purchases | **NONE** | landed_cost_collection endpoint GET (purchases/landed_cost_views.py:46-71); LandedCostDocument model (models.py:371-429; no warehouse FK) | landed-cost documents are company-global cost allocations to purchases; model has no warehouse FK | queryset built server-side (_document_queryset :37-43); pk from URL | purchases/landed_cost_views.py:46-71; purchases/models.py:371-429 | ENDPOINT-backed today; no warehouse dimension in the model | EVIDENCE_CONFIRMED |
| `purchases.landedcost.create` | purchases | **NONE** | landed_cost_collection endpoint POST (landed_cost_views.py:54-71; landed_cost_services.py draft create) | draft creation; no target object at creation; payee/allocations are data | service creates the document; user = actor for audit | purchases/landed_cost_views.py:54-71; landed_cost_services.py | no persisted parent context to scope to | EVIDENCE_CONFIRMED |
| `purchases.landedcost.post` | purchases | **NONE** | landed_cost_post endpoint (landed_cost_views.py:82-91; landed_cost_posting.py post_landed_cost :513) | posting acts on the company document; fiscal gate applies | document pk resolved server-side | purchases/landed_cost_views.py:82-91; landed_cost_posting.py:513 | ENDPOINT-backed; lifecycle-gated | EVIDENCE_CONFIRMED |
| `purchases.landedcost.reverse` | purchases | **NONE** | landed_cost_reverse endpoint (landed_cost_views.py:95-114; landed_cost_reversal.py reverse_landed_cost :131) | matrix row 10 controlled reversal; sensitive (C†) | document pk resolved server-side; reason-audited | purchases/landed_cost_views.py:95-114; landed_cost_reversal.py:131 | ENDPOINT-backed; lifecycle-gated | EVIDENCE_CONFIRMED |
| `purchases.landedcost.delete_draft` | purchases | **NONE** | no DELETE method on any landed-cost route (405 verified); audited delete = owning batch | UQ-9 ordinary-draft deletion contract; no object-scope restriction | document resolved server-side; audited-delete contract | absence check (E3: grep DELETE in landed_cost_views.py = 0); §20.3 | registered contract capability | EVIDENCE_CONFIRMED |
| `sales.document.view` | sales | **NONE** | Sale model (sales/models.py:34-64; NO document-level warehouse FK); warehouse via SaleLineWarehouseAllocation (:303); no sales routes/services today | key-level NONE: Accountant unrestricted per matrix row 4; WK cell carries (W) 'fulfillment data' - assignment-based data filter for WK holders only (role-conditional; see §23 item 9) | document pk resolved server-side by the owning API batch; WK filter derives warehouses from persisted SaleLineWarehouseAllocation rows | sales/models.py:34-64,294-331; §9A Item 1 row 4; absence of sales routes (E3) | the allocation rows provide the persisted relation for the WK fulfillment-data filter; ACC view unrestricted by approved policy | EVIDENCE_CONFIRMED |
| `sales.document.create` | sales | **NONE** | create_sale service (sales/services.py:145+) | no target object at creation; customer/warehouse allocations are data | service creates the object; created_by = actor | sales/services.py:110-123,145+ | draft creation has no persisted parent context to scope to | EVIDENCE_CONFIRMED |
| `sales.document.edit_draft` | sales | **NONE** | no draft-edit service exists today (verified: only create/finalize in sales/services.py); W0-2B future | acts on company drafts; no assignment restriction approved | sale resolved server-side by the future service; DRAFT gate | absence check (E3: grep update\|edit\|delete in sales/services.py = only cancel_warehouse_check) | status corrected S→M: no edit chokepoint exists | EVIDENCE_CONFIRMED |
| `sales.document.delete_draft` | sales | **NONE** | corrected UQ-9 audited delete (owning batch); ORM-only today (models.py:61-64 allows DRAFT delete) | owner decision UQ-9 (§20.3) | sale resolved server-side; audited-delete contract | §20.3; sales/models.py:61-64 | lifecycle/audit-gated, not scope-gated | EVIDENCE_CONFIRMED |
| `sales.document.submit` | sales | **NONE** | no submit step exists in code (verified); OD-6/future workflow | matrix row 4 'submit' named at role level; workflow unimplemented | sale resolved server-side by the future workflow service | absence check (E3: no SUBMITTED status; grep submit = comments only); §9A Item 1 row 4 | registered contract capability | EVIDENCE_CONFIRMED |
| `sales.document.approve` | sales | **UNRESOLVED** | RESERVED status (R); OD-6 document-workflow batch | approval workflow unimplemented; object scope (incl. self-approval prohibition, matrix row 9) unresolvable until the OD-6 design exists | undefined until OD-6 batch defines the workflow objects | §15.3 R (OD-6 batch); §9A Item 1 row 9; docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING; design-time state, not a runtime policy | UNRESOLVED |
| `sales.document.post` | sales | **NONE** | finalize_sale service (sales/services.py:189-374; explicit warehouse allocations required :310-313; status→FINALIZED :363-366) | posting acts on the company document; allocation warehouses are business data (no approved per-user warehouse restriction for ACC posting) | sale resolved server-side (instance or pk); allocation intents resolved from persisted rows | sales/services.py:189-374,310-313,363-366 | invoice-time warehouse allocation is a business invariant, not an authorization scope | EVIDENCE_CONFIRMED |
| `sales.document.cancel` | sales | **NONE** | no cancel service exists (verified); UQ-9 cancel-with-reason contract | matrix row 10; lifecycle-gated | sale resolved server-side; reason-audited contract | absence check (E3); §20.3 | registered contract capability | EVIDENCE_CONFIRMED |
| `sales.document.reverse` | sales | **NONE** | no sale-reversal service exists (verified); posted-sale correction modeled through sales.return.* services (reverse_sales_return returns_services.py:670-791) | matrix row 10 controlled correction; never direct edit of posted history | return resolved server-side; warehouse derived from SalesReturn.warehouse FK (:39) | absence check (E3: cited services.py:680-691 is cancel_warehouse_check audit tail - prior citation was wrong); sales/returns_services.py:670-791 | status corrected S→M with corrected evidence | EVIDENCE_CONFIRMED |
| `sales.document.export` | sales | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11; company-global | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `sales.return.view` | sales | **NONE** | SalesReturn model (sales/returns_models.py:25-84; warehouse FK :39); remaining_quantity read helper (sales/services.py:377-381) | return records are company-global; no object-scope restriction approved | return pk resolved server-side; read helpers take persisted objects | sales/returns_models.py:25-84; sales/services.py:377-381 | service-layer read helper exists (S status retained) | EVIDENCE_CONFIRMED |
| `sales.return.create` | sales | **NONE** | create_sales_return (sales/returns_services.py:239-431; requires FINALIZED sale :257-258) | company-global operational correction; no object-scope restriction approved | sale resolved server-side; warehouse from SalesReturn.warehouse | sales/returns_services.py:239-431 | lifecycle-gated service | EVIDENCE_CONFIRMED |
| `sales.return.reverse` | sales | **NONE** | reverse_sales_return (sales/returns_services.py:670-791; blocks while posted refunds exist :727-730) | matrix row 10 controlled reversal | return resolved server-side; compensating stock movement derived from the persisted return | sales/returns_services.py:670-791 | reversal is lifecycle-gated | EVIDENCE_CONFIRMED |
| `sales.return.export` | sales | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `sales.refund.view` | sales | **NONE** | Refund model (sales/returns_models.py:87-130); no read service today | customer refund records are company-global financial records; no warehouse dimension | refund pk resolved server-side by the owning API batch | sales/returns_models.py:87-130; correction of prior 'no verified service' claim (services exist since main 99579d9: returns_services.py:500,637) | status corrected U→M: Refund model grounded; read chokepoint future; seed assignment = owner decision (§23 item 8) | EVIDENCE_CONFIRMED |
| `sales.refund.create` | sales | **NONE** | create_refund service (sales/returns_services.py:500-636; requires POSTED return :513-514; refundable cap :538-542) | company-global financial operation on a posted return; no object-scope restriction approved | sales_return resolved server-side; cap computed from persisted rows | sales/returns_services.py:500-636 (existed at main 99579d9; prior Rev-2 grep scoped only to sales/services.py) | status corrected U→S: service verified; seed assignment = owner decision (§23 item 8) | EVIDENCE_CONFIRMED |
| `sales.refund.reverse` | sales | **NONE** | reverse_refund service (sales/returns_services.py:637-667; POSTED→REVERSED :658) | matrix row 10 controlled reversal | refund resolved server-side; reason-audited | sales/returns_services.py:637-667 | status corrected U→S: service verified; seed assignment = owner decision (§23 item 8) | EVIDENCE_CONFIRMED |
| `payments.receipt.view` | payments | **NONE** | Payment model (payments/models.py:13-25; purposes RECEIVABLE/CUSTOMER_CREDIT :8-10); no read service today | customer receipts are company-global financial records; no warehouse dimension | payment pk resolved server-side by the owning API batch | payments/models.py:13-25; absence of read functions (E4: only create/reverse/CCS services) | status corrected S→M: no read chokepoint exists | EVIDENCE_CONFIRMED |
| `payments.receipt.create` | payments | **NONE** | create_payment service (payments/services.py:111-115; posts Dr 1110 / Cr 1310\|2200 :154-193) | company-global financial operation; party resolved server-side; no object-scope restriction approved | party/currency resolved server-side (_resolve_party :45-54 enforces customer role + active) | payments/services.py:111-203 | posting occurs inside create (no separate draft phase today) | EVIDENCE_CONFIRMED |
| `payments.receipt.post` | payments | **NONE** | no separate finalize step exists; receipts are created directly POSTED via post_journal (payments/services.py:154-193; _persist_entry accounting/services.py:44-48) | company-global; the posting capability is the governed operation | payment/journal resolved server-side | payments/services.py:154-193; accounting/services.py:44-48 | key governs the posting capability that exists inside create_payment | EVIDENCE_CONFIRMED |
| `payments.receipt.reverse` | payments | **NONE** | reverse_payment service (payments/services.py:207-220; refuses settlement-linked payments :215-218) | matrix row 10 controlled reversal | payment resolved server-side; reversal routed through reverse_journal (accounting/services.py:258) | payments/services.py:207-220 | Payment row never mutated; journal reversal carries the effect | EVIDENCE_CONFIRMED |
| `payments.receipt.export` | payments | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `payments.payment.view` | payments | **NONE** | NO supplier-payment model/service exists anywhere (verified: grep SupplierPayment = 0; payments app holds only customer Payment) | matrix row 5 reserves supplier payment execution behind explicit treasury permission; company-global when built | future service resolves supplier/purchase server-side | absence check (E4 absence #5); §9A Item 1 row 5 | status corrected S→M: registered future capability, no code grounding today | EVIDENCE_CONFIRMED |
| `payments.payment.create` | payments | **NONE** | no supplier-payment service exists (verified); related flows today: supplier_advances.create (Dr 1500/Cr 1110) and supplier refunds | matrix row 5; company-global when built; execution-level sensitivity reflected by C†-style GM configuration per matrix row 8 | future service resolves supplier server-side | absence check (E4); supplier_advances/services.py:145-186 | status corrected S→M | EVIDENCE_CONFIRMED |
| `payments.payment.post` | payments | **NONE** | no supplier-payment posting service exists (verified) | matrix row 5/8; company-global when built | future service resolves supplier server-side | absence check (E4) | status corrected S→M | EVIDENCE_CONFIRMED |
| `payments.payment.reverse` | payments | **NONE** | no supplier-payment reversal service exists (verified); reverse pattern exists for customer receipts (payments/services.py:207-220) | matrix row 10 controlled reversal | future service resolves the payment server-side | absence check (E4) | status corrected S→M | EVIDENCE_CONFIRMED |
| `payments.payment.export` | payments | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `allocations.allocation.view` | allocations | **NONE** | CustomerAllocation/CustomerAllocationReversal models (allocations/models.py:9-73); read helpers payment_available/invoice_allocated/invoice_outstanding (allocations/services.py:69-92) | allocation records are company-global; same-customer invariant enforced in service | payment/sale resolved server-side (gates :174-181) | allocations/services.py:69-92 | read helpers exist (S retained) | EVIDENCE_CONFIRMED |
| `allocations.allocation.create` | allocations | **NONE** | allocate_payment (allocations/services.py:154-252; gates :174-197) | company-global financial operation; customer-match invariant prevents cross-party allocation | payment/sale/settlement resolved server-side; capacity caps computed from persisted rows | allocations/services.py:154-252 | the same-customer rule (:180-181) is a data invariant, not a user-assignment scope | EVIDENCE_CONFIRMED |
| `allocations.allocation.reverse` | allocations | **NONE** | reverse_allocation (allocations/services.py:265-295) | matrix row 10 controlled reversal | allocation resolved server-side; reason-audited | allocations/services.py:265-295 | lifecycle-gated | EVIDENCE_CONFIRMED |
| `allocations.allocation.export` | allocations | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `supplier_advances.advance.view` | supplier_advances | **NONE** | SupplierAdvance models (supplier_advances/models.py:46-145); read helpers advance_available/purchase_advance_allocated (supplier_advances/services.py:104,109) | advances are company-global; no warehouse dimension | advance/supplier resolved server-side (_party :46-55 enforces active supplier) | supplier_advances/services.py:104,109 | read helpers exist (S retained) | EVIDENCE_CONFIRMED |
| `supplier_advances.advance.create` | supplier_advances | **NONE** | create_supplier_advance (supplier_advances/services.py:145-186; posts Dr 1500/Cr 1110) | company-global financial operation | supplier/currency resolved server-side; period gate :166 | supplier_advances/services.py:145-186 | created directly POSTED | EVIDENCE_CONFIRMED |
| `supplier_advances.advance.reverse` | supplier_advances | **NONE** | reverse_supplier_advance (supplier_advances/services.py:317-343; blocks while allocations active :334-335) | matrix row 10 controlled reversal | advance resolved server-side; reason-audited | supplier_advances/services.py:317-343 | lifecycle-gated | EVIDENCE_CONFIRMED |
| `supplier_advances.advance.export` | supplier_advances | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `cash.cashaccount.view` | cash | **NONE** | CashAccount model (cash_accounts/models.py:19-31; identity master, no balances/ledger); only resolvers exist (services.py:51) | cash account master data is company-global; no read/list service exists today | account pk resolved server-side by the owning API batch | cash_accounts/models.py:19-31; cash_accounts/services.py:51,66,86,121 | status corrected S→M: no read chokepoint; create/edit/deactivate services exist (S rows) | EVIDENCE_CONFIRMED |
| `cash.cashaccount.create` | cash | **NONE** | create_cash_account (cash_accounts/services.py:66-84) | company-global master data | service creates; user = actor for audit | cash_accounts/services.py:66-84 | master-data creation | EVIDENCE_CONFIRMED |
| `cash.cashaccount.edit` | cash | **NONE** | update_cash_account (cash_accounts/services.py:86-119) | company-global master data | account resolved server-side | cash_accounts/services.py:86-119 | master-data edit | EVIDENCE_CONFIRMED |
| `cash.cashaccount.deactivate` | cash | **NONE** | set_cash_account_active (cash_accounts/services.py:121-140) | company-global master data; flag-only deactivation | account resolved server-side; reason-audited | cash_accounts/services.py:121-140 | flag-only lifecycle | EVIDENCE_CONFIRMED |
| `cash.cashaccount.export` | cash | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `treasury.operation.view` | treasury | **NONE** | no treasury model/service/endpoint exists anywhere (verified: grep -ri treasury over backend/ = 0 code hits) | matrix row 8: ACC prepares, execution/settlement/reconciliation individually configurable by GM; no warehouse dimension exists in the approved policy; any future service design must not introduce unapproved scope | future service resolves operations server-side | absence check (E4); §9A Item 1 row 8 | registered MATRIX key; all treasury keys are M | EVIDENCE_CONFIRMED |
| `treasury.operation.prepare` | treasury | **NONE** | no treasury model/service/endpoint exists anywhere (verified: grep -ri treasury over backend/ = 0 code hits) | matrix row 8: ACC prepares, execution/settlement/reconciliation individually configurable by GM; no warehouse dimension exists in the approved policy; any future service design must not introduce unapproved scope | future service resolves operations server-side | absence check (E4); §9A Item 1 row 8 | registered MATRIX key | EVIDENCE_CONFIRMED |
| `treasury.operation.execute` | treasury | **NONE** | no treasury model/service/endpoint exists anywhere (verified: grep -ri treasury over backend/ = 0 code hits) | matrix row 8: ACC prepares, execution/settlement/reconciliation individually configurable by GM; no warehouse dimension exists in the approved policy; any future service design must not introduce unapproved scope | future service resolves operations server-side | absence check (E4); §9A Item 1 row 8; sensitive (Y) | registered MATRIX key; execution C† | EVIDENCE_CONFIRMED |
| `treasury.operation.reverse` | treasury | **NONE** | no treasury model/service/endpoint exists anywhere (verified: grep -ri treasury over backend/ = 0 code hits) | matrix row 8: ACC prepares, execution/settlement/reconciliation individually configurable by GM; no warehouse dimension exists in the approved policy; any future service design must not introduce unapproved scope | future service resolves operations server-side | absence check (E4); §9A Item 1 rows 8/10; sensitive (Y) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `treasury.operation.export` | treasury | **NONE** | no treasury model/service/endpoint exists anywhere (verified: grep -ri treasury over backend/ = 0 code hits) | matrix row 8: ACC prepares, execution/settlement/reconciliation individually configurable by GM; no warehouse dimension exists in the approved policy; any future service design must not introduce unapproved scope | future export job server-side | absence check (E4); §9A Item 1 row 11 | registered MATRIX key | EVIDENCE_CONFIRMED |
| `exchange.house.view` | exchange | **NONE** | ExchangeHouse model (exchange_houses/models.py:20-31; identity master, no currency/balance); only resolver exists (services.py:51) | exchange-house master data is company-global; no per-user house assignment approved | house pk resolved server-side by the owning API batch | exchange_houses/models.py:20-31; exchange_houses/services.py:51,68,90,125 | status corrected S→M for the view row: no read chokepoint; create/edit/deactivate services exist (S rows) | EVIDENCE_CONFIRMED |
| `exchange.house.create` | exchange | **NONE** | create_exchange_house (exchange_houses/services.py:68-88) | company-global master data | service creates; user = actor for audit | exchange_houses/services.py:68-88 | master-data creation | EVIDENCE_CONFIRMED |
| `exchange.house.edit` | exchange | **NONE** | update_exchange_house (exchange_houses/services.py:90-123) | company-global master data | house resolved server-side | exchange_houses/services.py:90-123 | master-data edit | EVIDENCE_CONFIRMED |
| `exchange.house.deactivate` | exchange | **NONE** | set_exchange_house_active (exchange_houses/services.py:125-145) | company-global master data; flag-only | house resolved server-side; reason-audited | exchange_houses/services.py:125-145 | flag-only lifecycle | EVIDENCE_CONFIRMED |
| `exchange.house.export` | exchange | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `exchange.settlement.view` | exchange | **NONE** | no settlement model/service exists (verified: single model in app; settle/commission greps = docstrings+negative tests) | matrix row 8; company-global when built | future service resolves settlements server-side | absence check (E4); §15.3 M note | registered MATRIX key | EVIDENCE_CONFIRMED |
| `exchange.settlement.create` | exchange | **NONE** | no settlement service exists (verified) | matrix row 8; company-global when built | future service resolves parties/houses server-side | absence check (E4) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `exchange.settlement.reconcile` | exchange | **NONE** | no settlement/reconciliation service exists (verified) | matrix row 8: reconciliation individually configurable (C†) | future service resolves settlements server-side | absence check (E4) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `exchange.settlement.export` | exchange | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `accounting.journal.view` | accounting | **NONE** | JournalEntry/JournalLine models (accounting/models.py:46-133; statuses DRAFT/POSTED/REVERSED :21-24); read layer journals_by_source/trace_source/account_balance (accounting/balances.py:94-219) | journal entries are company-global; no warehouse/party dimension on the entry itself (party attribution lives in party_ledger) | entry/source resolved server-side by the read layer | accounting/balances.py:94-219 | read layer exists (S retained) | EVIDENCE_CONFIRMED |
| `accounting.journal.create_draft` | accounting | **NONE** | no journal draft services exist (verified: _persist_entry creates POSTED directly, accounting/services.py:44-75) | matrix row 6: ACC manages journal drafts (future); company-global | future service resolves accounts/period server-side | absence check (E5); accounting/services.py:44-75 | registered MATRIX key; draft workflow future | EVIDENCE_CONFIRMED |
| `accounting.journal.edit_draft` | accounting | **NONE** | no draft-edit service (verified); DRAFT rows ORM-editable in tests only | matrix row 6; company-global | future service resolves the draft server-side | absence check (E5); accounting/models.py:52 (DRAFT default) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `accounting.journal.delete_draft` | accounting | **NONE** | no draft-delete service (verified); UQ-9 contract | UQ-9 (§20.3); matrix row 6 | future service resolves the draft server-side; audited delete | absence check (E5); §20.3 | registered MATRIX key | EVIDENCE_CONFIRMED |
| `accounting.journal.post` | accounting | **NONE** | post_journal posts directly (accounting/services.py:44-75,188,227,243); human routine-posting API future | matrix row 6: post eligible routine entries only when explicitly permitted (C†); fiscal gate applies | entry resolved server-side; assert_posting_date_open gate | accounting/services.py:188,44-75; fiscal_periods/services.py:121-138 | registered MATRIX key; system auto-posting exists, human post API future | EVIDENCE_CONFIRMED |
| `accounting.journal.cancel` | accounting | **NONE** | no cancel service (verified); UQ-9 contract | UQ-9; matrix row 10 | future service resolves the draft server-side | absence check (E5); §20.3 | registered MATRIX key | EVIDENCE_CONFIRMED |
| `accounting.journal.reverse` | accounting | **NONE** | reverse_journal service (accounting/services.py:258-344; rejects DRAFT/double-reversal; period gate :306) | matrix row 10: controlled reversal only; posted history immutable (models.py:76-95) | entry resolved server-side (row-locked :274); reason required | accounting/services.py:258-344; accounting/models.py:76-95 | service exists (S retained); sensitive (Y) | EVIDENCE_CONFIRMED |
| `accounting.report.view` | accounting | **NONE** | read-only balances layer (accounting/balances.py:1-17,94-219; trial_balance :128-187) | balances/reports are company-global | queries executed server-side; mixed-currency refusal :77-91 | accounting/balances.py:1-17,128-187 | read layer exists (S retained); no HTTP endpoint yet | EVIDENCE_CONFIRMED |
| `accounting.report.export` | accounting | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `accounting.coa.view` | accounting | **NONE** | Account model (accounting/models.py:30-43); COA seeded by command (coa.py:83-136); no COA endpoints | chart of accounts is global accounting configuration (matrix rows 3/6) | account resolved server-side by the future API | accounting/models.py:30-43; accounting/coa.py:83-136; bootstrap command :197 | registered MATRIX key | EVIDENCE_CONFIRMED |
| `accounting.coa.create` | accounting | **NONE** | no COA create endpoint/service beyond canonical seed (verified) | matrix row 3: structural accounting configuration GM-controlled; C† | future service validates parent/type server-side | absence check (E5) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `accounting.coa.edit` | accounting | **NONE** | no COA edit endpoint/service (verified) | matrix row 3; C† | future service resolves the account server-side | absence check (E5) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `currencies.rate.view` | currencies | **NONE** | Currency/ExchangeRate models (currencies/models.py:6-55); NO currencies service module exists (verified); FX posting lives in accounting/fx.py | currencies/rates are company-global master data | rate queries server-side by the future API | currencies/models.py:6-55; absence check (E4) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `currencies.rate.create` | currencies | **NONE** | Currency/ExchangeRate models (currencies/models.py:6-55); NO currencies service module exists (verified); FX posting lives in accounting/fx.py | matrix row 3: routine maintenance where explicitly delegated (C†) | future service validates pair/date server-side | currencies/models.py:33-55 (unique pair+date constraint :52-55) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `currencies.rate.edit` | currencies | **NONE** | Currency/ExchangeRate models (currencies/models.py:6-55); NO currencies service module exists (verified); FX posting lives in accounting/fx.py | matrix row 3; C† | future service resolves the rate row server-side | absence check (E4) | registered MATRIX key | EVIDENCE_CONFIRMED |
| `currencies.rate.export` | currencies | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `parties.party.view` | parties | **NONE** | Party model (parties/models.py:18-39; is_customer/is_supplier flags :21-22; no balances); only resolver exists (parties/services.py:63-75); no read service/endpoint | party master data is company-global; WK holders get minimum-fields-only views per matrix row 2 (field-level restriction, not object scope) | party pk resolved server-side by the owning API batch; WK serializer restricts fields | parties/models.py:18-39; parties/services.py:63-75; §9A Item 1 row 2 | status corrected S→M: no read chokepoint; WK restriction is field-level (serializer concern) | EVIDENCE_CONFIRMED |
| `parties.party.create` | parties | **NONE** | create_party (parties/services.py:78-100) | company-global master data | service creates; user = actor | parties/services.py:78-100 | no persisted parent context at creation | EVIDENCE_CONFIRMED |
| `parties.party.edit` | parties | **NONE** | update_party (parties/services.py:104-150) | company-global master data | party resolved server-side | parties/services.py:104-150 | role-flag invariant revalidated :130-137 | EVIDENCE_CONFIRMED |
| `parties.party.deactivate` | parties | **NONE** | set_party_active (parties/services.py:154-172) | company-global master data; flag-only | party resolved server-side; reason-audited | parties/services.py:154-172 | flag-only lifecycle | EVIDENCE_CONFIRMED |
| `parties.party.export` | parties | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11: party exports permitted for ACC; bulk export separately permissioned | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `products.product.view` | products | **NONE** | Product model (products/models.py:17-77; ref_purchase_price/ref_sales_price :36-41; no transactional cost field); only resolver exists (products/services.py:83); no read service/endpoint | product master data is company-global; WK holders get name/code/UOM-only views per matrix (no cost/price) - field-level restriction, not object scope | product pk resolved server-side by the owning API batch; WK serializer excludes reference prices | products/models.py:17-77,36-41; products/services.py:83; §9A Item 1 row 2/7 | status corrected S→M: no read chokepoint; WK restriction is field-level (serializer concern) | EVIDENCE_CONFIRMED |
| `products.product.create` | products | **NONE** | create_product (products/services.py:141-200) | company-global master data | service creates; category/UOM resolved server-side (:69-80) | products/services.py:141-200 | no parent context at creation | EVIDENCE_CONFIRMED |
| `products.product.edit` | products | **NONE** | update_product (products/services.py:211-284) | company-global master data | product resolved server-side | products/services.py:211-284 | editable-fields whitelist :203-208 | EVIDENCE_CONFIRMED |
| `products.product.deactivate` | products | **NONE** | set_product_active (products/services.py:287-306) | company-global master data; flag-only | product resolved server-side; reason-audited | products/services.py:287-306 | flag-only lifecycle | EVIDENCE_CONFIRMED |
| `products.product.export` | products | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `catalog.category.view` | catalog | **NONE** | Category model (categories/models.py:11-26); UOM model (uom/models.py:11-26); services create/update/set_active (categories/services.py:62,81,112; uom/services.py:62,81,112) | category/UOM master data is company-global; no warehouse/party dimension | object pk resolved server-side by the owning API batch | categories/models.py:11-26; uom/models.py:11-26; services lines above | status corrected S→M: no read chokepoint (resolver only) | EVIDENCE_CONFIRMED |
| `catalog.category.create` | catalog | **NONE** | Category model (categories/models.py:11-26); UOM model (uom/models.py:11-26); services create/update/set_active (categories/services.py:62,81,112; uom/services.py:62,81,112) | category/UOM master data is company-global; no warehouse/party dimension | object pk resolved server-side by the owning API batch | categories/models.py:11-26; uom/models.py:11-26; services lines above | service exists (S row); master-data creation | EVIDENCE_CONFIRMED |
| `catalog.category.edit` | catalog | **NONE** | Category model (categories/models.py:11-26); UOM model (uom/models.py:11-26); services create/update/set_active (categories/services.py:62,81,112; uom/services.py:62,81,112) | category/UOM master data is company-global; no warehouse/party dimension | object pk resolved server-side by the owning API batch | categories/models.py:11-26; uom/models.py:11-26; services lines above | service exists (S row) | EVIDENCE_CONFIRMED |
| `catalog.category.deactivate` | catalog | **NONE** | Category model (categories/models.py:11-26); UOM model (uom/models.py:11-26); services create/update/set_active (categories/services.py:62,81,112; uom/services.py:62,81,112) | category/UOM master data is company-global; no warehouse/party dimension | object pk resolved server-side by the owning API batch | categories/models.py:11-26; uom/models.py:11-26; services lines above | flag-only lifecycle (S row) | EVIDENCE_CONFIRMED |
| `catalog.category.export` | catalog | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `catalog.uom.view` | catalog | **NONE** | Category model (categories/models.py:11-26); UOM model (uom/models.py:11-26); services create/update/set_active (categories/services.py:62,81,112; uom/services.py:62,81,112) | category/UOM master data is company-global; no warehouse/party dimension | object pk resolved server-side by the owning API batch | categories/models.py:11-26; uom/models.py:11-26; services lines above | status corrected S→M: no read chokepoint (resolver only) | EVIDENCE_CONFIRMED |
| `catalog.uom.create` | catalog | **NONE** | Category model (categories/models.py:11-26); UOM model (uom/models.py:11-26); services create/update/set_active (categories/services.py:62,81,112; uom/services.py:62,81,112) | category/UOM master data is company-global; no warehouse/party dimension | object pk resolved server-side by the owning API batch | categories/models.py:11-26; uom/models.py:11-26; services lines above | service exists (S row) | EVIDENCE_CONFIRMED |
| `catalog.uom.edit` | catalog | **NONE** | Category model (categories/models.py:11-26); UOM model (uom/models.py:11-26); services create/update/set_active (categories/services.py:62,81,112; uom/services.py:62,81,112) | category/UOM master data is company-global; no warehouse/party dimension | object pk resolved server-side by the owning API batch | categories/models.py:11-26; uom/models.py:11-26; services lines above | service exists (S row) | EVIDENCE_CONFIRMED |
| `catalog.uom.deactivate` | catalog | **NONE** | Category model (categories/models.py:11-26); UOM model (uom/models.py:11-26); services create/update/set_active (categories/services.py:62,81,112; uom/services.py:62,81,112) | category/UOM master data is company-global; no warehouse/party dimension | object pk resolved server-side by the owning API batch | categories/models.py:11-26; uom/models.py:11-26; services lines above | flag-only lifecycle (S row) | EVIDENCE_CONFIRMED |
| `catalog.uom.export` | catalog | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `warehouses.warehouse.view` | warehouses | **NONE** | Warehouse model (warehouses/models.py:19-34; NO keeper/user FK - verified); warehouses/services.py create/update/set_active (:64,:84,:117) | key-level NONE: ACC views all warehouses (master data); WK cell carries (W) 'assigned only' per matrix row 7 - an assignment-based data filter for WK holders only (role-conditional; see §23 item 9) | warehouse pk/list resolved server-side; WK filter will use the M6 UserWarehouseScope registry (approved model set; not yet implemented - verified absent) | warehouses/models.py:19-34; absence check (E2: grep keeper\|UserWarehouse\|WarehouseScope = 0); §9A Item 1 row 7 | the (W) semantics for WK are grounded in the approved matrix and the approved M6 model; ACC is unrestricted by approved policy | EVIDENCE_CONFIRMED |
| `warehouses.warehouse.create` | warehouses | **NONE** | Warehouse model (warehouses/models.py:19-34; NO keeper/user FK - verified); warehouses/services.py create/update/set_active (:64,:84,:117) | company-global master data (matrix row 3 pattern; C† for ACC) | service creates (services.py:64-81); user = actor for audit | warehouses/services.py:64-81 | master-data creation; no endpoints yet (S row) | EVIDENCE_CONFIRMED |
| `warehouses.warehouse.edit` | warehouses | **NONE** | Warehouse model (warehouses/models.py:19-34; NO keeper/user FK - verified); warehouses/services.py create/update/set_active (:64,:84,:117) | company-global master data (C†) | warehouse resolved server-side (resolve_warehouse :49-61) | warehouses/services.py:84-114 | master-data edit (S row) | EVIDENCE_CONFIRMED |
| `warehouses.warehouse.deactivate` | warehouses | **NONE** | Warehouse model (warehouses/models.py:19-34; NO keeper/user FK - verified); warehouses/services.py create/update/set_active (:64,:84,:117) | company-global master data; flag-only (C†) | warehouse resolved server-side; reason-audited | warehouses/services.py:117-136 | flag-only lifecycle (S row) | EVIDENCE_CONFIRMED |
| `warehouses.warehouse.export` | warehouses | **NONE** | no export infrastructure repo-wide (verified); future | matrix row 11 | export job server-side | absence check (E1/E5) | registered future capability | EVIDENCE_CONFIRMED |
| `inventory.movement.view` | inventory | **WAREHOUSE_REQUIRED** | StockMovement model + read helpers movements_for/stock_for/avco_for (inventory/stock.py:26-89) | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse resolved server-side; list/read queries filtered to warehouses assigned via M6 | inventory/models.py:73-178,90-94; inventory/stock.py:26-89 | movement history is the only stock truth (stock.py:1); (W) in ACC and WK cells | EVIDENCE_CONFIRMED |
| `inventory.movement.create` | inventory | **WAREHOUSE_REQUIRED** | receive_stock/issue_stock/open_stock/transfer_stock/adjustment services (inventory/services.py:508-720,764-953,959-1036) - all take warehouse kwarg resolved server-side | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse kwarg must belong to the caller's assigned set; resolve_warehouse (:120-125) validates existence; M6 membership check by the resolver | inventory/services.py:508-540,543-621,628-720,811-953,959-1036 | (W) in ACC and WK cells; services already take explicit warehouse | EVIDENCE_CONFIRMED |
| `inventory.movement.reverse` | inventory | **NONE** | approved compensating-path services: purchase_return/sales_return (inventory/services.py:1353-1379) and return-stock reversals (:1453-1543); posted movements immutable (models.py:166-178) | no (W) marker: ACC reversal is not warehouse-restricted by approved policy; the compensating movement inherits the source movement's warehouse (object context, not user scope) | source movement resolved server-side; warehouse derived from the persisted row (_lock_stock_identity) | inventory/services.py:1353-1379,1453-1543; inventory/models.py:166-178 | reversal capability routed through approved return paths (S retained) | EVIDENCE_CONFIRMED |
| `inventory.movement.export` | inventory | **WAREHOUSE_REQUIRED** | no export infrastructure repo-wide (verified); future | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse resolved server-side; list/read queries filtered to warehouses assigned via M6 | absence check (E1/E5); §9A Item 1 row 7 | (W) in ACC cell; export of assigned-warehouse movement data | EVIDENCE_CONFIRMED |
| `inventory.count.view` | inventory | **WAREHOUSE_REQUIRED** | no stock-count model/service/endpoint exists (verified: inventory migrations 0001-0005 create only StockMovement/WarehouseInventoryAccount/ShortageSettlement/InventoryReturn) | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry; future count documents will carry the warehouse FK | warehouse resolved server-side; list/read queries filtered to warehouses assigned via M6 | absence check (E2); §9A Item 1 row 7 | (W) in ACC and WK cells; M status retained (no count model yet) | EVIDENCE_CONFIRMED |
| `inventory.count.create` | inventory | **WAREHOUSE_REQUIRED** | no count model/service exists (verified) | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse resolved server-side; list/read queries filtered to warehouses assigned via M6 | absence check (E2) | (W) in ACC and WK cells; M status retained | EVIDENCE_CONFIRMED |
| `inventory.count.export` | inventory | **WAREHOUSE_REQUIRED** | no count model/export infra exists (verified) | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse resolved server-side; list/read queries filtered to warehouses assigned via M6 | absence check (E2) | (W) in ACC cell; M status retained | EVIDENCE_CONFIRMED |
| `inventory.adjustment.view` | inventory | **WAREHOUSE_REQUIRED** | adjustments are ADJUSTMENT_IN/OUT StockMovement rows via _adjustment_operation (inventory/services.py:959-1036); read coverage via stock.py movement queries | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse resolved server-side; list/read queries filtered to warehouses assigned via M6 | inventory/services.py:959-1036 | (W) in ACC cell; S retained (movement read layer covers adjustment rows) | EVIDENCE_CONFIRMED |
| `inventory.adjustment.create` | inventory | **WAREHOUSE_REQUIRED** | adjust_stock_in/adjust_stock_out services (inventory/services.py:1025-1036 → _adjustment_operation :959-1022; warehouse kwarg) | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse kwarg must belong to the caller's assigned set; negative-stock acknowledgement gate :988-1005 | inventory/services.py:959-1036 | (W) in ACC cell; S retained | EVIDENCE_CONFIRMED |
| `inventory.adjustment.post` | inventory | **WAREHOUSE_REQUIRED** | adjustments post immediately inside _adjustment_operation (inventory/services.py:959-1022; fiscal gate :967) | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse kwarg server-resolved; posting is atomic with the movement | inventory/services.py:959-1022 | (W) in ACC cell; S retained | EVIDENCE_CONFIRMED |
| `inventory.adjustment.reverse` | inventory | **NONE** | no adjustment-reversal service exists (verified: only the two sales-return stock reversals, inventory/services.py:1453-1543); correction = compensating movement contract | no (W) marker: ACC reversal not warehouse-restricted by approved policy; compensating movement inherits source warehouse (object context) | source movement resolved server-side; warehouse derived from the persisted row | absence check (E2); inventory/models.py:170-177 | status corrected S→M: no adjustment-reversal chokepoint today | EVIDENCE_CONFIRMED |
| `inventory.adjustment.export` | inventory | **WAREHOUSE_REQUIRED** | no export infrastructure repo-wide (verified); future | (W) appears in the Accountant cell - the restriction applies to ALL holders of the key per approved matrix row 7 ('subject to assigned scope and stock controls'); enforced against the M6 UserWarehouseScope registry | warehouse resolved server-side; list/read queries filtered to warehouses assigned via M6 | absence check (E1/E5) | (W) in ACC cell; M status retained | EVIDENCE_CONFIRMED |
| `reporting.dashboard.view` | reporting | **NONE** | no dashboard API/model exists (verified: grep dashboard over backend/ = 0) | key-level NONE: ACC sees operational+finance summaries per matrix row 1 ('within assigned permissions'); WK cell carries (W) - warehouse-summaries-only is an assignment-based DATA filter for WK holders (role-conditional; see §23 item 9) | future dashboard service computes aggregates server-side; WK filtering via M6; ACC data gated by the user's other permissions per matrix row 1 | absence check (E5); §9A Item 1 row 1; §15.3 M note | M status retained; role-conditional data filtering documented rather than key-level scope | EVIDENCE_CONFIRMED |
| `documents.document.view` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |
| `documents.document.create` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |
| `documents.document.edit_draft` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |
| `documents.document.delete_draft` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |
| `documents.document.submit` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |
| `documents.document.approve` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |
| `documents.document.post` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |
| `documents.document.cancel` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |
| `documents.document.export` | documents | **UNRESOLVED** | OD-6 owner decision contract only (docs/decisions/OD-6_DOCUMENT_WORKFLOW_OWNER_DECISION.md); documents app = document numbering only (documents/models.py:4-12) | no persisted document/assignment model exists; scope unknowable until the OD-6 batch defines workflow objects | undefined until the OD-6 batch | documents/models.py:4-12; absence check (E5: grep attachment\|FileField\|ImageField = 0); OD-6 decision doc | UNRESOLVED - FAIL CLOSED - NOT ELIGIBLE FOR SEEDING. OD-6 document workflow is unimplemented: the documents app contains only NumberSequence (documents/models.py:4-12); no attachment models or FileField exist repo-wide (verified). Object scope ('assigned documents') cannot be established without the OD-6 design. This is a design-time classification, not a runtime policy; RESERVED seed disposition unchanged. | UNRESOLVED |

**Registry totals:** 162 rows · 162 unique keys · scope: NONE=140, WAREHOUSE_REQUIRED=10, OBJECT_REQUIRED=2, UNRESOLVED=10 · status: EVIDENCE_CONFIRMED=152, UNRESOLVED=10. The ten `WAREHOUSE_REQUIRED` keys are exactly the ten inventory keys carrying an Accountant-column `(W)` marker; the two `OBJECT_REQUIRED` keys are the self-scope keys; the ten `UNRESOLVED` keys are `documents.document.*` (9) and `sales.document.approve`.

## 16. Authorization resolver — corrected technical encoding (Rev 2 — defect G fix)

### 16.1 Binding evaluation sequence

The resolver (`backend/security/authorization.py`, W0-2A; dormant — zero view wiring in W0-2A) MUST evaluate in exactly this order. **No permission-grant lookup (catalog, overrides, roles) may occur before steps 1–3 have passed.** This satisfies Item 2 rule 1 precisely and prevents catalog-existence probing by unauthenticated callers.

1. **Authentication** — `user` is None or `not user.is_authenticated` → DENY `UNAUTHENTICATED`. Nothing is persisted (frozen Batch 3 pin preserved).
2. **Account state** — `not user.is_active` → DENY `INACTIVE_ACCOUNT`; account locked (`locked_until > now`, W0-2D; a no-op check until D ships) → DENY `ACCOUNT_LOCKED`.
3. **Session validity** — authentication layer MUST provide trusted session context; never infer validity from caller-supplied booleans/request fields. Validate server-side Django session and expiry; when W0-2D records exist, validate binding/revocation. Invalid, absent where required, or expired → DENY `NO_ACTIVE_SESSION`. BasicAuthentication-only context is insufficient for MFA-protected routes.
4. **Permission-key resolution (first catalog touch)** — unknown/inactive key → DENY `UNKNOWN_PERMISSION` + warning log. The entire resolver—including account-lock/session checks and permission, override, role, scope, and GM-capability lookups—MUST be inside one fail-closed exception boundary. Expected denials retain their reason; unexpected DB/cache/resolver errors return DENY `FAIL_CLOSED` and log. No exception may escape before an authorization decision or fall through as ALLOW.
5. **Protected GM authority** — active GM role assignment AND key ∈ GM capability set (§15.3 GM seed rule) → ALLOW `GM_PROTECTED`. Overrides are never consulted for GM. Domain invariants still apply downstream (they live below the resolver). A locked/inactive GM is denied at steps 2–3 — this is the owner-approved D9 lockout applying universally, not an authority change.
6. **Explicit deny** — active user override with `effect=DENY` → DENY `USER_DENY`.
7. **Explicit allow** — active user override with `effect=ALLOW` → evaluate scope (step 8); pass → ALLOW `USER_ALLOW`.
8. **Mandatory object-scope policy** — every permission/operation MUST declare server-owned scope policy `NONE`, `WAREHOUSE_REQUIRED`, or `OBJECT_REQUIRED`. For every non-GM grant with policy other than `NONE`, trusted scope is mandatory. Missing scope, unresolved object, inability to derive warehouse/owner, mismatch, or scope error → DENY `SCOPE_DENIED`. `scope=None` is valid only for policy `NONE`. Derive scope from persisted target object/server-side route context; client-supplied IDs/booleans are not authoritative. Applies equally to role grants and explicit user ALLOW; ALLOW never bypasses scope. GM may use global scope but remains subject to domain invariants.
9. **Role-derived permissions** — key ∈ union of ACTIVE role grants → scope check → ALLOW `ROLE_GRANT`.
10. **Default deny** — otherwise DENY `NO_GRANT`.

Conflict rules (binding): explicit DENY (6) precedes explicit ALLOW (7) and role union (9) — a role grant can never override an explicit denial; if both a live ALLOW and DENY existed (the schema of §14.4 makes this unreachable), DENY wins; GM protection (5) precedes overrides — ordinary overrides can never revoke GM authority (D3); unknown keys and all errors fail closed.

### 16.2 Corrected pseudocode

```python
def resolve(user, permission_key, *, auth_context, resource=None, at=None) -> PermissionDecision:
    """Conceptual contract; security-sensitive inputs are server-derived."""
    at = at or timezone.now()
    trace = []
    try:
        if user is None or not user.is_authenticated:
            return deny("UNAUTHENTICATED", trace)  # preserve Batch 3 no-persist behavior
        if not user.is_active:
            return deny("INACTIVE_ACCOUNT", trace)
        if account_locked(user, at):
            return deny("ACCOUNT_LOCKED", trace)
        if not auth_context.is_valid_for(user, at):
            return deny("NO_ACTIVE_SESSION", trace)
        if auth_context.is_basic_only and auth_context.requires_mfa:
            return deny("MFA_REQUIRED", trace)
        perm = Permission.objects.get(key=permission_key, is_active=True)
        if has_active_role(user, RoleCode.GM, at) and perm.key in gm_capability_set(at):
            return allow("GM_PROTECTED", trace)
        override = active_override(user, perm, at)
        if override is not None and override.effect == Effect.DENY:
            return deny("USER_DENY", trace)
        policy = permission_scope_policy(perm)  # server-owned registry metadata
        trusted_scope = derive_scope_from_persisted_resource(resource, policy)
        if policy != ScopePolicy.NONE:
            if trusted_scope is None or not trusted_scope.allows(user, perm):
                return deny("SCOPE_DENIED", trace)
        elif trusted_scope is not None and not trusted_scope.is_consistent_with(resource):
            return deny("SCOPE_DENIED", trace)
        if override is not None and override.effect == Effect.ALLOW:
            return allow("USER_ALLOW", trace)
        if perm.key in union_of_active_role_permissions(user, at):
            return allow("ROLE_GRANT", trace)
        return deny("NO_GRANT", trace)
    except Permission.DoesNotExist:
        return deny("UNKNOWN_PERMISSION", trace)  # server-side warning log
    except Exception:
        log_resolver_failure(permission_key=permission_key, user_id=getattr(user, "pk", None))
        return deny("FAIL_CLOSED", trace)
```

### 16.3 Resolver test additions (extends R1–R13)

| # | Case | Expected |
|---|---|---|
| R14 | locked account (GM included) | DENY `ACCOUNT_LOCKED` — evaluated before GM step |
| R15 | live ALLOW+DENY pair (only reachable by manual DB tampering) | DENY `USER_DENY` (defensive deny-wins) |
| R16 | structural: query-count assertion — resolver performs **zero** Permission/override/role queries when called with `AnonymousUser` | order proof (no catalog leak) |
| R17 | expired-but-unsettled assignment (end_at past, revoked_at NULL) | resolver denies (ACTIVE predicate); settlement converts to `EXPIRED` and re-grant then succeeds |
| R18 | unknown key with authenticated user | DENY `UNKNOWN_PERMISSION` + warning log; unknown key with anonymous user → DENY `UNAUTHENTICATED` (never `UNKNOWN_PERMISSION`) |

### 16.4 Mandatory scope and resolver-failure tests (Revision 4)

| # | Case | Expected |
|---|---|---|
| R19 | Warehouse Keeper has role grant but no trusted scope | DENY `SCOPE_DENIED` |
| R20 | Client supplies warehouse ID outside assignment | DENY `SCOPE_DENIED`; client value is not authority |
| R21 | Warehouse Keeper has explicit ALLOW but no/mismatched scope | DENY `SCOPE_DENIED` |
| R22 | Accountant operation marked `WAREHOUSE_REQUIRED` with no scope | DENY `SCOPE_DENIED` |
| R23 | User accesses resource in assigned warehouse | Grant only if role/override and domain checks pass |
| R24 | Permission policy is `NONE` | No warehouse scope required; all other checks apply |
| R25 | DB error during permission/override/role/scope lookup | DENY `FAIL_CLOSED`; error logged; no grant |
| R26 | Non-GM staff or superuser requests Django Admin | DENY at AdminSite gate |
| R27 | GM BasicAuthentication-only request to MFA-protected route | DENY; password alone cannot satisfy MFA |

## 17. AuditAction inventory and field length (Rev 2 — defect C fix)

### 17.1 Defect

`AuditEvent.action` is `CharField(max_length=20)` (verified, `security/models.py:18`). Revision 1's proposed action names include names up to **26 characters**, which would be truncated/rejected. Verified inventory:

### 17.2 Existing members (unchanged — no rename, no shortening)

| Member | Length |
|---|---|
| `LOGIN` | 5 |
| `LOGOUT` | 6 |
| `CREATE` | 6 |
| `UPDATE` | 6 |
| `POST` | 4 |
| `REVERSE` | 7 |
| `APPROVE` | 7 |

### 17.3 Proposed additions (complete inventory, W0-2E enum extension)

| Member | Length | Born in |
|---|---|---|
| `LOGIN_SUCCESS` | 13 | C |
| `LOGIN_FAILED` | 12 | C |
| `ACCOUNT_CREATED` | 15 | C |
| `ACCOUNT_ACTIVATED` | 18 | C |
| `ACCOUNT_DEACTIVATED` | 20 | C |
| `ACCOUNT_RECOVERY` | 16 | C |
| `ACCOUNT_BOOTSTRAP` | 17 | C |
| `ACCOUNT_LOCKED` | 14 | C/D |
| `ACCOUNT_UNLOCKED` | 15 | C/D |
| `ACCOUNT_EMERGENCY_RECOVERY` | **26 (max)** | C |
| `ROLE_ASSIGNED` | 13 | C |
| `ROLE_REVOKED` | 12 | C |
| `PERMISSION_GRANTED` | 18 | C |
| `PERMISSION_REVOKED` | 18 | C |
| `PERMISSION_DENIED` | 17 | B |
| `SESSION_STARTED` | 15 | D |
| `SESSION_TERMINATED` | 18 | D |
| `MFA_ENROLLED` | 12 | C |
| `MFA_REVOKED` | 11 | C |
| `MFA_RESET` | 9 | C |
| `RECOVERY_CODES_ROTATED` | 22 | C |
| `ACCESS_GRANTED` | 14 | B/C (grant/replacement audit) |
| `ACCESS_EXTENDED` | 15 | B/C (renewal audit, §14.7) |
| `ACCESS_REVOKED` | 14 | B/C |
| `AUDIT_CHECKPOINT` | 16 | E |
| `DELETE` | 6 | B (audited draft deletion, §20) |

**Maximum proposed length = 26 (`ACCOUNT_EMERGENCY_RECOVERY`).**

### 17.4 Corrected field-length recommendation and naming convention

- **`action` field length: `CharField(max_length=40)`** (was 20). Rationale: max today 26; 40 gives headroom; lengthening a CharField is backward-compatible (existing 7 values fit).
- **Naming convention (binding):** UPPER_SNAKE_CASE; pattern `<SUBJECT>_<PAST_TENSE_VERB>` or `<SUBJECT>_<QUALIFIER>_<VERB>`; maximum 3 underscore-separated segments; each segment ≤ 12 chars; total ≤ 40 chars. Enforced by a unit test that iterates `AuditAction.choices` and by the registry constant `AUDIT_ACTION_MAX_LENGTH = 40`.
- **Migration:** one `AlterField` (20 → 40) in W0-2E (combined with the additive choices extension). PostgreSQL widens the column (metadata-only); SQLite performs the standard Django table rebuild. Existing business event names are **not** renamed or shortened.

## 18. Audit hash-chain integrity and concurrency (Revision 3 — defects D/E corrected)

### 18.1 Defects corrected

Revision 2 had two incomplete guarantees:

1. It computed a payload hash without incorporating the previous event hash. That produces individually hashed events, not a cryptographically linked hash chain.
2. It assumed that the audit-head UPDATE would be the first write in the SQLite transaction. Existing business transactions may already have performed reads before calling the audit service. In SQLite's default DEFERRED mode, a read transaction that later attempts to upgrade to a writer can fail with a busy/snapshot conflict; the audit service cannot retroactively make its UPDATE the transaction's first statement.

Django documents that SQLite's default transaction mode is DEFERRED, that IMMEDIATE obtains the write reservation at transaction start, and that select_for_update() has no effect on SQLite. Therefore atomic() by itself and a late UPDATE are not a sufficient cross-engine serialization contract. See the [Django 5.2 database documentation on SQLite transaction behavior](https://docs.djangoproject.com/en/5.2/ref/databases/#transactions-behavior), which documents DEFERRED/IMMEDIATE modes and the absence of SQLite select_for_update() support.

### 18.2 Event fields and canonical hash definition

The W0-2E audit-chain extension must add the following immutable fields to each audit event:

- event_uuid: application-generated UUID, created before the INSERT and unique.
- prev_event_hash: 64-character lowercase hexadecimal SHA-256 digest; the first event uses 64 zeroes.
- event_hash: 64-character lowercase hexadecimal SHA-256 digest.

The database schema must enforce uniqueness for event_uuid, event_hash, and prev_event_hash. Unique prev_event_hash ensures that no committed event can create a second successor from the same chain link; the genesis all-zero previous hash can therefore occur only once. The verifier independently checks these constraints and reports any fork or duplicate as corruption.

The canonical payload is a versioned object containing every immutable persisted audit-event field other than the database-generated primary key and the two chain fields. It MUST include event_uuid and all available actor, action, target/resource, timestamp, request-origin, and metadata fields. The canonicalization contract is:

- UTF-8 JSON, recursively sorted object keys, compact separators, explicit nulls, and no NaN/Infinity.
- Timestamps normalized to UTC ISO-8601 with a fixed precision and explicit Z suffix.
- Decimal values serialized as canonical decimal strings; UUIDs as lowercase canonical strings.
- Metadata must contain only supported JSON scalar/list/object values; unsupported Python objects and binary values are rejected, not stringified with repr().
- The payload includes a fixed schema/version identifier so future canonicalization changes are explicit and verifiable.

For each event, calculate:

    payload_bytes = canonical_json_bytes(versioned_immutable_event_payload)
    previous_hash_bytes = bytes.fromhex(prev_event_hash)
    event_hash = SHA256(
        b"HESABDARI-AUDIT-CHAIN-V1\x00"
        + previous_hash_bytes
        + payload_bytes
    ).hexdigest()

The domain-separation prefix is a fixed protocol constant, not configurable at runtime. The previous hash is part of the digest input. Storing prev_event_hash without incorporating it into event_hash is prohibited.

The verifier MUST recompute each event_hash from its canonical payload and prev_event_hash, verify that the first event links to the all-zero genesis hash, verify that every subsequent event links to exactly one preceding event_hash, detect missing links/forks/duplicate event UUIDs, and verify that AuditChainHead matches the final verified event. Verification order follows the hash links, not assumptions about timestamp ordering. The database primary key is a locator only; it is not the cryptographic chain order.

### 18.3 Transactional writer protocol

New W0-2E model: AuditChainHead singleton with fixed id=1, head_hash, last_event_id, and updated_at. It is initialized with the genesis hash and a null/zero last-event pointer appropriate to the model field.

Every audit write remains inside the same database transaction as its business operation. Under the chain lock, the writer:

1. Acquires the AuditChainHead row for writing before reading its current hash.
2. Reads head_hash only after acquiring that write lock.
3. Creates event_uuid and constructs the canonical immutable payload.
4. Sets prev_event_hash to the locked head_hash and computes event_hash using §18.2.
5. Inserts the event once, with all chain fields populated in the INSERT; the append-only trigger must never require a later UPDATE to the event row.
6. Updates AuditChainHead.head_hash to the new event_hash and last_event_id to the inserted row's primary key.
7. Commits the business mutation, audit event, and chain-head update atomically.

Any failure rolls back the business mutation, event insert, and head update together. There is no separate audit transaction and no post-commit audit write.

PostgreSQL: the first chain operation is UPDATE of the singleton AuditChainHead row (or an equivalent row-lock acquisition before the head SELECT). Under the repository's normal READ COMMITTED isolation, the subsequent SELECT sees the latest committed head after any lock wait. The implementation must not silently assume this behavior under REPEATABLE READ/SERIALIZABLE; if another isolation level is configured, the lock/read strategy and tests must be revisited. The singleton row serializes writers; select_for_update() may be used on PostgreSQL but is not the portability mechanism.

### 18.4 SQLite transaction-start requirement — mandatory, not an optional late lock

For SQLite, the supported chain-writer contract is:

- The outermost transaction for every audit-producing business operation MUST begin with SQLite transaction_mode=IMMEDIATE. This obtains the database write reservation at BEGIN, before business-service reads and before any audit-head read. This is the same transaction-start rule imposed on grant-writing services in §14.6; both workflows use one consistent outermost boundary.
- Configure Django's SQLite database OPTIONS with transaction_mode="IMMEDIATE" for every SQLite database alias that can execute audit-producing business operations. Django >=5.2 supports this setting. It is a connection-level transaction policy and affects all outermost atomic transactions on that alias, not just the audit function.
- Nested atomic() blocks are savepoints; they do not change an already-open outer transaction from DEFERRED to IMMEDIATE. Therefore an audit-producing operation MUST NOT be entered inside an ambient DEFERRED transaction. The implementation inventory must inspect request wrappers, ATOMIC_REQUESTS, tests, management commands, and service callers to prove the IMMEDIATE transaction is outermost.
- If the application cannot guarantee that boundary, SQLite hash-chain concurrency is NOT supported by that call path and the implementation must STOP rather than claim that a late AuditChainHead UPDATE repairs it.
- Set an explicit SQLite timeout/busy_timeout. A lock/busy error aborts and rolls back the entire outer business transaction. A retry, if needed, may only retry the entire business operation from its outermost boundary and only where the operation has an idempotency guarantee. Never catch a lock error and retry only the audit insert/head update inside a broken transaction.
- The owner must explicitly approve the global SQLite IMMEDIATE setting because it changes transaction behavior for all outermost transactions on that SQLite connection and can reduce write concurrency/throughput. If the owner declines, W0-2E must present a different proven transaction-boundary architecture; it may not silently fall back to DEFERRED plus a late UPDATE.

This requirement is stronger and more accurate than Revision 2's claim that a first UPDATE inside the audit function is always the first transaction write. The audit function cannot know or undo reads that happened earlier in the caller's transaction.

### 18.5 Guarantees and boundaries

- Serialization: SQLite serializes audit-producing outer transactions from BEGIN IMMEDIATE; PostgreSQL serializes on the singleton head row.
- Chain integrity: each event_hash commits to both the immutable payload and the previous event_hash. A changed payload, changed previous link, missing event, duplicate successor, or fork is detected by verification.
- Atomicity: business state, inserted audit event, and head pointer commit or roll back together.
- Ordering: the previous-hash link defines the canonical order. Do not use created_at or primary-key ordering as a substitute for verifying the links.
- Append-only compatibility: all event chain fields are populated at INSERT time. No later UPDATE to an audit event is permitted; the existing append-only database triggers remain authoritative.
- No unbounded or partial-transaction retries. A retry must restart the entire outer business transaction and preserve the operation's idempotency contract.

### 18.6 Required concurrency and integrity tests (both engines)

| # | Test | Assertion |
|---|---|---|
| CH1 | PostgreSQL concurrent writers (8 independent connections × 25 events) | One unbranched chain; every digest verifies; head equals final event |
| CH2 | SQLite concurrent writers using IMMEDIATE outermost transactions | No stale-head read, fork, or partial commit; lock waiting follows configured timeout |
| CH3 | SQLite negative control using DEFERRED with a read before the first write | Test demonstrates the unsafe upgrade/race path; implementation does not claim this path is supported |
| CH4 | Rollback injection after event INSERT but before head update | Business mutation, event, and head all roll back; next successful event links to prior committed head |
| CH5 | Tampered payload, tampered prev hash, deleted middle event, duplicate successor, and fork fixtures on isolated test DB | Verifier detects every corruption class |
| CH6 | Canonicalization vectors across SQLite and PostgreSQL | Same logical event yields identical canonical bytes and digest on both engines |
| CH7 | Existing audit rollback tests and representative business call paths | Existing atomicity behavior remains intact; all audited call paths begin at the required outer transaction boundary |
| CH8 | Append-only trigger integration | Event INSERT succeeds; UPDATE/DELETE fail; chain/head writes require no event-row UPDATE |

## 19. Append-only audit protection and test isolation (Rev 2 — defect E fix)

### 19.1 Binding no-bypass rule

**No production bypass and no test bypass will be created.** Specifically: no guard/flag tables that disable triggers, no session variables that silence triggers, no settings switch that conditionally skips the RunSQL trigger migration in any environment, and no fixture that mutates audit rows. Tests run against fully-protected databases.

### 19.2 Database enforcement (unchanged from Rev 1, restated)

- **PostgreSQL:** `CREATE FUNCTION security_reject_audit_mutation() RETURNS trigger ... RAISE EXCEPTION` + `BEFORE UPDATE OR DELETE ... FOR EACH ROW EXECUTE FUNCTION ...` — rejects any UPDATE/DELETE of `security_auditevent`.
- **SQLite:** `BEFORE UPDATE` / `BEFORE DELETE` triggers with `SELECT RAISE(ABORT, 'security_auditevent is append-only')`.
- One migration, two vendor-guarded `RunSQL` operations, each with `reverse_sql` dropping the trigger (rollback-safe). First raw-SQL migration in the repo — isolated, documented exception confined to the security app; `makemigrations --check` stays clean (triggers are not in model state).

### 19.3 How tests verify protection (without weakening it)

- Django test runners create **ephemeral test databases by running all migrations** — the triggers are present in every test database by construction. Cleanup = discarding the test database, never mutating rows.
- Verification tests (both engines): ORM `queryset.update(...)` → `DatabaseError`; ORM `.delete()` → `DatabaseError`; raw-cursor `UPDATE`/`DELETE` → `DatabaseError`; normal `INSERT` (including inside business transactions) succeeds; migration reverse drops and re-apply restores triggers; chain verification fails when a row is edited out-of-band **with triggers dropped by the test's own schema manipulation** (CH4 — this manipulates only the test's own ephemeral DB, never a shared/production surface).

### 19.4 Legacy tests that mutate audit rows — mandatory rewrite in W0-2E

Verified mutation sites: `accounting/test_bootstrap.py:55-58` (`AuditEvent.objects.filter(...).delete()`) and `:116-121` (`event.action = AuditAction.UPDATE; event.save(update_fields=["action"])`). Once triggers land, these tests fail. **Resolution:** W0-2E must rewrite these specific tests to achieve their intent (bootstrap freshness/idempotency) **without mutating audit rows** — e.g., query-scoped assertions, event counting, or constructing the negative condition through the bootstrap command's own inputs. If — and only if — a specific test proves impossible to refactor without mutation, the W0-2E implementer must **STOP and report to the owner** rather than introduce any bypass. This escalation rule is binding.

## 20. Document lifecycle reconciliation (Rev 2 — defect H fix)

### 20.1 Owner-approved lifecycle rules with honest status labels

| Rule (owner-approved) | Status at baseline `99579d9` |
|---|---|
| Ordinary Draft records may be created, edited, and deleted before becoming effective, with authorization and audit history | **PARTIALLY ENFORCED-TODAY**: draft create/edit services exist; only purchase-draft **line** deletion is service-level (`purchases/services.py:349`); whole-draft deletion is raw-ORM only and **unaudited** → audited `delete_disposable_draft` service = CONTRACT-ONLY (owning domain batches) |
| TEST records remain isolated and must not create real financial or operational effects | **CONTRACT-ONLY — NOT enforced today.** No `record_class` field, no post-path rejection, no test isolation mechanism exists (NOT FOUND, verified). W0-2A must not and does not claim TEST isolation is enforced |
| Pending Evidence records cannot be silently deleted; cancelled with a reason and retained | **CONTRACT-ONLY** (OD-6 batch; state does not exist — gap G-A2) |
| Approval and posting are separate actions | **CONTRACT-ONLY** (no approval engine exists; `AuditAction.APPROVE` member is dead code today) |
| Editing an approved but unposted record invalidates its approval | **CONTRACT-ONLY** (OD-6 batch) |
| Posted/effective records cannot be edited or deleted directly | **ENFORCED-TODAY** (verified: `PostedImmutabilityError` delete-override family, 31 points) |
| Corrections to posted records use the approved reversal/correction process | **ENFORCED-TODAY** (verified: `reverse_journal`, landed-cost reversal services, purchase-return/refund reversal paths) |

### 20.2 TEST enablement prerequisites (binding — all four must land in approved batches before TEST can be exposed)

1. Additive `record_class` fields (`DRAFT` default / `TEST`) on the target domain's document models (owning domain batch).
2. Post-path rejection in **every** post/finalize service of that domain: assert `record_class != "TEST"` before any effects (hard invariant).
3. Audited `delete_disposable_draft(document, user, reason)` service for the domain (same-transaction `DELETE` audit event).
4. Per-domain tests: post-rejection, audited deletion, report-invisibility of TEST records.

Enabling TEST functionality before all four prerequisites of a domain are implemented and owner-approved is **prohibited**. W0-2A implements none of them (not even the schema fields — they belong to the domain batches to avoid touching domain models twice). Until then, the UI/API must not expose any TEST-record capability.

### 20.3 Corrected UQ-9 (owner decision recorded — not re-asked)

The owner has decided (recorded verbatim): **"Ordinary Draft records may be deleted before becoming effective, with proper authorization and audit history. Pending Evidence records must be cancelled with a reason and retained. Posted/effective records are immutable and reversal-only."** Revision 1's framing of ordinary-draft deletion as an open owner question is corrected. Remaining work is implementation mapping only (which domain batches build the audited delete services), not policy.

## 21. UQ register — Rev 2 re-classification

Classification vocabulary: **ALREADY-DECIDED** (owner decided; closed) · **TECHNICALLY-RESOLVED** (resolved by this revision; owner may veto without blocking) · **OWNER-DECISION** (requires an explicit owner decision) · **DEFERRED** (belongs to a later approved phase; no decision needed now).

| # | Question (Rev 1) | Rev 2 classification | Status / consequence / recommendation |
|---|---|---|---|
| UQ-1 | May a GM role assignment ever be revoked via ERP APIs (incl. self)? | **OWNER-DECISION** (before W0-2C) | Affects C, not A. Recommendation unchanged: GM assignments managed only by bootstrap/recovery utility through W0-2A..D; API revocation deferred. Consequence of no decision: C cannot ship role-revocation APIs for GM assignments |
| UQ-2 | Temporary access representation | **TECHNICALLY-RESOLVED** | Bounded dated rows on M4/M5/M6; temporal semantics fully specified (§14). Owner may veto without blocking W0-2A (a separate model would change 0002 before implementation) |
| UQ-3 | Reject override-writes targeting active-GM users at write time? | **TECHNICALLY-RESOLVED** | Yes — reject at write time (defense in depth; resolver already ignores such overrides). Clear semantics beat allow-but-ignored |
| UQ-4 | Add `cryptography` dependency (AES-GCM/Ed25519)? | **OWNER-DECISION** (before W0-2C) | Only new dependency in the plan; needed by C/E, not A. Consequence of refusal: stdlib-only fallback is materially weaker (no authenticated encryption, no Ed25519) and requires redesign of §7.3 custody |
| UQ-5 | Key custody facility on the target OS | **DEFERRED** (W0-2C) | Validate on the actual machine before selection; fallback = file-based key with ACL + offline copy |
| UQ-6 | Backup frequency/retention/encryption; checkpoint cadence | **DEFERRED** (W0-2E) | D12 keeps these open; recommendation: daily checkpoint + per-shift for high activity; owner sets retention |
| UQ-7 | Auditor-visible categories and masking (D11) | **DEFERRED** (W0-2E) | GM-only audit report first; auditor subset later with a masking spec |
| UQ-8 | Exact trusted origins for local UI (D13) | **DEFERRED** (W0-2F) | Proposal: `http://localhost:5173` (dev) + packaged origin; no wildcard |
| UQ-9 | Ordinary-DRAFT deletion policy | **ALREADY-DECIDED** | Owner rule recorded verbatim (§20.3); removed from the open list; not re-asked. Implementation mapping (audited delete services) rides with domain batches |
| UQ-10 | Concurrency limit = 2: refuse 3rd login vs terminate-oldest-with-disclosure | **OWNER-DECISION** (before W0-2D) | Both readings satisfy "does not silently hide"; recommendation: refuse-with-list (user chooses). Consequence of no decision: D cannot ship the concurrency control |
| UQ-11 | Drift diagnostic UX | **TECHNICALLY-RESOLVED** | Log-only (`step_delta` in server logs); user-visible hint may be added later as cosmetics |
| UQ-12 | G-8 closure timing (`finalize_sale`/`reverse_payment` dedicated audit events) | **DEFERRED** (W0-2E) | As planned in the W0-2 report; additive and safe |

## 22. Technical issue resolution table (Revision 4 deliverable)

| Issue | Defect in Revision 1 | Resolution | Where |
|---|---|---|---|
| A | Temporal uniqueness: expired-but-unrevoked rows could permanently block re-grant; partial unique treated as sufficient | Settlement operation + `revocation_kind` + one-live-row-per-slot uniqueness as race backstop + grant service algorithm + overlap policy + renewal/replacement semantics + per-engine concurrency strategy | §14.1–14.7 |
| B | Catalog had wildcard-style prefixes, "similar to" rows, and an unresolved 20-vs-23 domain count | Exact machine-readable registry: 20 domains, 162 keys, per-key meaning/sensitivity/seed/status; reconciliation of 20-vs-23; unresolved keys marked, not guessed | §15 |
| C | `AuditAction` max_length 20 < longest proposed name (26) | Complete inventory with lengths; `CharField(40)`; binding naming convention; migration note | §17 |
| D | Audit-chain digest did not include the previous hash, and SQLite locking assumed a late audit UPDATE was always the transaction's first write | Versioned canonical payload; domain-separated SHA-256 over previous-hash bytes plus payload; unique event/link constraints; link-based verifier; mandatory IMMEDIATE outermost SQLite transaction; explicit ambient-transaction prohibition; timeout and whole-operation retry rules; owner approval because the setting affects all outermost transactions | §18.2–18.6 |
| E | "Test-bypass mechanism" in the trigger migration could weaken production protections | Binding no-bypass rule; triggers in every test DB by migration; verification tests; mandatory rewrite of legacy mutating tests; STOP-and-report escalation | §19 |
| F | `user` FKs CASCADE on M4/M5/M6 could erase authorization history | PROTECT everywhere on user/attribution FKs; deactivation-not-deletion policy; invariant test | §14.8 |
| G | Resolver consulted the permission catalog before authentication checks | Corrected 10-step binding sequence (auth → account → session → catalog → GM → deny → allow → role → scope → default-deny) + corrected pseudocode + new tests R14–R18 | §16 |
| H | Lifecycle conflated enforced rules with future contracts; TEST isolation risked being read as available | Status labels (ENFORCED-TODAY vs CONTRACT-ONLY) per rule; binding TEST enablement prerequisites; W0-2A explicitly implements none | §20 |
| I | UQ-9 contradicted the owner's clarified policy | Owner rule recorded verbatim; removed from open list; not re-asked | §20.3, §21 |
| J | Future-phase behavior risked being read as implemented | §13/§24 boundary matrix; CONTRACT-ONLY labels throughout; zero-endpoint-behavior-change proof plan retained | §13.1, §24 |
| K | Optional scope allowed warehouse-bound grants to skip object scope | Server-owned scope policy; mandatory trusted resource-derived scope for all non-GM scoped grants; ALLOW cannot bypass scope | §16.1–16.4 |
| L | Django Admin GM-only statement lacked enforceable gate; staff/superuser assumptions could bypass | Custom AdminSite gate on every admin route; active GM role required; superuser alone never grants access; direct-route tests | §5.1, §16.4 |
| M | BasicAuthentication could satisfy password-only authentication despite mandatory GM MFA | W0-2C route inventory and proof that Basic-only requests cannot reach protected MFA routes; transition requires Batch 2/3 compatibility review | §6, §16.4 |
| N | Resolver exception boundary did not cover account/session and permission lookup failures | One fail-closed boundary over all security lookups; tests for DB/cache/scope errors | §16.1–16.4 |
| O | SQLite grant service treated first UPDATE as safe despite ambient DEFERRED transaction risk | Uniform outermost IMMEDIATE requirement for SQLite grant/audit operations; ambient DEFERRED prohibited; whole-operation retry; owner consent required | §14.6, §18.4–18.6, §23 |
| P | Grant-service race text implied retry after same-slot unique conflict would necessarily succeed | Distinguish transient lock/busy retry from domain-level same-slot conflict; never automatically retry an active/scheduled conflicting grant | §14.6 |
| Q | Registry claimed scope mapping delivered (§4.2/§15.2) while §15.1 still required "enumerate all 162 keys before code"; no `scope_policy` existed per key (Defects A/B) | Evidence-backed scope registry: 162 rows × 9 fields, every classification grounded or explicitly UNRESOLVED; §15.1 contradiction resolved | §15.1, §15A |
| R | Seed totals arithmetically inconsistent with the matrix: GM 150 vs E+S+M=149; ACC 101 vs 102 'A' cells; "seeded to no one 12" omitted `sales.document.approve` | Row-level recount; corrected totals (E=11/S=53/M=88/R=10; GM 152 / ACC 102 / WK 12 / unseeded 10) with binding reconciliation notes | §15.4 |
| S | `sales.refund.*` marked UNRESOLVED "no verified service" — false: `Refund` model + `create_refund`/`reverse_refund` existed on main; Revision 2's grep was scoped to `sales/services.py` only | Keys grounded `[R5]` (M/S/S); GM seed updated to 152; Accountant seed = owner decision; §13.3 evidence row annotated | §13.3, §15.3, §15.5, §23.8 |
| T | 17 keys carried status S without an existing service-layer chokepoint (4× `payments.payment.*` — no supplier-payment code exists anywhere; 6× master-data view rows with resolver-only apps; `sales.document.view/edit_draft/reverse`; `purchases.document.view`; `purchases.supplierrefund.view`; `inventory.adjustment.reverse`) | Corrected to M with `[R5]` markers; per-key evidence in §15A | §15.3, §15A |
| U | Stale evidence: §24.1 heading said "Revision 3" under the Revision 4 section; §24.3 "Post-Revision-4" numbers (9 ahead / 1,234 lines / blob add6ba62) were mid-revision, not final (final Revision 4 state: 10 ahead / 1,237 lines / blob bf36e6c3) | Heading corrected; §24.3 replaced with verifiable pre-commit facts; final post-commit evidence delegated to the owner handoff report (not copied from old counts) | §24 |
| V | Warehouse Keeper vocabularies conflated: "12 seeded" vs 14 keys bearing `(W)`/assignment semantics appeared contradictory | Reconciled: 12 WK seeds = 8 `(W)`-scoped + 2 field-restricted + 2 self-scope; 14 `(W)`-bearing keys = 10 WAREHOUSE_REQUIRED (ACC-column markers) + 4 role-conditional (WK-column-only markers) | §15.4, §15A, §23.9 |

## 23. Remaining owner decisions (explicit list)

1. **Approve this Revision 5 design** — including the catalog registry (§15: 20 domains / 162 keys; scope registry §15A: NONE=140 / WAREHOUSE_REQUIRED=10 / OBJECT_REQUIRED=2 / UNRESOLVED=10; seeds GM 152 / ACC 102 / WK 12) and the C† defaults (which keys stay unseeded pending explicit GM grants). **This is the only decision required before W0-2A implementation.**
2. **UQ-4** — approve adding the `cryptography` dependency (needed by W0-2C/E; not by A).
3. **UQ-1** — GM-assignment revocation policy (needed before W0-2C).
4. **UQ-10** — third-session behavior (needed before W0-2D).
5. **W0-2E SQLite transaction policy consent** — approve or decline the required SQLite OPTIONS transaction_mode="IMMEDIATE" setting for audit-producing and grant-writing workflows. This is not a cosmetic recommendation: without an IMMEDIATE outermost transaction before business reads, the proposed SQLite chain-writer guarantee is not established. The setting affects all outermost atomic transactions on that SQLite connection. If declined, W0-2E must return with an alternative proven boundary design; it must not ship a DEFERRED/late-UPDATE approximation.
6. **UQ-6 / UQ-7** — backup cadence/retention and auditor masking parameters (before W0-2E).
7. **UQ-8** — trusted origins list (before W0-2F).
8. **`sales.refund.*` seed assignment (raised by Revision 5 evidence).** The customer-refund services exist on main (`create_refund`/`reverse_refund`, `sales/returns_services.py:500-667`), so the three keys are now registry-grounded and seeded to GM. Decision: does the Accountant role receive `sales.refund.view/create/reverse` (matrix rows 5/10 "record/manage routine receipts and payments" / "controlled correction")? **Why needed:** refunds issue money back to customers; the W0-2B/2C seed migration must know. **Evidence:** services verified; approved matrix has no explicit refund row. **Safe default while unresolved:** GM-only (current registry; Accountant cells "—"). **Blocked:** W0-2B sales API wiring, W0-2C seed migration.
9. **Role-conditional warehouse filtering — modeling confirmation (raised by Revision 5).** Four keys (`warehouses.warehouse.view`, `purchases.document.view`, `sales.document.view`, `reporting.dashboard.view`) carry `(W)`/assignment semantics only in the Warehouse Keeper matrix cell. Registry modeling: key scope = `NONE`; WK holders receive assignment-based data filtering per approved matrix rows 1/4/5/7, enforced server-side by the owning API batch against M6. The alternative — classifying the keys `WAREHOUSE_REQUIRED` for all holders — would warehouse-restrict Accountant views, which the approved matrix does not state. **Why needed:** the resolver implements one policy per key; the owner should confirm the modeling. **Evidence:** approved matrix rows; `Purchase.warehouse` FK (purchases/models.py:75); `SaleLineWarehouseAllocation` (sales/models.py:303); M6 model set. **Safe default:** current modeling (fail-closed in the resolver either way). **Blocked:** W0-2B endpoint scoping design.

Technically-resolved items (UQ-2, UQ-3, UQ-11) need no decision; the owner may veto them without blocking.

## 24. Revision 5 verification evidence and W0-2A implementation boundary

### 24.1 Files changed by Revisions 3–5

Revisions 3, 4, and 5 each change exactly one repository file: `docs/architecture/W0-2A_RBAC_OFFLINE_SECURITY_DESIGN_DRAFT.md`. The GitHub update is a documentation-only commit on the existing branch `security/w0-2a-rbac-architecture`. No code, model, migration, API, frontend, test, settings, workflow, or other repository file is changed. No PR is created, no merge is performed, and no deployment occurs. The resulting commit SHA and final compare evidence are recorded in the accompanying owner handoff.

### 24.2 W0-2A boundary matrix (defect J)

| Component | Disposition in W0-2A |
|---|---|
| Architecture design (this document) | DELIVERED (design only; owner review pending) |
| Six RBAC models + constraints/indexes | SCHEMA-ONLY (additive migrations 0002; dormant) |
| Permission catalog registry + seed | SCHEMA+SEED (0003; 162 keys / 20 domains) |
| Superuser→GM mapping | MIGRATION (0004; idempotent; no-op on current DBs) |
| Resolver service + trace | CODE, DORMANT — zero view wiring, zero settings change, zero importers among views (structural test asserts) |
| Temporal grant services (settlement/renewal/replacement) | CONTRACT-ONLY (§14 — implemented with W0-2B admin services; W0-2A ships schema + resolver only) |
| Endpoint enforcement (HasERPPermission, denial-audit hook) | FUTURE — W0-2B (feature-flagged) |
| Login/MFA/bootstrap/admin APIs | FUTURE — W0-2C |
| Sessions/lockout/concurrency controls | FUTURE — W0-2D |
| Audit chain fields, AuditChainHead, triggers, CharField(40), new AuditAction wiring, checkpoints | FUTURE — W0-2E; must implement §18 exactly and wait for the SQLite transaction-policy owner decision |
| Frontend auth/guards/UX | FUTURE — W0-2F |
| Full regression + PostgreSQL exact-head evidence | FUTURE — W0-2G |
| TEST record capabilities | FUTURE — domain batches, gated by §20.2 prerequisites |
| Pending Evidence / Approval workflow | FUTURE — OD-6 batch |

**Zero-endpoint-behavior-change proof plan (retained from the implementation blueprint):** no view/permission/settings/middleware/URL changes (grep-diff scoped proof); resolver unwired; full existing suite (1022 passed / 9 skipped baseline on the identical code tree) green unmodified on SQLite and PostgreSQL; Security Batch 2 and Batch 3 pins untouched; makemigrations --check clean; migration forward+reverse on both engines. These are required future implementation checks, not claims that Revision 3 ran them.

### 24.3 Evidence availability statement (Revision 5)

**Pre-commit live verification (performed before this revision's commit):** main at `99579d99f4b7c668118ad7e2add2a2ef91d04fba`; branch tip `33fd1a1f90fc49ccdbaf081b8a2ef9fbd45d4e27` (10 ahead / 0 behind vs main); document blob `bf36e6c34ed1481ec5224c67de48f4d78441cb21` (1,237 lines); no W0-2A PR exists; the exact commit `33fd1a1` had zero check-runs and zero statuses → **CI NOT VERIFIABLE, not GREEN**. The working environment had been reset between sessions; the repository was re-cloned and these values re-verified live against GitHub before work began (§13.4).

**Post-commit evidence discipline (Defect D fix):** Revision 2–4 recorded "post-revision" evidence that was actually captured mid-revision (§22 row U). Revision 5 does not copy pre-commit counts forward: the final Revision 5 commit SHA, document blob SHA, compare ahead/behind counts, diff statistics, PR status, and CI status are computed from live GitHub **after** the final documentation commit and are recorded in the accompanying owner handoff report. Any future revision must follow the same rule.

### 24.4 STOP

Revision 5 is a documentation-only correction: a complete evidence-backed scope registry (§15A), matrix reconciliation, seed recount, and stale-evidence repairs. No models, migrations, services, permissions, endpoints, settings, or tests have been implemented. The branch must remain unmerged. The revised design is presented for owner review; implementation begins only after explicit owner approval (§23).

**STOP — REVISION 5 DOCUMENTATION UPDATE COMPLETE. AWAITING OWNER REVIEW.**