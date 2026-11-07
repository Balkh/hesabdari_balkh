"""Server-side admission and validation for the W0-2C session registry."""
from __future__ import annotations

import hashlib
import time
from datetime import timedelta

from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from security.mfa_models import SecurityLoginSession

SESSION_MAX_ACTIVE = 2
SESSION_IDLE_TIMEOUT = timedelta(minutes=15)
SESSION_ABSOLUTE_LIFETIME = timedelta(hours=12)


class SessionAdmissionError(RuntimeError):
    """A session cannot be admitted without violating security invariants."""


def session_key_digest(session_key: str) -> str:
    if not isinstance(session_key, str) or not session_key:
        raise ValueError("a valid Django session key is required")
    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()


def _register_login_session_once(user, session_key: str, *, mfa_verified_at=None, at=None):
    """Register one authenticated Django session in one of two DB-enforced slots."""
    if user is None or getattr(user, "pk", None) is None or not getattr(user, "is_authenticated", False):
        raise ValueError("a persisted authenticated user is required")
    digest = session_key_digest(session_key)
    now = at or timezone.now()
    absolute_expiry = now + SESSION_ABSOLUTE_LIFETIME
    idle_expiry = min(now + SESSION_IDLE_TIMEOUT, absolute_expiry)
    expired_existing = False

    try:
        with transaction.atomic():
            type(user)._default_manager.select_for_update().get(pk=user.pk)
            existing = SecurityLoginSession.objects.select_for_update().filter(
                session_key_hash=digest
            ).first()
            if existing is not None:
                if existing.user_id != user.pk or existing.revoked_at is not None:
                    raise SessionAdmissionError("session cannot be reused")
                if existing.idle_expires_at <= now or existing.absolute_expires_at <= now:
                    existing.revoked_at = now
                    existing.revoke_reason = "EXPIRED"
                    existing.save(update_fields=["revoked_at", "revoke_reason"])
                    expired_existing = True
                else:
                    return existing

            # Close expired records before choosing one of the two durable slots.
            # If the submitted key itself was expired, commit its closure first;
            # deny reuse only after the transaction has committed.
            if not expired_existing:
                SecurityLoginSession.objects.filter(
                    user=user, revoked_at__isnull=True
                ).filter(
                    Q(idle_expires_at__lte=now) | Q(absolute_expires_at__lte=now)
                ).update(revoked_at=now, revoke_reason="EXPIRED")

                occupied = set(
                    SecurityLoginSession.objects.filter(
                        user=user, revoked_at__isnull=True
                    ).values_list("slot_number", flat=True)
                )
                if len(occupied) >= SESSION_MAX_ACTIVE:
                    raise SessionAdmissionError("maximum active sessions reached")

                for slot_number in (1, 2):
                    if slot_number in occupied:
                        continue
                    try:
                        with transaction.atomic():
                            return SecurityLoginSession.objects.create(
                                user=user,
                                session_key_hash=digest,
                                slot_number=slot_number,
                                created_at=now,
                                last_seen_at=now,
                                idle_expires_at=idle_expiry,
                                absolute_expires_at=absolute_expiry,
                                mfa_verified_at=mfa_verified_at,
                            )
                    except IntegrityError:
                        continue
                raise SessionAdmissionError("maximum active sessions reached")
        if expired_existing:
            raise SessionAdmissionError("session has expired")
    except SessionAdmissionError:
        raise


def register_login_session(user, session_key: str, *, mfa_verified_at=None, at=None):
    """Register with bounded SQLite lock retry; never bypass the DB slot cap."""
    from django.db import connections

    connection = connections["default"]
    max_attempts = 5 if connection.vendor == "sqlite" else 1
    for attempt in range(max_attempts):
        try:
            return _register_login_session_once(
                user,
                session_key,
                mfa_verified_at=mfa_verified_at,
                at=at,
            )
        except DatabaseError as exc:
            message = str(exc).lower()
            retryable_sqlite_lock = (
                connection.vendor == "sqlite"
                and ("locked" in message or "busy" in message)
            )
            if retryable_sqlite_lock and attempt + 1 < max_attempts:
                # The failed atomic block has rolled back before this bounded
                # backoff. A new transaction re-reads the occupied slots.
                time.sleep(0.025 * (attempt + 1))
                continue
            raise SessionAdmissionError("session registry is unavailable") from None
    raise SessionAdmissionError("session registry is unavailable")


def touch_login_session(user, session_key: str, *, at=None):
    """Validate a registry row and extend idle expiry without extending absolute expiry."""
    if user is None or getattr(user, "pk", None) is None:
        return None
    digest = session_key_digest(session_key)
    now = at or timezone.now()
    try:
        with transaction.atomic():
            row = SecurityLoginSession.objects.select_for_update().filter(
                user=user, session_key_hash=digest, revoked_at__isnull=True
            ).first()
            if row is None:
                return None
            if row.idle_expires_at <= now or row.absolute_expires_at <= now:
                row.revoked_at = now
                row.revoke_reason = "EXPIRED"
                row.save(update_fields=["revoked_at", "revoke_reason"])
                return None
            row.last_seen_at = now
            row.idle_expires_at = min(now + SESSION_IDLE_TIMEOUT, row.absolute_expires_at)
            row.save(update_fields=["last_seen_at", "idle_expires_at"])
            return row
    except DatabaseError:
        return None


def revoke_login_session(user, session_key: str, *, reason="LOGOUT", at=None) -> bool:
    digest = session_key_digest(session_key)
    now = at or timezone.now()
    updated = SecurityLoginSession.objects.filter(
        user=user, session_key_hash=digest, revoked_at__isnull=True
    ).update(revoked_at=now, revoke_reason=reason[:40])
    return updated == 1


def revoke_all_login_sessions(user, *, reason="SECURITY_RESET", at=None) -> int:
    now = at or timezone.now()
    return SecurityLoginSession.objects.filter(
        user=user, revoked_at__isnull=True
    ).update(revoked_at=now, revoke_reason=reason[:40])
