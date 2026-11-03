"""Thin operational API over the frozen fiscal-period domain (Phase 3.2).

No business rules live here: every decision (range, overlap, lifecycle
transitions, authorization, reason, close validation, audit) is made by
``fiscal_periods.services``. There is deliberately no PUT/PATCH/DELETE
surface and no status-write field anywhere — a period's status can only
change through the audited lifecycle services, so bypassing them is
impossible by construction.

Auth reuses the existing mechanism (Session/Basic +
``IsAuthenticatedForERP``); role granularity belongs to Phase 15.
Domain failures map to the existing ``{"error": ...}`` shape.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response

from security.operation_registry import OperationSpec, TARGET_URL_KWARG, erp_operations
from security.permissions import HasErpOperation, IsAuthenticatedForERP

from .models import FiscalPeriod
from .serializers import (
    FiscalPeriodSerializer,
    LifecycleReasonSerializer,
    PeriodCreateSerializer,
)
from .services import (
    PeriodValidationError,
    close_period,
    create_period,
    lock_period,
    reopen_period,
    unlock_period,
)

_AUTH_CLASSES = [SessionAuthentication, BasicAuthentication]


def _domain_error(exc):
    """Map a frozen-service rejection to the existing API error shape."""
    return Response(
        {"error": {"code": "http_400", "message": str(exc)}},
        status=http_status.HTTP_400_BAD_REQUEST,
    )


@erp_operations(
    GET=OperationSpec(
        operation_id="fiscal.period.collection.list",
        permission_key="fiscal.period.view",
        binding_kind="COLLECTION",
    ),
    POST=OperationSpec(
        operation_id="fiscal.period.collection.create",
        permission_key="fiscal.period.create",
        binding_kind="COLLECTION",
    ),
)
@api_view(["GET", "POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP, HasErpOperation])
def period_collection(request):
    """GET: list periods (authoritative order). POST: create via service."""
    if request.method == "GET":
        periods = FiscalPeriod.objects.all()
        return Response(FiscalPeriodSerializer(periods, many=True).data)
    serializer = PeriodCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        period = create_period(user=request.user, **serializer.validated_data)
    except PeriodValidationError as exc:
        return _domain_error(exc)
    return Response(
        FiscalPeriodSerializer(period).data,
        status=http_status.HTTP_201_CREATED,
    )


def _get_period(pk):
    return get_object_or_404(FiscalPeriod, pk=pk)


def _lifecycle(request, pk, service):
    period = _get_period(pk)
    serializer = LifecycleReasonSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        updated = service(
            period, user=request.user,
            reason=serializer.validated_data["reason"],
        )
    except PeriodValidationError as exc:
        return _domain_error(exc)
    return Response(FiscalPeriodSerializer(updated).data)


@erp_operations(
    POST=OperationSpec(
        operation_id="fiscal.period.object.close",
        permission_key="fiscal.period.close",
        binding_kind="OBJECT",
        target_kind="FISCAL_PERIOD",
        target_source=TARGET_URL_KWARG,
        target_kwarg="pk",
    )
)
@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP, HasErpOperation])
def period_close(request, pk):
    """OPEN → CLOSED via ``close_period()`` (reason optional)."""
    return _lifecycle(request, pk, close_period)


@erp_operations(
    POST=OperationSpec(
        operation_id="fiscal.period.object.reopen",
        permission_key="fiscal.period.reopen",
        binding_kind="OBJECT",
        target_kind="FISCAL_PERIOD",
        target_source=TARGET_URL_KWARG,
        target_kwarg="pk",
    )
)
@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP, HasErpOperation])
def period_reopen(request, pk):
    """CLOSED → OPEN via ``reopen_period()`` (reason required by service)."""
    return _lifecycle(request, pk, reopen_period)


@erp_operations(
    POST=OperationSpec(
        operation_id="fiscal.period.object.lock",
        permission_key="fiscal.period.lock",
        binding_kind="OBJECT",
        target_kind="FISCAL_PERIOD",
        target_source=TARGET_URL_KWARG,
        target_kwarg="pk",
    )
)
@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP, HasErpOperation])
def period_lock(request, pk):
    """OPEN → LOCKED via ``lock_period()`` (reason optional)."""
    return _lifecycle(request, pk, lock_period)


@erp_operations(
    POST=OperationSpec(
        operation_id="fiscal.period.object.unlock",
        permission_key="fiscal.period.unlock",
        binding_kind="OBJECT",
        target_kind="FISCAL_PERIOD",
        target_source=TARGET_URL_KWARG,
        target_kwarg="pk",
    )
)
@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP, HasErpOperation])
def period_unlock(request, pk):
    """LOCKED → OPEN via ``unlock_period()`` (reason required by service)."""
    return _lifecycle(request, pk, unlock_period)
