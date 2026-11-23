"""Canonical, transactional append-only audit hash chain (W0-2E)."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from uuid import UUID, uuid4

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone

from security.models import AuditChainHead, AuditEvent

GENESIS_HASH = "0" * 64
HASH_DOMAIN = b"HESABDARI-AUDIT-CHAIN-V1\x00"
CANONICAL_SCHEMA = "hesabdari.audit-event.v1"


class AuditChainError(RuntimeError):
    """The append protocol or chain integrity check cannot safely continue."""


class AuditChainVerificationError(AuditChainError):
    """Persisted audit history does not form one valid chain."""


def _canonical_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("non-finite floats are not permitted in audit metadata")
        return value
    if isinstance(value, UUID):
        return str(value).lower()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("non-finite Decimal values are not permitted in audit metadata")
        if value == 0:
            return "0"
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            raise TypeError("naive datetimes are not permitted in audit metadata")
        normalized = value.astimezone(dt_timezone.utc)
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("binary values are not permitted in audit metadata")
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("audit metadata object keys must be strings")
            normalized[key] = _canonical_value(item)
        return {key: normalized[key] for key in sorted(normalized)}
    raise TypeError(f"unsupported audit metadata type: {type(value).__name__}")


def canonical_json_bytes(payload) -> bytes:
    normalized = _canonical_value(payload)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def immutable_event_payload(event) -> dict:
    return {
        "schema": CANONICAL_SCHEMA,
        "event_uuid": str(event.event_uuid).lower(),
        "user_id": event.user_id,
        "action": event.action,
        "entity": event.entity,
        "entity_id": event.entity_id,
        "reference": event.reference,
        "previous_state": event.previous_state,
        "new_state": event.new_state,
        "reason": event.reason,
        "created_at": event.created_at,
        "actor_snapshot": event.actor_snapshot,
        "authorization_context": event.authorization_context,
        "source_fingerprint": event.source_fingerprint,
    }


def calculate_event_hash(previous_hash: str, payload: dict) -> str:
    if (
        not isinstance(previous_hash, str)
        or len(previous_hash) != 64
        or any(char not in "0123456789abcdef" for char in previous_hash)
    ):
        raise ValueError("prev_event_hash must be 64 lowercase hexadecimal characters")
    return hashlib.sha256(
        HASH_DOMAIN + bytes.fromhex(previous_hash) + canonical_json_bytes(payload)
    ).hexdigest()


_SENSITIVE_AUDIT_KEYS = {
    "password", "passwd", "passphrase", "totp", "totpcode",
    "recoverycode", "recoverycodes", "secret", "secretkey",
    "ownerkey", "encryptionkey", "privatekey", "ciphertext",
    "nonce", "credential", "credentials", "authorizationheader",
    "accesstoken", "refreshtoken", "apikey",
}
_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:password|passwd|passphrase|totp(?:[\s_-]*code)?|"
    r"recovery[\s_-]*codes?|owner[\s_-]*key|access[\s_-]*token|"
    r"refresh[\s_-]*token|api[\s_-]*key)\b\s*[:=]\s*)"
    r"[^\s,;&]+"
)
_BEARER_SECRET_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_OTP_URI_SECRET_PATTERN = re.compile(r"(?i)(otpauth://totp/[^?\s]+\?secret=)[^&\s]+")


def _redact_text(value):
    if not isinstance(value, str):
        return value
    value = _INLINE_SECRET_PATTERN.sub(r"\1[REDACTED]", value)
    value = _BEARER_SECRET_PATTERN.sub("Bearer [REDACTED]", value)
    return _OTP_URI_SECRET_PATTERN.sub(r"\1[REDACTED]", value)


def _redact_sensitive(value):
    """Redact credential-like fields recursively before they enter the ledger."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = "".join(ch for ch in str(key).lower() if ch.isalnum())
            if normalized in _SENSITIVE_AUDIT_KEYS or any(
                marker in normalized
                for marker in ("password", "totp", "recoverycode", "privatekey", "ciphertext")
            ):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = _redact_sensitive(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _request_context():
    try:
        from security.request_context import get_current_request
        return get_current_request()
    except Exception:
        return None


def _source_fingerprint(request) -> str:
    if request is None:
        return ""
    remote = str(getattr(request, "META", {}).get("REMOTE_ADDR") or "unknown")[:128]
    message = b"audit-source\x00" + remote.encode("utf-8", errors="replace")
    return hmac.new(str(settings.SECRET_KEY).encode("utf-8"), message, hashlib.sha256).hexdigest()


def _actor_snapshot(user, at):
    if user is None or getattr(user, "pk", None) is None:
        return {
            "actor_type": "ANONYMOUS_OR_SYSTEM",
            "user_id": None,
            "roles": [],
            "permission_overrides": [],
            "historical_source": "captured_at_event_time",
        }

    from django.db.models import Q
    from security.models import (
        GMRoleSlot,
        RolePermission,
        UserPermissionOverride,
        UserRoleAssignment,
    )

    assignments = list(
        UserRoleAssignment.objects.filter(
            user_id=user.pk,
            role__is_active=True,
            revoked_at__isnull=True,
            start_at__lte=at,
        ).filter(Q(end_at__isnull=True) | Q(end_at__gt=at))
        .select_related("role")
        .order_by("role__code", "pk")
    )
    gm_slot_assignment_id = GMRoleSlot.objects.filter(code="GM").values_list(
        "assignment_id", flat=True
    ).first()
    roles = []
    for assignment in assignments:
        if assignment.role.code == "GM" and assignment.pk != gm_slot_assignment_id:
            continue
        permission_keys = list(
            RolePermission.objects.filter(
                role_id=assignment.role_id,
                permission__is_active=True,
            ).order_by("permission__key").values_list("permission__key", flat=True)
        )
        roles.append({
            "assignment_id": assignment.pk,
            "role_code": assignment.role.code,
            "start_at": assignment.start_at,
            "end_at": assignment.end_at,
            "permission_keys": permission_keys,
        })

    overrides = list(
        UserPermissionOverride.objects.filter(
            user_id=user.pk,
            revoked_at__isnull=True,
            start_at__lte=at,
        ).filter(Q(end_at__isnull=True) | Q(end_at__gt=at))
        .select_related("permission")
        .order_by("permission__key")
        .values("permission__key", "effect", "start_at", "end_at")
    )
    username_field = user.USERNAME_FIELD
    return {
        "actor_type": "USER",
        "user_id": str(user.pk),
        "username": str(getattr(user, username_field, "")),
        "roles": roles,
        "permission_overrides": overrides,
        "historical_source": "captured_at_event_time",
    }


def _authorization_snapshot(request, supplied):
    if supplied is not None:
        return {"capture": "SERVICE_ARGUMENT", "context": supplied}
    if request is None:
        return {
            "capture": "MANAGEMENT_OR_BACKGROUND",
            "operation_id": None,
            "permission_key": None,
        }
    request_context = getattr(request, "_erp_authorization_audit_context", None)
    if request_context is not None:
        return {"capture": "REQUEST_AUTHORIZATION", "context": request_context}
    authenticator = getattr(request, "successful_authenticator", None)
    return {
        "capture": "REQUEST_AUTHENTICATION_ONLY",
        "operation_id": None,
        "permission_key": None,
        "authenticator": type(authenticator).__name__ if authenticator is not None else None,
    }


def append_audit_event(
    *,
    user,
    action,
    entity,
    entity_id,
    reference,
    previous_state,
    new_state,
    reason,
    authorization_context=None,
):
    if not connection.in_atomic_block:
        raise AuditChainError("audit events must be appended inside the caller's business transaction")
    if connection.vendor == "sqlite":
        transaction_mode = connection.settings_dict.get("OPTIONS", {}).get("transaction_mode")
        if str(transaction_mode).upper() != "IMMEDIATE":
            raise AuditChainError("SQLite audit append requires an outermost IMMEDIATE transaction")

    now = timezone.now()
    request = _request_context()
    # The head UPDATE is deliberately the first chain operation. On PostgreSQL
    # it obtains the row lock under READ COMMITTED; SQLite already owns the
    # write reservation from BEGIN IMMEDIATE.
    try:
        touched = AuditChainHead.objects.filter(pk=1).update(updated_at=now)
        if touched != 1:
            raise AuditChainError("audit chain singleton head is missing; apply migrations")
        head = AuditChainHead.objects.select_for_update().get(pk=1)
    except DatabaseError as exc:
        raise AuditChainError("audit chain serialization failed; whole business transaction must roll back") from exc

    event = AuditEvent(
        user=user,
        action=action,
        entity=entity,
        entity_id=_redact_text(str(entity_id)),
        reference=_redact_text(reference or ""),
        # Normalize JSONField payloads to their exact persisted representation
        # before hashing; the JSON encoder must not transform Decimal, UUID or
        # datetime values after the digest has been calculated.
        previous_state=_canonical_value(_redact_sensitive(previous_state)),
        new_state=_canonical_value(_redact_sensitive(new_state)),
        reason=_redact_text(reason or ""),
        event_uuid=uuid4(),
        prev_event_hash=head.head_hash,
        actor_snapshot=_canonical_value(_redact_sensitive(_actor_snapshot(user, now))),
        authorization_context=_canonical_value(
            _redact_sensitive(_authorization_snapshot(request, authorization_context))
        ),
        source_fingerprint=_source_fingerprint(request),
        created_at=now,
    )
    event.event_hash = calculate_event_hash(
        event.prev_event_hash, immutable_event_payload(event)
    )
    event.save(force_insert=True)

    head.head_hash = event.event_hash
    head.last_event = event
    head.save(update_fields=["head_hash", "last_event", "updated_at"])
    return event


def verify_audit_chain(*, using="default") -> dict:
    from security.models import AuditEvent, AuditChainHead

    events = list(AuditEvent.objects.using(using).all().order_by("pk"))
    if not AuditChainHead.objects.using(using).filter(pk=1).exists():
        raise AuditChainVerificationError("audit chain singleton head is missing")
    head = AuditChainHead.objects.using(using).get(pk=1)
    by_previous = {}
    for event in events:
        if event.prev_event_hash in by_previous:
            raise AuditChainVerificationError("duplicate successor/fork at previous hash")
        by_previous[event.prev_event_hash] = event

    current = GENESIS_HASH
    visited = []
    seen_uuid = set()
    while current in by_previous:
        event = by_previous[current]
        if event.event_uuid in seen_uuid:
            raise AuditChainVerificationError("duplicate event UUID or cycle detected")
        seen_uuid.add(event.event_uuid)
        expected = calculate_event_hash(current, immutable_event_payload(event))
        if not hmac.compare_digest(expected, event.event_hash):
            raise AuditChainVerificationError(f"event hash mismatch at event id {event.pk}")
        visited.append(event)
        current = event.event_hash

    if len(visited) != len(events):
        raise AuditChainVerificationError("orphan, missing link, or disconnected audit event detected")
    last_id = visited[-1].pk if visited else None
    if head.head_hash != current or head.last_event_id != last_id:
        raise AuditChainVerificationError("audit chain head does not match the verified final event")
    return {
        "valid": True,
        "event_count": len(visited),
        "head_hash": current,
        "last_event_id": last_id,
    }
