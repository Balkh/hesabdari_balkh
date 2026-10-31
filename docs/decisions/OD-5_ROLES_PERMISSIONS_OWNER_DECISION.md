# OD-5 — Roles, Permissions, and User Security Owner Decision

**Decision ID:** OD-5  
**Record date:** 2026-10-31  
**Authority:** Explicit owner-approved security decisions recorded in the Hesabdari Balkh project conversation  
**Status:** OWNER-APPROVED DECISION — DOCUMENTED BY W0-1  
**Scope:** Individual accounts, GM administration, role-based access, per-user access, sessions, authentication protection, and security audit

## 1. Identity and account ownership

- Every employee must have an individual account. Shared employee accounts are prohibited.
- The General Manager (GM) has full administrative access to ERP operations and manages employee accounts, roles, permissions, activity, and access.
- The GM may create and approve the GM's own operations; a second approver is not required for the GM.
- Employees receive only the access explicitly required for their assigned duties.
- When an employee leaves or changes role, the prior access must be revoked and an operational handover prompted/recorded.
- Account creation, activation/deactivation, role changes, permission changes, recovery, and access revocation must be logged.

## 2. Roles and permission model

- Access is based on roles and explicit permissions, with per-user overrides where authorized.
- Permissions must distinguish relevant actions, not merely broad module visibility. Examples include view, create, edit draft, submit, review, approve, post/finalize, cancel, reverse, release/issue, print, download, reconcile, and administer, where applicable to a domain.
- Financially sensitive information and operations must be restricted to authorized users.
- GM access does not bypass immutable posted-document rules or other hard accounting/domain invariants. In particular, a POSTED document is not directly editable even by the GM; correction follows the approved reversal/correction contract.
- Permission changes take effect immediately. Where necessary to enforce revocation, affected sessions must be terminated.
- A role change must revoke the old role's permissions while preserving historical actor/role information for past actions.
- Temporary access must have a start and end time, expire automatically, and be revocable or extendable by the GM.
- The exact conflict precedence between role grants and per-user overrides, and the initial employee role catalog, must be specified in the implementation permission matrix without weakening any explicit denial or domain invariant; do not silently invent an owner policy.

## 3. GM administration and recovery

The GM must be able to:

- create, activate, deactivate, and manage employee accounts;
- assign, change, and revoke roles;
- grant, review, extend, and revoke temporary access;
- review user activity and security events;
- review failed logins and unlock an account;
- inspect active sessions/devices and terminate sessions;
- manage access and initiate employee departure/role-change handover.

GM account recovery must be secure and must not provide a privilege-escalation path. Recovery actions must be logged and protected against unauthorized use.

## 4. Authentication and session security

- Failed login attempts must be logged.
- Account lockout must be configurable; the GM can review and unlock accounts.
- Idle-session timeout and a pre-expiry warning must be configurable.
- Multiple sessions may be allowed, but sessions/devices must be visible and logged, and the GM must be able to terminate them.
- MFA is mandatory for the GM.
- MFA is configurable for employees.
- Strong password controls apply; GM password resets must force the required password change.
- Session termination and access revocation must take effect promptly.
- Exact lockout thresholds, timeout values, MFA methods, and recovery factors are implementation parameters to be selected and verified; this record does not prescribe unapproved numeric settings or a particular MFA vendor.

## 5. Audit, monitoring, and reporting

The system must provide auditable activity information covering, at minimum:

- successful and failed logins and logouts;
- account creation, activation, deactivation, and recovery;
- role and permission grants, changes, expiry, and revocation;
- session/device creation and termination;
- document access and workflow actions;
- sensitive financial and operational actions;
- approvals, posting/finalization, cancellation, and reversal;
- suspicious security events and alerts to the GM.

Audit history must not be deletable or tamperable through ordinary application permissions. Security-relevant actions must preserve actor identity and the role/permission context applicable at the time. Backups must include roles, permissions, and security/audit history.

## 6. Alerts and operational controls

- Suspicious events must alert the GM.
- Departure and role-change procedures must revoke access and prompt handover.
- Permission and security reports must be available to the GM.
- User/device/session visibility must support prompt investigation and termination.

## 7. Relationship to prior security batches

This is a separate owner-approved RBAC/user-security decision. It does not reopen, expand, or modify the frozen Security Batch 2 or Security Batch 3 contracts. Deployment-dependent admin protection, shared-cache/rate-limit decisions, and other explicitly deferred items remain governed by their existing records and separate owner approval.

## 8. Implementation boundary

This decision is not evidence that RBAC, account administration, MFA, session management, audit immutability, alerts, or user-facing security screens are implemented. Before implementation, inspect the current Django User/authentication setup, existing Security app, AuditEvent, API routes, tests, and frontend. Reuse existing foundations and implement incrementally; do not replace the user model or security architecture without demonstrated necessity and separate approval.
