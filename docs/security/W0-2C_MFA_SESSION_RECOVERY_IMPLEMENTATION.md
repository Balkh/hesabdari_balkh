# W0-2C — MFA, TOTP Secret Protection, Local GM Recovery, and Session Foundation

Status: IMPLEMENTATION WORKSTREAM — NOT RELEASED
Base: security/w0-2b-r2-enforcement @ 87c56129cd7b727cfe7807b4e82b6d64e85d132d
Branch: security/w0-2c-mfa-session-recovery
Owner approvals (2026-11-06) are binding:
- TOTP secrets use AES-256-GCM; the encryption key is separate from the database.
- GM recovery and GM assignment recovery/transfer are local-only, physically controlled, offline emergency operations. No public API, LAN endpoint, internet service, or routine backdoor.
- A third concurrent login is rejected; the two existing sessions remain valid and are not evicted.
- Windows 10/11 are the primary desktop targets.

## 1. Existing-state boundary (verified before implementation)
The W0-2B/R2 branch has the singleton GM slot and operation-aware authorization. It does not yet contain a TOTP credential model, an encrypted-secret service, a durable session registry, a recovery-code lifecycle, or an emergency GM recovery utility. DRF currently lists SessionAuthentication and BasicAuthentication. The /admin route is temporarily denied to everyone. The W0-2B PR remains Draft/Open and must not be merged as part of this work.

## 2. Security invariants
1. Password-only authentication is never sufficient for the GM or any operation explicitly marked MFA-required.
2. No TOTP secret, recovery code, raw bootstrap token, or encryption key is stored in plaintext in the database, logs, audit payloads, API response, or source control.
3. TOTP secrets are encrypted and authenticated with AES-256-GCM using a unique 96-bit nonce per encryption and a versioned key identifier. Authentication-tag failure is a hard denial; no fallback to plaintext.
4. The AES key is never stored in the database or ordinary application configuration.
5. The Windows key provider must be proven on Windows 10 and 11. No provider may silently fall back to plaintext, user-level unprotected files, or a software keyring with an unknown backend.
6. A missing, corrupt, or unavailable key store makes MFA verification fail closed and produces an operator-safe diagnostic without secret values.
7. Maximum active sessions per user is two. A third login is rejected atomically; existing sessions are preserved.
8. Session expiry is enforced server-side: 15-minute idle timeout, 12-hour absolute lifetime. Warning is a client UX hint at 2 minutes before idle expiry, not an authorization control.
9. GM recovery is a local offline emergency procedure. No ordinary API, staff account, superuser flag, or support bypass can transfer the singleton GM slot.
10. GM MFA is mandatory. Employee MFA remains configurable by GM; do not impose mandatory MFA on every employee.
11. Existing accounting, inventory, posting, reversal, fiscal-period, and frozen Security Batch 2/3 contracts remain unchanged.

## 3. TOTP contract
- RFC 6238 TOTP, 30-second period, SHA-1 compatibility profile, six digits, ±1 time-step verification window; use a maintained cryptographic library.
- Generate high-entropy secrets with the OS CSPRNG. Display enrollment material once over the authenticated local session; never return it again after confirmation.
- Enrollment is pending until a valid code is confirmed. A GM account cannot be provisioned as usable without confirmed TOTP.
- Store only AES-256-GCM ciphertext, 12-byte nonce, key version, and non-secret metadata. Bind ciphertext to stable user identity and purpose using associated authenticated data.
- Rotate/reset operations revoke prior credential and recovery codes in one transaction and emit audit events without secret payloads.
- Employees may enroll/disable only according to the approved role policy; GM enrollment cannot be disabled through ordinary employee/admin APIs.

## 4. Recovery-code contract
- Generate exactly 10 single-use recovery codes after confirmed MFA enrollment.
- Store salted password-hash representations (Django password hasher), not plaintext or reversible ciphertext.
- Show the codes once. Each use consumes exactly one code atomically; concurrent replay must have one winner.
- Rotate codes only after successful strong authentication (password + TOTP or approved local emergency recovery).
- Lost phone: password + one unused recovery code. Lost password and phone: local physical access plus the separately held offline emergency owner key.
- Emergency recovery revokes the old MFA credential and all active sessions, resets credentials through a controlled local utility, then requires new TOTP enrollment and generates a fresh set of recovery codes.
- No secret is printed to stdout, application logs, CI artifacts, or ordinary audit records.

## 5. Session contract
- A durable server-side session registry binds the Django session key to user, creation time, last activity, absolute expiry, revocation state, and non-secret device label.
- Session creation and active-session count enforcement occur inside a database transaction with row-level serialization/locking suitable for SQLite and PostgreSQL. Do not rely on a non-atomic count-then-insert.
- At two active sessions, a third login returns a safe denial and leaves both existing sessions untouched.
- Logout/revocation invalidates both the registry record and the Django session.
- Every protected request validates the registry record and both expiry clocks. Session fixation is prevented by rotating the Django session key after authentication.
- No client-provided user ID, session status, MFA flag, or timestamp is trusted.

## 6. Windows key custody — required proof before provider selection
Evaluate Windows DPAPI CurrentUser and Windows Credential Manager on actual Windows 10 and Windows 11 runners/devices. The selected provider must satisfy:
- Key generation and AES-256-GCM encryption/decryption test.
- Key survives application restart and OS reboot.
- Key is bound to the intended Windows identity and cannot be read by another local account.
- Database backup/restore on the same machine can decrypt previously encrypted TOTP data.
- A documented offline emergency key-recovery process exists for Windows profile loss or computer failure; recovery material is stored separately from the computer and ordinary DB backup.
- No silent fallback if Windows APIs or provider are unavailable.
- Explicitly document DPAPI CurrentUser versus LocalMachine scope, process identity, Tauri/backend launch identity, and credential ACL behavior.
Do not select a provider based solely on a Linux CI result. If Windows proof cannot run in CI, add a dedicated Windows workflow and report it as pending until it executes successfully.

## 7. BasicAuthentication compatibility gate
Before changing authentication classes:
- Inventory every API route and every authentication class it accepts.
- Prove Basic-only requests cannot access GM operations or any operation whose contract requires an active session/MFA.
- Preserve frozen Batch 2/3 route behavior; do not silently remove BasicAuthentication globally.
- Prefer a narrow, explicit authentication policy at the operation boundary, with regression tests for each protected operation and the existing public allowlist.
- Any unavoidable change to a frozen Batch 2/3 contract requires a separate owner decision before implementation.

## 8. Local bootstrap and emergency recovery
- Bootstrap is a local management command, creates a random 256-bit one-time token, persists only its SHA-256 hash, expires in 10 minutes, and consumes once.
- No default password and no network-accessible bootstrap endpoint.
- Emergency recovery requires local physical access and a separately stored offline owner key; it must be explicit, auditable, single-use, and incapable of creating a second concurrent GM holder.
- Existing GM assignment history is preserved. No automatic winner selection or slot overwrite.
- UQ-1 transfer/revocation semantics remain limited to the approved local emergency process; no general GM transfer API is authorized.

## 9. Required tests
SQLite and PostgreSQL:
- TOTP enrollment pending/confirm/reject; correct/incorrect/expired code; clock-window boundaries; AES-GCM tamper and wrong-key denial.
- No plaintext secret/key/code in DB rows, responses, logs, exception messages, or audit payloads.
- Key missing/corrupt/rotation and version handling fail closed.
- Recovery code one-time consumption under concurrency; 10 codes issued; rotation revokes old codes.
- GM cannot operate without confirmed MFA; employee MFA remains optional/configurable.
- Two concurrent sessions succeed; third is denied with original two unchanged; logout/revoke invalidates; idle and absolute expiry.
- Session fixation resistance; anonymous/Basic-only requests cannot bypass MFA/session gates.
- Bootstrap token single-use, 10-minute expiry, hash-only storage, local-only.
- Recovery requires offline owner key, revokes sessions and prior MFA, preserves singleton GM invariant and assignment history.
- Every operation route has authentication/MFA compatibility coverage.
- Migrations apply cleanly to fresh and existing databases; makemigrations --check clean.

Windows 10/11:
- Actual DPAPI/Credential Manager persistence, ACL/isolation, restart/reboot, DB restore, and offline key recovery.
- Packaged Tauri runtime integration, not only cargo check.

## 10. Delivery gates
Work in small commits on this feature branch only. Each batch must include tests and exact commit CI evidence. Keep PR Draft until all W0-2C acceptance criteria pass. Do not merge, enable Production, un-draft, or freeze without explicit owner approval. A green CI job is not sufficient evidence for Windows key custody or packaged desktop behavior.


## 11. Implementation progress (branch evidence; not release acceptance)

Implemented in the current W0-2C branch:
- `security.crypto`: AES-256-GCM envelope primitive; 12-byte nonce; version/key-id metadata; AAD binds purpose and user identity; missing/invalid key and authentication-tag failures deny closed. The provider is injectable only; no Windows provider has been selected.
- `security.mfa`: CSPRNG Base32 TOTP secret generation; RFC 6238 SHA-1 profile; six-digit/30-second TOTP; ±1-step validation; matched counter helper; ten generated recovery codes and Django salted password hashes.
- `security.mfa_models` plus migrations 0006/0007: encrypted MFA device metadata, one-way recovery-code rows, server-side session registry, TOTP replay counter and per-device failed-attempt lock state.
- `security.mfa_service`: pending enrollment, encrypted secret persistence, confirmation, TOTP replay rejection, five-failure/five-minute enrollment throttle, and conditional one-time recovery-code consumption. Key provider must be supplied by the caller.

Not yet implemented:
- No OS-backed Windows key provider; services cannot be enabled in production until one is proven.
- No HTTP/API enrollment or login integration; no GM/employee MFA policy enforcement has been wired into AuthContext or operation resolution.
- No authenticated TOTP step-up flow, disable/rotation lifecycle, or recovery-code rotation.
- No session creation/revocation/expiry enforcement; current session model is a registry schema only.
- No local emergency owner-key utility or bootstrap token workflow.
- No Windows packaged Tauri proof.

Verification note:
- Earlier exact-head CI exposed Django's 30-character index-name limit; the two names were shortened.
- Subsequent runs before migration 0007 were expected to fail the repository's makemigrations --check because the model fields had been added before their migration. Verify the newest exact head after migration 0007 and service tests land; do not infer success from intermediate runs.
## 12. Current implementation snapshot — supersedes earlier status statements

Sections 11 and earlier are historical progress notes. Where they say a capability is not implemented, this section records the later branch state.

### Implemented in code on this feature branch

- AES-256-GCM envelope encryption, 96-bit nonce, version/key-id metadata, and AAD binding to purpose and subject. Key material is injected through the KeyProvider interface; no plaintext, environment-variable, or ordinary-file fallback exists.
- RFC 6238 TOTP profile: SHA-1 compatibility, six digits, 30-second step, ±1-step acceptance, replay-counter enforcement, and per-device failure throttling.
- Durable MFA, recovery-code, and login-session models, including migrations 0006–0011. TOTP secrets are encrypted; recovery codes and session keys are stored only as hashes.
- Password login and logout endpoints, anonymous-login CSRF enforcement, login throttling, audit events, and server-side session registry validation.
- GM MFA is mandatory. Online GM login using a recovery code is denied; GM recovery-code rotation and employee self-service enrollment/disable routes are blocked for GM identities.
- Employee MFA enrollment and confirmation, ten one-time recovery codes, recovery-code rotation after password plus a strong second factor, and optional employee disable only when GM policy does not require MFA. Disabling revokes active sessions.
- GM-controlled employee MFA requirement, restricted to the active singleton-linked GM and written to audit history.
- Two active session slots enforced by a database partial unique constraint; a third session is rejected without evicting either existing session. Idle timeout is 15 minutes; absolute lifetime is 12 hours.
- Initial GM bootstrap commands: issue_gm_bootstrap_token creates a 256-bit, ten-minute, one-time token and stores only its SHA-256 hash; bootstrap_gm is interactive/local-only, requires a configured 32-byte OS-backed provider, confirms TOTP before claiming the singleton GM slot, creates ten hashed recovery codes, consumes the token, and audits the bootstrap.
- Initial bootstrap is permanently closed when any GM assignment history exists or an initial token has already been consumed. This command cannot replace, recover, revoke, or transfer an existing GM.

### Exact CI evidence

- Commit 337d1da946a47dd8e93a2378da5142d658661833, run 42329560991: all four jobs completed successfully — Backend, PostgreSQL 17.11, Frontend, and Tauri.
- Backend Django suite: 431 tests, 2 skipped. pytest suite: 1,342 passed, 10 skipped. PostgreSQL Django suite: 431 tests and POSTGRESQL VERIFICATION: PASS.
- Frontend audit reported zero vulnerabilities. Tauri evidence is the Linux shell cargo check plus frontend build; it is not a Windows installer or packaged runtime test.
- Commit c57995b70d5823b9c719e8d47d603966bc988d28 renamed three test key-provider helper classes to eliminate pytest collection warnings. Its exact-head CI run must complete before that warning cleanup is called verified.

### Not implemented / not verified — release blockers

1. No production Windows key provider has been selected or integrated. The backend still exposes only the injected KeyProvider interface. DPAPI CurrentUser and Windows Credential Manager must be compared under the actual execution identity on Windows 10 and Windows 11; Linux CI cannot prove Windows ACLs, persistence, reboot behavior, profile loss, or key recovery.
2. The Tauri shell currently packages only the React frontend. Its Rust entry point has no backend sidecar/process integration or key-provider bridge. The Django runtime is not yet launched by the desktop shell. Therefore the Windows backend execution identity and local-only service boundary are not yet established.
3. No separate offline GM emergency owner-key workflow exists. Lost-password-and-phone recovery, secure key custody outside the computer, MFA/session revocation, replacement TOTP enrollment, and audit-preserving local recovery remain unimplemented.
4. Django Admin remains deny-all. A dedicated singleton-GM-plus-verified-MFA gate must be implemented and tested for every Admin request before it can be enabled.
5. The two-minute session-expiry warning, packaged Windows installer/runtime tests, and actual Windows 10/11 validation remain outstanding.
6. BasicAuthentication still requires the planned route-by-route compatibility review before any broader authentication-class change.
7. Account lockout and related W0-2D controls, append-only/hash-chain audit controls in W0-2E, and trusted-origin controls in W0-2F remain separate workstreams.

### Release decision

W0-2C remains Draft, Open, unmerged, and not Production-ready. The successful run above verifies only the exact commit cited. The current branch head must have its own successful CI before its latest changes are verified. No merge, un-draft, Production enablement, or freeze is authorized by this status update.
