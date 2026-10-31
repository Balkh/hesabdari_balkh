# W0-2A — RBAC Architecture & Offline Security Design Contract

**Repository:** `Balkh/hesabdari_balkh`  
**Baseline:** `main` at `99579d99f4b7c668118ad7e2add2a2ef91d04fba`  
**Working branch:** `security/w0-2a-rbac-architecture`  
**Status:** FIVE DESIGN ITEMS OWNER-APPROVED; ACCOUNTANT ROLE EXPANSION OWNER-APPROVED; TECHNICAL MODEL MAPPING AND IMPLEMENTATION PLAN REMAIN OPEN  
**Date:** 2026-10-31

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

These are baseline observations, not claims about any later commit.

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

### 4.2 Initial roles

The initial role catalog is limited to:

- **GM** — General Manager.
- **Accountant** — accounting/finance duties, subject to an explicit permission matrix.
- **Warehouse Keeper** — warehouse/inventory duties, subject to an explicit permission matrix.

Role names are approved. The initial Accountant permission matrix is owner-approved as a broad operational role, as amended in the owner decision record below. Exact permission keys, object scopes, and per-user configuration must still be mapped during implementation planning. Warehouse Keeper remains limited to warehouse duties unless the GM explicitly grants additional per-user permissions.

Django Admin is GM-only (owner decision D5). Employee workflows must be provided through controlled ERP interfaces, not Django Admin.

### 4.3 Proposed additive authorization entities

Subject to implementation review, prefer additive models referencing Django User:

- **Role** — stable role identity and active state.
- **Permission** — stable machine key for a specific resource/action.
- **RolePermission** — permission granted to a role.
- **UserRoleAssignment** — user-to-role assignment with effective dates and actor/audit metadata.
- **UserPermissionOverride** — explicit per-user allow/deny, optional start/end time, reason, granting actor, and revocation metadata.
- **TemporaryAccess** — if not represented directly by dated overrides, a separately auditable bounded grant with automatic expiry.

Avoid duplicate permission engines or using Django Groups as a second competing source of truth. A final model mapping must be chosen before migration creation. Historical actor/role/permission context must be preserved for past audit events.

### 4.4 Authorization evaluation

Default decision is **deny** unless a valid permission is positively established. The owner selected deny precedence for conflicts (D3), and GM authority is protected from ordinary employee overrides.

The owner-approved resolver ordering and edge cases are specified in Section 9A, Item 2. Implementation must encode those semantics exactly and test explicit user deny vs role grant, explicit user allow, multiple-role union, protected GM authority, expiry/revocation, and hard domain invariants.

Authorization must be enforced on the backend for every protected operation. Frontend hiding/disabled controls are usability only and never security boundaries. Object-level checks are required wherever access depends on ownership, assigned warehouse, document state, or another business boundary.

Permission checks must not bypass accounting/business-service validation. Existing API 403 behavior for denied protected requests is preserved (D6); do not change frozen Batch 2/3 authentication behavior.

## 5. GM authority and employee administration

GM has full ERP administrative authority within hard domain invariants. GM may create and approve the GM's own operations; a second approver is not required. No ordinary per-user deny/override may remove protected GM authority.

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

- Initial proposal: generate 10 single-use recovery codes; display/print once; store only secure hashes in the database.
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
- Audit records must be append-only and protected at the database level (D7). Exact database enforcement mechanism must be selected and tested for SQLite development and PostgreSQL deployment.
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

- Backup frequency, retention, encryption, restore verification, and separate key custody.
- Exact trusted local origins and browser/Tauri origin strategy.
- CSP directives for the eventual deployment/package.
- Auditor-visible data categories and masking rules.
- Exact audit database protection mechanism and cross-database test strategy.
- Numeric lockout/idle/session values and clock-drift policy.
- Final permission taxonomy and role matrix.
- Final resolver precedence details and multi-role conflict semantics.

## 9A. Owner-approved concrete security decisions — five items

The five items below were explicitly approved by the owner in the conversation on 2026-10-31. The Accountant permission matrix was subsequently amended and approved by the owner on 2026-10-31 as recorded in Section 9C. These decisions are approved policy boundaries; implementation details explicitly marked open still require technical validation and must not be invented in code.

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

### Item 2 — Resolver precedence and multiple roles (proposal)

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

This proposal resolves the D3 deny-precedence requirement while preserving explicit per-user grants. Owner confirmation is required.

### Item 3 — GM first-run bootstrap and recovery key custody (proposal)

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

### Item 4 — Numeric security and session defaults (proposal)

Recommended initial single-computer defaults:

| Control | Proposed value | Behavior |
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

### Item 5 — Database append-only audit mechanism (proposal)

Use a layered, cross-database design:

1. **Application contract:** all audit writes go through one audited append service; normal application code has no update/delete path for audit rows.
2. **Database enforcement:** install SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers, and PostgreSQL equivalent triggers, that reject mutation/deletion of audit rows. Migration tests must prove both operations fail.
3. **Tamper evidence:** each event stores a canonicalized payload hash and previous-event hash, forming a per-database append chain. Verify the chain on startup/health diagnostics and in a dedicated audit-integrity command.
4. **Independent offline evidence:** periodically export a signed audit checkpoint to a separately stored offline backup location; a database administrator with full machine access may still bypass local controls, so do not describe triggers alone as absolute tamper-proofing.
5. **Failure policy:** security-critical actions must fail closed if their required audit write cannot be committed atomically. Do not allow a successful role grant, MFA reset, recovery, or sensitive administrative change without its audit event.
6. **Compatibility:** prove behavior on SQLite (development) and PostgreSQL (deployment); ensure normal migrations and backup/restore preserve triggers and chain continuity.

The threat model must explicitly state that an attacker with unrestricted operating-system and database-owner access can potentially replace local files or database objects. Hash chaining and offline signed checkpoints provide detection/resilience, not magical prevention against a fully privileged machine attacker.

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

1. Finalize resolver semantics, permission taxonomy, role matrix, bootstrap/recovery details, and numeric session/security parameters.
2. Implement additive RBAC models and migration without changing existing endpoint authorization behavior.
3. Add deterministic unit tests for permission resolution, expiry, deny precedence, GM protected authority, and multi-role cases.
4. Verify migrations and existing security/accounting regressions on SQLite and PostgreSQL.
5. Present schema/API impact and evidence for owner review.

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

Before W0-2A code implementation, owner must approve:

1. Permission taxonomy and exact initial role matrix.
2. Resolver precedence, including role aggregation and user override conflicts.
3. Model mapping and migration approach.
4. First-run GM bootstrap mechanism.
5. Recovery key custody and encryption-key backup strategy.
6. Numeric lockout, idle timeout, session, and TOTP clock-drift parameters.
7. Audit database append-only mechanism and supported database behavior.

**Current status:** five design items and the Accountant operational-role amendment are owner-approved. This document update records policy decisions only; it does not claim that any schema, migration, API, frontend, authentication behavior, or audit behavior has been implemented or verified.
