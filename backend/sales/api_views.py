"""Authenticated REST API over the existing Sales domain services.

This layer deliberately contains no accounting or inventory calculations.
"""
import hashlib
import json
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from core.idempotency import IdempotencyRecord
from sales.models import Sale, SaleLine, WarehouseCheck
from sales.services import (
    SalesValidationError, cancel_warehouse_check, create_sale, finalize_sale,
    finalize_warehouse_check, prepare_warehouse_check,
)
from security.permissions import IsAuthenticatedForERP

from .api_serializers import (
    SaleCreateSerializer, SaleReadSerializer, WarehouseCheckCancelSerializer,
    WarehouseCheckCreateSerializer, WarehouseCheckFinalizeSerializer,
    WarehouseCheckReadSerializer,
)

_AUTH_CLASSES = [SessionAuthentication, BasicAuthentication]


def _domain_error(exc):
    return Response(
        {"error": {"code": "http_400", "message": str(exc)}},
        status=http_status.HTTP_400_BAD_REQUEST,
    )


def _sale_queryset():
    return Sale.objects.select_related("customer", "currency", "journal_entry", "created_by").prefetch_related(
        "lines__product", "lines__unit", "lines__transit_lot"
    ).order_by("sale_date", "document_number")


def _check_queryset():
    return WarehouseCheck.objects.select_related(
        "sale", "sale__customer", "sale_line__product", "warehouse",
        "stock_movement", "cogs_journal", "reversal",
    ).order_by("number")


def _canonical(value):
    if hasattr(value, "pk") and value.pk is not None:
        return {"id": value.pk}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _idempotent_create(*, key, operation, validated_data, model, create):
    """Atomically reserve a request key and replay only the exact same request."""
    fingerprint = hashlib.sha256(
        json.dumps(_canonical(validated_data), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = IdempotencyRecord.objects.filter(key=key).first()
    if existing:
        body = existing.response_body or {}
        if existing.operation != operation or body.get("fingerprint") != fingerprint:
            raise SalesValidationError("This idempotency key was used for a different operation or payload.")
        object_id = body.get("object_id")
        if object_id is None:
            raise SalesValidationError("The previous idempotent operation has no replayable result.")
        return model.objects.get(pk=object_id), True
    try:
        with transaction.atomic():
            record = IdempotencyRecord.objects.create(key=key, operation=operation)
            obj = create()
            record.response_body = {"fingerprint": fingerprint, "object_id": obj.pk}
            record.save(update_fields=["response_body"])
            return obj, False
    except IntegrityError:
        existing = IdempotencyRecord.objects.filter(key=key).first()
        if existing is None:
            raise
        body = existing.response_body or {}
        if existing.operation != operation or body.get("fingerprint") != fingerprint:
            raise SalesValidationError("This idempotency key was used for a different operation or payload.")
        object_id = body.get("object_id")
        if object_id is None:
            raise SalesValidationError("The previous idempotent operation has no replayable result.")
        return model.objects.get(pk=object_id), True


@api_view(["GET", "POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def sale_collection(request):
    if request.method == "GET":
        return Response(SaleReadSerializer(_sale_queryset(), many=True).data)
    serializer = SaleCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    key = data.pop("idempotency_key")
    rate = data.pop("exchange_rate", None)
    rate_date = data.pop("rate_date", None)
    try:
        sale, replayed = _idempotent_create(
            key=key, operation="sales.create", validated_data=serializer.validated_data,
            model=Sale,
            create=lambda: create_sale(
                user=request.user, rate=rate, rate_date=rate_date, **data,
            ),
        )
    except (SalesValidationError, ValueError, IntegrityError) as exc:
        return _domain_error(exc)
    sale = _sale_queryset().get(pk=sale.pk)
    return Response(
        SaleReadSerializer(sale).data,
        status=http_status.HTTP_200_OK if replayed else http_status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def sale_detail(request, pk):
    sale = get_object_or_404(_sale_queryset(), pk=pk)
    return Response(SaleReadSerializer(sale).data)


@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def sale_finalize(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    try:
        finalized = finalize_sale(
            sale=sale, user=request.user,
        )
    except (SalesValidationError, ValueError) as exc:
        return _domain_error(exc)
    return Response(SaleReadSerializer(_sale_queryset().get(pk=finalized.pk)).data)


@api_view(["GET", "POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def warehouse_check_collection(request):
    if request.method == "GET":
        return Response(WarehouseCheckReadSerializer(_check_queryset(), many=True).data)
    serializer = WarehouseCheckCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    key = data.pop("idempotency_key")
    try:
        check, replayed = _idempotent_create(
            key=key, operation="sales.warehouse-check.create",
            validated_data=serializer.validated_data, model=WarehouseCheck,
            create=lambda: prepare_warehouse_check(**data),
        )
    except (SalesValidationError, ValueError, IntegrityError) as exc:
        return _domain_error(exc)
    return Response(
        WarehouseCheckReadSerializer(_check_queryset().get(pk=check.pk)).data,
        status=http_status.HTTP_200_OK if replayed else http_status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def warehouse_check_detail(request, pk):
    check = get_object_or_404(_check_queryset(), pk=pk)
    return Response(WarehouseCheckReadSerializer(check).data)


@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def warehouse_check_finalize(request, pk):
    check = get_object_or_404(WarehouseCheck, pk=pk)
    serializer = WarehouseCheckFinalizeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    try:
        finalized = finalize_warehouse_check(check=check, user=request.user, **data)
    except (SalesValidationError, ValueError) as exc:
        return _domain_error(exc)
    return Response(WarehouseCheckReadSerializer(_check_queryset().get(pk=finalized.pk)).data)


@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def warehouse_check_cancel(request, pk):
    check = get_object_or_404(WarehouseCheck, pk=pk)
    serializer = WarehouseCheckCancelSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        reversal = cancel_warehouse_check(
            check=check, user=request.user, **serializer.validated_data,
        )
    except (SalesValidationError, ValueError) as exc:
        return _domain_error(exc)
    return Response({
        "id": reversal.pk, "warehouse_check_id": reversal.warehouse_check_id,
        "reversal_date": reversal.reversal_date, "reason": reversal.reason,
        "idempotency_key": reversal.idempotency_key, "created_at": reversal.created_at,
    })


