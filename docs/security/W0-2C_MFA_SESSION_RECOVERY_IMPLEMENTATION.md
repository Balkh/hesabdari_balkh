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
## 12. Current implementation and acceptance status — supersedes earlier snapshots

Sections 11 and earlier are historical progress records. Their “not implemented” statements describe earlier commits and must not be read as the current branch state.

### Implemented on this W0-2C branch

- AES-256-GCM envelope encryption with 96-bit nonces, version/key-id metadata, and authenticated purpose/user binding. There is no plaintext, environment-variable, or ordinary-file key fallback.
- A Windows desktop Credential Manager provider stores the AES-256 key, active key ID, and a separate Django signing secret in the current user's credential vault. The desktop settings profile loads these secrets and fails closed when they are missing or malformed. The provisioning command is local-console-only and never prints the secret values. This is an implemented desktop provider candidate, not yet accepted as a production desktop runtime provider.
- RFC 6238 TOTP: SHA-1 compatibility profile, six digits, 30-second period, ±1-step verification, replay-counter enforcement, and per-device failure throttling.
- MFA models and migrations 0006–0012 cover encrypted devices, one-time recovery hashes, session records/admission slots, employee policy, bootstrap token, and emergency owner-key history.
- GM MFA is mandatory. Employee MFA is optional unless required by the active singleton GM. Basic-only requests cannot satisfy an MFA-required operation; MFA management and recovery endpoints use SessionAuthentication.
- Password login/logout, CSRF/throttle protection, audit events, and active session-registry validation are wired. Registered sessions have two admission slots, 15-minute idle timeout, and 12-hour absolute lifetime. A third concurrent session is rejected without evicting the existing two.
- Initial GM bootstrap uses a random one-time token (stored as a hash), requires confirmed TOTP, claims the singleton slot, creates ten hashed recovery codes, and creates the separate offline owner-key record. Bootstrap closes permanently once GM assignment history or a consumed bootstrap token exists.
- Offline emergency recovery restores the existing singleton GM in place; consumes the offline owner key; rotates the password, TOTP device, recovery codes, and owner key; revokes sessions; and records a secret-free audit event. It never creates a second GM or silently selects another assignment.
- Emergency bootstrap, provisioning, owner-key rotation, and recovery management commands share a local-console guard. On Windows it checks the active physical-console session ID against the process session ID, rejects remote-session and remotely controlled/shadowed sessions, checks the `GlassSessionId` registry discriminator for RemoteFX cases, and fails closed when the operating-system check is unavailable.
- Operation-specific API regression tests cover MFA-policy target binding and stale-user races; Accountant denial of fiscal-period close/reopen/lock/unlock; Accountant landed-cost create/post but not reverse; BasicAuthentication compatibility behavior; and idle/absolute session expiry at the protected API boundary.
- Windows CI now calls native session APIs and checks the remote-session registry discriminator in addition to the DPAPI/Credential Manager evaluation tests.

### BasicAuthentication compatibility boundary

BasicAuthentication remains available only through the existing frozen compatibility routes for non-GM users whose policy does not require MFA. It creates no `SecurityLoginSession` registry record, so it does not receive the two-session cap, idle/absolute session timeout, or per-session revocation. GM and MFA-required employee Basic-only requests are denied; the MFA management endpoints are SessionAuthentication-only. This is an explicit residual risk and must be resolved through a separate owner decision before release; do not silently remove the frozen Batch 2/3 compatibility path.

### Verification evidence and limits

- Earlier exact-head run [#45226546025](https://github.com/Balkh/hesabdari_balkh/actions/runs/45226546025) for commit `560c3a9d191f0a127686853a1501a52c9b2cc52a` completed all seven jobs successfully. Backend: 1,367 passed / 16 skipped; PostgreSQL: 1,377 passed / 6 skipped, with `POSTGRESQL VERIFICATION: PASS`. That run predates the local-console hardening and the newest native Windows session probe.
- Latest source changes require their own exact-head CI. Do not carry forward the older green result to a newer commit.
- GitHub-hosted Windows checks cover Windows Server 2022 x64, Windows Server 2025 x64, and Windows 11 ARM64. Those checks are not a substitute for customer Windows 10/11 x64 desktops, reboot persistence, cross-user isolation, database backup/restore, or a real offline recovery drill.
- The current Tauri Rust entry point builds the shell only. It does not launch/supervise a packaged Django backend or prove the backend runs under the same Windows identity that owns Credential Manager secrets. Linux `cargo check` is not evidence of a Windows packaged runtime.

### Remaining acceptance blockers

1. Complete the manual Windows 10/11 x64 procedures in [W0-2C Windows Acceptance Runbook](W0-2C_WINDOWS_ACCEPTANCE_RUNBOOK.md): reboot persistence, second-user isolation, actual RDP/shadow/WinRM denial, same-user backup/restore, and simulated profile-loss recovery against a disposable database.
2. Implement and test the packaged Tauri-to-Django process lifecycle, loopback-only service boundary, app-data database path, startup/health/shutdown behavior, and proof of a single intended Windows user identity.
3. The React frontend is still a foundation shell with no authenticated login/session application flow. The two-minute pre-expiry warning UX is therefore not implemented or validated.
4. BasicAuthentication's session-control bypass requires an explicit owner policy decision before production acceptance.
5. Django Admin remains deny-all (404). Do not reopen it until its dedicated GM + verified MFA + account-lockout gate is implemented and tested.
6. W0-2D account lockout/recovery policy, W0-2E append-only/hash-chain audit controls, and W0-2F trusted-origin controls remain separate workstreams. The current `account_locked()` seam is a no-op until W0-2D ships.

### Release decision

W0-2C remains Draft, Open, unmerged, and not Production-ready. A green CI run verifies only the exact commit it ran against. Manual Windows acceptance, packaged desktop integration, owner review, and explicit owner approval are still required. No merge, un-draft, Production activation, or freeze is authorized by this status update.
