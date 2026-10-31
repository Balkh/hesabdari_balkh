# W0-2A — RBAC Architecture & Offline Security Design Contract

**Repository:** `Balkh/hesabdari_balkh`  
**Baseline:** `main` at `99579d99f4b7c668118ad7e2add2a2ef91d04fba`  
**Working branch:** `security/w0-2a-rbac-architecture`  
**Status:** FIVE DESIGN ITEMS OWNER-APPROVED; ACCOUNTANT ROLE EXPANSION OWNER-APPROVED; TECHNICAL MODEL MAPPING AND IMPLEMENTATION PLAN REMAIN OPEN; OWNER REVIEW PENDING  
**Date:** 2026-10-31  
**Revision 2:** 2026-10-31 — technical design correction, pushed to the working branch for owner review.  
**Revision 3:** 2026-10-31 — targeted documentation-only corrections to the audit hash-chain and SQLite transaction contract, plus refreshed repository evidence. No application code, model, migration, API, frontend, test, or runtime behavior changes. No PR, merge, deployment, or implementation authorization.

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

Django Admin is GM-only (owner decision D5). Employee workflows must be provided through controlled ERP interfaces, not Django Admin.

**[Rev 2]** The exact permission-key catalog is now defined: §15 (162 keys across 20 domains; seeds GM = 150, Accountant = 101, Warehouse Keeper = 12).

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

Revision 3 is a documentation-only correction to the already-pushed Revision 2 design. It corrects (D) the audit hash-chain construction, (E) SQLite transaction-start/locking guarantees, and (F) repository evidence that became stale after Revision 2 was pushed. **No application code, Django models, migrations, API/frontend changes, tests, permission enforcement, authentication/session implementation, or runtime behavior were changed.** This revision updates only this design document on the existing W0-2A branch. It does not create a PR, merge, deploy, or authorize implementation. W0-2A implementation remains blocked on explicit owner approval.

### 13.2 Mandatory repository inspection and revision evidence

The following is the independently observed GitHub state immediately before the Revision 3 document update:

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

After the Revision 3 update, the resulting commit SHA, file blob SHA, compare counts, PR search, and exact-commit CI/status lookup must be recorded in the owner handoff. No CI success is inferred from an empty or unavailable status response.

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
| No sales refund service | grep `refund` in `sales/services.py` = 0 hits | VERIFIED (NOT FOUND) |

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
2. **Settlement UPDATE for the slot runs FIRST** (§14.3). On SQLite this first write statement upgrades the deferred transaction to a write transaction immediately, taking the database write lock before any slot-state read; on PostgreSQL it takes row locks on the rows it closes.
3. Validate window: `end_at > start_at`; bounded grants require `end_at` and `reason`.
4. Overlap check: `SELECT ... WHERE <slot> AND revoked_at IS NULL` → if found, raise domain error `GrantConflictError`.
5. INSERT the new row.
6. COMMIT. If a concurrent writer raced past steps 4–5, the partial unique index rejects the second INSERT with `IntegrityError`, which the service translates to `GrantConflictError` (caller may retry; retry re-runs settlement and succeeds).

**Engine behavior:**

- **SQLite (development):** single-writer per database. Step 2 executes a write before any read of slot state, so two concurrent grant operations serialize deterministically (the second blocks on the write lock, then proceeds and either finds the settled/closed row or fails the unique index). Django's SQLite default `busy_timeout` applies; W0-2B must set an explicit generous timeout and map lock errors to retriable `GrantConflictError`. Django ≥5.2 supports `"OPTIONS": {"transaction_mode": "IMMEDIATE"}` which takes the write lock at `BEGIN` — this is the **recommended belt-and-braces hardening**, proposed as an owner-visible settings change in W0-2E (not W0-2A; W0-2A changes no settings).
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
| `purchases.document.view` | View purchase documents | – | A | A (receiving data, W) | S |
| `purchases.document.create` | Create purchase draft | – | A | ✕ | S |
| `purchases.document.edit_draft` | Edit DRAFT purchase | – | A | ✕ | S (`purchases/services.py:300-365`) |
| `purchases.document.delete_draft` | Delete ordinary DRAFT purchase (audited; corrected UQ-9) | – | A | ✕ | M — line-level deletion exists (`purchases/services.py:349`); whole-draft audited delete service = owning batch |
| `purchases.document.post` | Post purchase | – | A | ✕ | S |
| `purchases.document.cancel` | Cancel unposted purchase with reason | – | A | ✕ | M (no cancel service yet) |
| `purchases.document.reverse` | Reverse via approved return/refund paths | – | A | ✕ | S |
| `purchases.document.export` | Export purchases | – | A | ✕ | M |
| `purchases.supplierrefund.view` | View supplier refunds | – | A | ✕ | S |
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
| `sales.document.view` | View sales documents | – | A | A (fulfillment data, W) | S |
| `sales.document.create` | Create sale draft | – | A | ✕ | S |
| `sales.document.edit_draft` | Edit DRAFT sale | – | A | ✕ | S |
| `sales.document.delete_draft` | Delete ordinary DRAFT sale (audited; corrected UQ-9) | – | A | ✕ | M (ORM-only today) |
| `sales.document.submit` | Submit sale in workflow | – | A | ✕ | M (no submit step in code) |
| `sales.document.approve` | Approve sale (OD-6) | – | C† | ✕ | R (OD-6 batch) |
| `sales.document.post` | Finalize sale (`finalize_sale`) | – | A | ✕ | S |
| `sales.document.cancel` | Cancel unposted sale with reason | – | A | ✕ | M (no cancel service) |
| `sales.document.reverse` | Reverse via approved cancel/return paths | – | A | ✕ | S (`sales/services.py:680-691`) |
| `sales.document.export` | Export sales | – | A | ✕ | M |
| `sales.return.view` | View sales returns | – | A | ✕ | S |
| `sales.return.create` | Create sales return | – | A | ✕ | S |
| `sales.return.reverse` | Reverse sales return | – | A | ✕ | S |
| `sales.return.export` | Export sales returns | – | A | ✕ | M |
| `sales.refund.view` | Customer refund views | – | — | ✕ | **U** (no verified service — do not seed, do not enforce) |
| `sales.refund.create` | Customer refund creation | – | — | ✕ | **U** |
| `sales.refund.reverse` | Customer refund reversal | – | — | ✕ | **U** |

**Domain `payments` — 10 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `payments.receipt.view` | View customer receipts | – | A | ✕ | S |
| `payments.receipt.create` | Create customer receipt | – | A | ✕ | S |
| `payments.receipt.post` | Finalize receipt | – | A | ✕ | S |
| `payments.receipt.reverse` | Reverse receipt (`reverse_payment`) | – | A | ✕ | S |
| `payments.receipt.export` | Export receipts | – | A | ✕ | M |
| `payments.payment.view` | View supplier payments | – | A | ✕ | S |
| `payments.payment.create` | Create supplier payment | – | A | ✕ | S |
| `payments.payment.post` | Finalize payment | – | A | ✕ | S |
| `payments.payment.reverse` | Reverse payment | – | A | ✕ | S |
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
| `cash.cashaccount.view` | View cash accounts | – | A | ✕ | S |
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
| `exchange.house.view` | View exchange houses | – | A | ✕ | S (`exchange_houses/services.py:51,68`) |
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
| `parties.party.view` | View parties (Keeper: minimum fields only) | – | A | A (min fields) | S |
| `parties.party.create` | Create party | – | A | ✕ | S |
| `parties.party.edit` | Edit party | – | A | ✕ | S |
| `parties.party.deactivate` | Deactivate party | – | A | ✕ | S |
| `parties.party.export` | Export party data | – | A | ✕ | M |

**Domain `products` — 5 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `products.product.view` | View products (Keeper: name/code/UOM only — no cost/price) | – | A | A (min fields) | S |
| `products.product.create` | Create product | – | A | ✕ | S |
| `products.product.edit` | Edit product | – | A | ✕ | S |
| `products.product.deactivate` | Deactivate product | – | A | ✕ | S |
| `products.product.export` | Export products | – | A | ✕ | M |

**Domain `catalog` — 10 keys**

| Key | Meaning | Sens | ACC | WK | Status |
|---|---|---|---|---|---|
| `catalog.category.view` | View categories | – | A | ✕ | S |
| `catalog.category.create` | Create category | – | A | ✕ | S |
| `catalog.category.edit` | Edit category | – | A | ✕ | S |
| `catalog.category.deactivate` | Deactivate category | – | A | ✕ | S |
| `catalog.category.export` | Export categories | – | A | ✕ | M |
| `catalog.uom.view` | View UOMs | – | A | ✕ | S |
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
| `inventory.adjustment.reverse` | Reverse adjustment (INV-guarded) | – | A | ✕ | S |
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

### 15.4 Catalog totals (exact)

| Measure | Count |
|---|---|
| Distinct domains | **20** |
| Total registered keys | **162** |
| Sensitive keys (`is_sensitive=True`) | **29** (security 18, audit 2, fiscal 4, landedcost.reverse 1, treasury execute+reverse 2, journal post+reverse 2) |
| GM seed (= GM capability set) | **150** (all ENDPOINT/SERVICE/MATRIX keys) |
| Accountant seed | **101** |
| Warehouse Keeper seed | **12** (all warehouse-scope W except `security.account.view_own`, `security.mfa.enroll_own`) |
| Seeded to no one | **12** (`documents.*` 9 RESERVED + `sales.refund.*` 3 UNRESOLVED) |
| ENDPOINT-backed keys (enforceable immediately at W0-2B wiring) | 11 |
| UNRESOLVED keys (not guessed) | 3 (`sales.refund.*`) |

### 15.5 Unresolved keys — explicit handling

`sales.refund.view/create/reverse`: no refund service was found in the sales domain (grep verified). They are registered only so the taxonomy is complete, carry no seed, and are enforced nowhere. The owning sales-API batch must either ground them in an approved service design or remove them from the registry. **No business permission has been invented without grounding.**

## 16. Authorization resolver — corrected technical encoding (Rev 2 — defect G fix)

### 16.1 Binding evaluation sequence

The resolver (`backend/security/authorization.py`, W0-2A; dormant — zero view wiring in W0-2A) MUST evaluate in exactly this order. **No permission-grant lookup (catalog, overrides, roles) may occur before steps 1–3 have passed.** This satisfies Item 2 rule 1 precisely and prevents catalog-existence probing by unauthenticated callers.

1. **Authentication** — `user` is None or `not user.is_authenticated` → DENY `UNAUTHENTICATED`. Nothing is persisted (frozen Batch 3 pin preserved).
2. **Account state** — `not user.is_active` → DENY `INACTIVE_ACCOUNT`; account locked (`locked_until > now`, W0-2D; a no-op check until D ships) → DENY `ACCOUNT_LOCKED`.
3. **Session validity** — enforced by the caller (DRF session machinery / W0-2D session records); invalid/expired → DENY `NO_ACTIVE_SESSION`.
4. **Permission-key resolution (first catalog touch)** — unknown key or `is_active=False` → DENY `UNKNOWN_PERMISSION` + server-side warning log. Any resolver exception from here on → DENY `FAIL_CLOSED` + log (fail-closed wrapper around the whole body).
5. **Protected GM authority** — active GM role assignment AND key ∈ GM capability set (§15.3 GM seed rule) → ALLOW `GM_PROTECTED`. Overrides are never consulted for GM. Domain invariants still apply downstream (they live below the resolver). A locked/inactive GM is denied at steps 2–3 — this is the owner-approved D9 lockout applying universally, not an authority change.
6. **Explicit deny** — active user override with `effect=DENY` → DENY `USER_DENY`.
7. **Explicit allow** — active user override with `effect=ALLOW` → evaluate scope (step 8); pass → ALLOW `USER_ALLOW`.
8. **Warehouse/resource scope** — evaluated inside steps 7 and 9 wherever the operation declares a scope: unresolvable/failing scope → DENY `SCOPE_DENIED` (fail-closed; never fallback-to-global).
9. **Role-derived permissions** — key ∈ union of ACTIVE role grants → scope check → ALLOW `ROLE_GRANT`.
10. **Default deny** — otherwise DENY `NO_GRANT`.

Conflict rules (binding): explicit DENY (6) precedes explicit ALLOW (7) and role union (9) — a role grant can never override an explicit denial; if both a live ALLOW and DENY existed (the schema of §14.4 makes this unreachable), DENY wins; GM protection (5) precedes overrides — ordinary overrides can never revoke GM authority (D3); unknown keys and all errors fail closed.

### 16.2 Corrected pseudocode

```python
def resolve(user, permission_key, *, at=None, scope=None) -> PermissionDecision:
    at = at or timezone.now()
    trace = []
    # 1. Authentication — strictly first; no catalog access before this passes
    if user is None or not user.is_authenticated:
        return deny("UNAUTHENTICATED", trace)          # nothing persisted (Batch 3 pin)
    # 2. Account state
    if not user.is_active:
        return deny("INACTIVE_ACCOUNT", trace)
    if account_locked(user, at):                       # W0-2D; no-op until D ships
        return deny("ACCOUNT_LOCKED", trace)
    # 3. Session validity — caller-enforced; recorded in trace
    if caller_session_invalid():
        return deny("NO_ACTIVE_SESSION", trace)
    try:
        # 4. First catalog touch happens only after 1–3
        perm = Permission.objects.get(key=permission_key, is_active=True)
    except Permission.DoesNotExist:
        return deny("UNKNOWN_PERMISSION", trace)       # + server-side warning log
    try:
        # 5. Protected GM
        if has_active_role(user, RoleCode.GM, at) and perm.key in gm_capability_set(at):
            return allow("GM_PROTECTED", trace)        # overrides never consulted
        # 6. Explicit deny
        o = active_override(user, perm, at)
        if o is not None and o.effect == Effect.DENY:
            return deny("USER_DENY", trace)
        # 7. Explicit allow (scope may still deny)
        if o is not None and o.effect == Effect.ALLOW:
            if scope is not None and not scope.allows(user, perm):
                return deny("SCOPE_DENIED", trace)     # 8. scope restriction
            return allow("USER_ALLOW", trace)
        # 9. Role-derived union
        if perm.key in union_of_active_role_permissions(user, at):
            if scope is not None and not scope.allows(user, perm):
                return deny("SCOPE_DENIED", trace)     # 8. scope restriction
            return allow("ROLE_GRANT", trace)
        # 10. Default deny
        return deny("NO_GRANT", trace)
    except Exception:
        return deny("FAIL_CLOSED", trace)              # + server-side warning log
```

### 16.3 Resolver test additions (extends R1–R13)

| # | Case | Expected |
|---|---|---|
| R14 | locked account (GM included) | DENY `ACCOUNT_LOCKED` — evaluated before GM step |
| R15 | live ALLOW+DENY pair (only reachable by manual DB tampering) | DENY `USER_DENY` (defensive deny-wins) |
| R16 | structural: query-count assertion — resolver performs **zero** Permission/override/role queries when called with `AnonymousUser` | order proof (no catalog leak) |
| R17 | expired-but-unsettled assignment (end_at past, revoked_at NULL) | resolver denies (ACTIVE predicate); settlement converts to `EXPIRED` and re-grant then succeeds |
| R18 | unknown key with authenticated user | DENY `UNKNOWN_PERMISSION` + warning log; unknown key with anonymous user → DENY `UNAUTHENTICATED` (never `UNKNOWN_PERMISSION`) |

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

- The outermost transaction for every audit-producing business operation MUST begin with SQLite transaction_mode=IMMEDIATE. This obtains the database write reservation at BEGIN, before business-service reads and before any audit-head read.
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

## 22. Technical issue resolution table (Revision 3 deliverable)

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

## 23. Remaining owner decisions (explicit list)

1. **Approve this Revision 3 design** — including the catalog registry (§15: 20 domains / 162 keys; seeds GM 150 / ACC 101 / WK 12) and the C† defaults (which keys stay unseeded pending explicit GM grants). **This is the only decision required before W0-2A implementation.**
2. **UQ-4** — approve adding the `cryptography` dependency (needed by W0-2C/E; not by A).
3. **UQ-1** — GM-assignment revocation policy (needed before W0-2C).
4. **UQ-10** — third-session behavior (needed before W0-2D).
5. **W0-2E SQLite transaction policy consent** — approve or decline the required SQLite OPTIONS transaction_mode="IMMEDIATE" setting for audit-producing workflows. This is not a cosmetic recommendation: without an IMMEDIATE outermost transaction before business reads, the proposed SQLite chain-writer guarantee is not established. The setting affects all outermost atomic transactions on that SQLite connection. If declined, W0-2E must return with an alternative proven boundary design; it must not ship a DEFERRED/late-UPDATE approximation.
6. **UQ-6 / UQ-7** — backup cadence/retention and auditor masking parameters (before W0-2E).
7. **UQ-8** — trusted origins list (before W0-2F).

Technically-resolved items (UQ-2, UQ-3, UQ-11) need no decision; the owner may veto them without blocking.

## 24. Revision 3 verification evidence and W0-2A implementation boundary

### 24.1 Files changed by Revision 3

Revision 3 changes exactly one repository file: `docs/architecture/W0-2A_RBAC_OFFLINE_SECURITY_DESIGN_DRAFT.md`. The GitHub update is a documentation-only commit on the existing branch `security/w0-2a-rbac-architecture`. No code, model, migration, API, frontend, test, settings, workflow, or other repository file is changed. No PR is created, no merge is performed, and no deployment occurs. The resulting commit SHA and final compare evidence are recorded in the accompanying owner handoff.

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

### 24.3 Evidence availability statement

Immediately before Revision 3, GitHub compare showed the branch 5 commits ahead and 0 behind main, with one documentation file added (1,152 additions, 0 deletions). The retrieved file blob was `9699bab8b143ae64ca8a3a15e39496893524ed9d`. No matching W0-2A PR was returned by PR search. The exact branch-tip commit SHA was not exposed by the available connector response. After the Revision 3 push, the owner handoff must record the exact new commit SHA, refreshed compare, file blob SHA, PR search result, and exact-commit CI/status result. Empty/unavailable checks are NOT VERIFIABLE, never GREEN.

### 24.4 STOP

Revision 3 is a documentation-only correction. No models, migrations, services, permissions, endpoints, settings, or tests have been implemented. The branch must remain unmerged. The revised design is presented for owner review; implementation begins only after explicit owner approval.

**STOP — REVISION 3 DOCUMENTATION UPDATE COMPLETE. AWAITING OWNER REVIEW.**