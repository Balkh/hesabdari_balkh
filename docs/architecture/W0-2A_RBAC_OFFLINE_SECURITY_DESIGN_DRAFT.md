# W0-2A — RBAC Architecture & Offline Security Design Contract

**Repository:** `Balkh/hesabdari_balkh`  
**Baseline:** `main` at `99579d99f4b7c668118ad7e2add2a2ef91d04fba`  
**Working branch:** `security/w0-2a-rbac-architecture`  
**Status:** DESIGN DRAFT — NOT IMPLEMENTATION APPROVAL  
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

Role names are approved; the complete action-by-action permission matrix is not approved by this document. No role receives implicit broad access merely because it exists.

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

The exact resolver ordering and edge cases remain an explicit design sign-off item before implementation. In particular, the implementation must specify how an explicit user deny interacts with a role grant, how multiple roles combine, and how expired/revoked assignments are excluded. Do not silently settle these semantics in code.

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
- Exact numeric lockout thresholds, idle timeout, TOTP clock-drift allowance, and session policy are not set in this document and must be decided before implementation.

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

**Current status:** design draft only. No schema, migration, API, frontend, authentication behavior, or audit behavior has been changed by this document.
