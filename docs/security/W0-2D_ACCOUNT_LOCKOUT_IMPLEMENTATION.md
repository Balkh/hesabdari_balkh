# W0-2D — Account Lockout and GM Recovery Administration

**Status:** Implementation candidate on `security/w0-2d-account-lockout`; not merged or owner-approved.  
**Contract:** W0-2A §9A Item 4 numeric defaults and OD-5 account-security requirements.

## Owner-approved policy implemented

- Five consecutive failed password authentications lock an active account.
- Lock duration is 15 minutes.
- Failure counter resets after 15 minutes without another failed password attempt or after successful authentication.
- The lock is bounded and expires automatically.
- The existing password-login endpoint's 10/minute anonymous source throttle remains unchanged.
- The existing security_login 10/minute setting is reused as a database-backed rate budget independently per account and local source. Password login keeps its existing DRF source throttle; BasicAuthentication requests receive a pre-authentication middleware check without changing the frozen authenticator class list.

## Runtime behavior

- A persistent `SecurityAccountLockout` row stores the per-account failure count, last failure time, and lock expiry.
- A request-scoped ContextVar supplies the actual ASGI/WSGI request to Django's `user_login_failed` signal when DRF BasicAuthentication calls Django authentication without a request object. Source fingerprints use only the socket peer address; forwarded headers and user-agent values are not trusted or stored.
- Both password login and BasicAuthentication are rate-limited against recent failures by username fingerprint and local-source fingerprint, using the existing 10/minute `security_login` setting and the new account/time index. This works from the existing local database and does not add Redis or another cache service.
- `SecurityLoginAttempt` stores recent authentication outcomes using keyed HMAC fingerprints; it does not store plaintext username, source IP, user agent, password, or token.
- Authorization checks the account-lock predicate at policy step 2, before protected GM authority or role grants. When the fifth password failure triggers a lock, all registered active sessions for that account are revoked in the same database transaction. A timed expiry or GM unlock therefore cannot revive a previously admitted session.
- Successful session login resets consecutive failures. A successful eligible BasicAuthentication request clears stale failures only when no active lock exists.
- MFA failures are recorded for GM review but do not increment the password-failure counter.
- A registered session with verified GM MFA is required to review recent attempts and issue an early unlock. Unlock requires a non-empty reason and writes an audit event in the same transaction as the state reset.
- If the GM account itself is locked, its web review API is not available; use the already implemented local offline owner-key recovery path. Django Admin remains disabled.

## Security boundaries

- The new history never stores raw credentials or plaintext usernames/source addresses.
- BasicAuthentication remains present under the frozen compatibility contract; this batch does not claim it gains W0-2C registry-session timeout/revocation semantics.
- The existing 10/minute DRF throttle remains on the password-login endpoint. The additional database-backed account/source check also protects the BasicAuthentication path; it does not introduce a new authenticator class or alter the frozen route matrix.
- AuditEvent remains the pre-W0-2E audit foundation. Events are recorded, but this batch does not claim database append-only/hash-chain guarantees.
- CI evidence does not replace Windows end-user acceptance.

## Required evidence before review

SQLite and PostgreSQL migration/full-test results are required, with explicit checks for threshold, 15-minute lock, reset boundary, successful-login reset, generic denial, BasicAuthentication failure capture, existing-session denial, GM/MFA-only review/unlock, non-GM denial, and audit evidence.
