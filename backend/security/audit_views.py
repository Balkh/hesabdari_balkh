"""GM-only audit review, bounded export, and integrity diagnostics."""

from __future__ import annotations

import json
import logging

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import HttpResponse
from django.utils.cache import add_never_cache_headers
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from security.audit_chain import (
    AuditChainVerificationError,
    assert_audit_trigger_schema,
    _redact_sensitive,
    verify_audit_chain,
)
from security.models import AuditAction, AuditEvent
from security.operation_registry import (
    COLLECTION,
    TARGET_NONE,
    OperationSpec,
    erp_operations,
)
from security.permissions import (
    HasErpOperation,
    IsAuthenticatedForERP,
    IsGMWithVerifiedMFA,
)

logger = logging.getLogger("security.audit")


def _verify_or_unavailable():
    try:
        assert_audit_trigger_schema()
        return verify_audit_chain()
    except AuditChainVerificationError:
        logger.exception("audit chain verification failed; withholding audit data")
        return None
    except Exception:
        logger.exception("audit chain storage is unavailable; withholding audit data")
        return None


def _build_audit_events_payload(request):
    """Reject invalid filters before acquiring the ledger-wide read lock."""
    raw_limit = request.query_params.get("limit", "50")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return None, Response({"error": "invalid_limit"}, status=status.HTTP_400_BAD_REQUEST)
    if not 1 <= limit <= 1000:
        return None, Response(
            {"error": "limit_must_be_between_1_and_1000"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    queryset = AuditEvent.objects.order_by("-id")
    action = request.query_params.get("action")
    if action:
        if action not in AuditAction.values:
            return None, Response({"error": "invalid_action"}, status=status.HTTP_400_BAD_REQUEST)
        queryset = queryset.filter(action=action)
    entity = request.query_params.get("entity")
    if entity:
        if len(entity) > 100:
            return None, Response({"error": "invalid_entity"}, status=status.HTTP_400_BAD_REQUEST)
        queryset = queryset.filter(entity=entity)
    before_id = request.query_params.get("before_id")
    if before_id:
        try:
            parsed_before_id = int(before_id)
        except (TypeError, ValueError):
            return None, Response({"error": "invalid_before_id"}, status=status.HTTP_400_BAD_REQUEST)
        if parsed_before_id <= 0:
            return None, Response({"error": "invalid_before_id"}, status=status.HTTP_400_BAD_REQUEST)
        queryset = queryset.filter(pk__lt=parsed_before_id)

    return _materialize_verified_page(queryset, limit)


@transaction.atomic
def _materialize_verified_page(queryset, limit):
    """Materialize the page before releasing the chain snapshot lock."""
    integrity = _verify_or_unavailable()
    if integrity is None:
        return None, Response(
            {"error": "audit_integrity_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    rows = list(queryset[:limit])
    payload = [
        {
            "id": event.pk,
            "event_uuid": str(event.event_uuid),
            "event_hash": event.event_hash,
            "prev_event_hash": event.prev_event_hash,
            "actor_user_id": event.user_id,
            "actor": _redact_sensitive(event.actor_snapshot),
            "authorization_context": _redact_sensitive(event.authorization_context),
            "action": event.action,
            "entity": _redact_sensitive(event.entity),
            "entity_id": _redact_sensitive(event.entity_id),
            "reference": _redact_sensitive(event.reference),
            "previous_state": _redact_sensitive(event.previous_state),
            "new_state": _redact_sensitive(event.new_state),
            "reason": _redact_sensitive(event.reason),
            "created_at": event.created_at.isoformat(),
        }
        for event in rows
    ]
    response_data = {
        "integrity": {
            "valid": integrity["valid"],
            "event_count": integrity["event_count"],
            "head_hash": integrity["head_hash"],
            "last_event_id": integrity["last_event_id"],
        },
        "events": payload,
        "next_before_id": rows[-1].pk if len(rows) == limit else None,
    }


    return response_data, None


@erp_operations(
    GET=OperationSpec(
        operation_id="security.audit.events.list",
        permission_key="audit.report.view",
        binding_kind=COLLECTION,
        target_source=TARGET_NONE,
    )
)
@api_view(["GET", "HEAD"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, IsGMWithVerifiedMFA, HasErpOperation])
def audit_events(request):
    """Return a bounded GM-only event page; export has a separate permission."""
    if "export" in request.query_params:
        return Response(
            {"error": "use_dedicated_audit_export_endpoint"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    payload, error = _build_audit_events_payload(request)
    response = error if error is not None else Response(payload)
    add_never_cache_headers(response)
    return response


@erp_operations(
    GET=OperationSpec(
        operation_id="security.audit.events.export",
        permission_key="audit.report.export",
        binding_kind=COLLECTION,
        target_source=TARGET_NONE,
    )
)
@api_view(["GET", "HEAD"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, IsGMWithVerifiedMFA, HasErpOperation])
def audit_events_export(request):
    """Export a bounded audit page; the route itself requires export permission."""
    payload, error = _build_audit_events_payload(request)
    if error is not None:
        return error
    response = HttpResponse(
        json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(",", ":")),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="hesabdari-audit-events.json"'
    add_never_cache_headers(response)
    return response



@erp_operations(
    GET=OperationSpec(
        operation_id="security.audit.integrity.view",
        permission_key="audit.report.view",
        binding_kind=COLLECTION,
        target_source=TARGET_NONE,
    )
)
@api_view(["GET", "HEAD"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, IsGMWithVerifiedMFA, HasErpOperation])
def audit_integrity(request):
    """GM-only on-demand integrity diagnostic; never repairs or rewrites history."""
    integrity = _verify_or_unavailable()
    if integrity is None:
        return Response(
            {"status": "INVALID_OR_UNAVAILABLE"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    response = Response({"status": "VALID", **integrity})
    add_never_cache_headers(response)
    return response
