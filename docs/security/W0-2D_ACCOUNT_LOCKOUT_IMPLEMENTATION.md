# W0-2D — Account Lockout and GM Recovery Administration

**Status:** Implementation candidate on `security/w0-2d-account-lockout`; not merged or owner-approved.  
**Contract:** W0-2A §9A Item 4 numeric defaults and OD-5 account-security requirements.

## Owner-approved policy implemented

- Five consecutive failed password authentications lock an active account.
- Lock duration is 15 minutes.
- Failure counter resets after 15 minutes without another failed password attempt or after successful authentication.
- The lock is bounded and expires automatically.
- The existing password-login endpoint's 10/minute anonymous source throttle remains unchanged.
- Django's failed-authentication signal captures unsuccessful ModelBackend and existing DRF BasicAuthentication attempts without replacing the frozen authenticator class list.

## Runtime behavior

- A persistent `SecurityAccountLockout` row stores the per-account failure count, last failure time, and lock expiry.
- `SecurityLoginAttempt` stores recent authentication outcomes using keyed HMAC fingerprints; it does not store plaintext username, source IP, user agent, password, or token.
- Authorization checks the account-lock predicate at policy step 2, before protected GM authority or role grants. When the fifth password failure triggers a lock, all registered active sessions for that account are revoked in the same database transaction. A timed expiry or GM unlock therefore cannot revive a previously admitted session.
- Successful session login resets consecutive failures. A successful eligible BasicAuthentication request clears stale failures only when no active lock exists.
- MFA failures are recorded for GM review but do not increment the password-failure counter.
- A registered session with verified GM MFA is required to review recent attempts and issue an early unlock. Unlock requires a non-empty reason and writes an audit event in the same transaction as the state reset.
- If the GM account itself is locked, its web review API is not available; use the already implemented local offline owner-key recovery path. Django Admin remains disabled.

## Security boundaries

- The new history never stores raw credentials or plaintext usernames/source addresses.
- BasicAuthentication remains present under the frozen compatibility contract; this batch does not claim it gains W0-2C registry-session timeout/revocation semantics.
- The existing 10/minute throttle applies to the password-login endpoint. BasicAuthentication failures are logged and counted against the account policy; this batch does not introduce a new authenticator class or alter the frozen route matrix.
- AuditEvent remains the pre-W0-2E audit foundation. Events are recorded, but this batch does not claim database append-only/hash-chain guarantees.
- CI evidence does not replace Windows end-user acceptance.

## Required evidence before review

SQLite and PostgreSQL migration/full-test results are required, with explicit checks for threshold, 15-minute lock, reset boundary, successful-login reset, generic denial, BasicAuthentication failure capture, existing-session denial, GM/MFA-only review/unlock, non-GM denial, and audit evidence.
