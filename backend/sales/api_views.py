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
from currencies.models import Currency
from sales.models import Sale, SaleLine, WarehouseCheck, WarehouseCheckReversal
from sales.returns_services import (
    ReturnValidationError, create_refund, create_sales_return, reverse_refund,
    reverse_sales_return,
)
from sales.services import (
    SalesValidationError, cancel_warehouse_check, create_sale, finalize_sale,
    finalize_warehouse_check, prepare_warehouse_check,
)
from sales.models import Refund, SalesReturn
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
    except (SalesValidationError, ReturnValidationError, ValueError) as exc:
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
            idempotency_key=request.data.get("idempotency_key") or f"sale:{sale.pk}:journal",
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
    except (SalesValidationError, ValueError) as exc:
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


@api_view(["GET"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def sales_return_collection(request):
    queryset = SalesReturn.objects.select_related("sale_line__sale", "sale_line__product", "warehouse", "entitlement_currency").order_by("return_date", "document_number")
    return Response([{
        "id": row.pk, "document_number": row.document_number, "sale_id": row.sale_line.sale_id,
        "sale_line_id": row.sale_line_id, "product_id": row.sale_line.product_id,
        "warehouse_id": row.warehouse_id, "quantity": row.quantity, "return_date": row.return_date,
        "reason": row.reason, "status": row.status, "entitlement_amount": row.entitlement_amount,
        "entitlement_currency_id": row.entitlement_currency_id, "journal_entry_id": row.journal_entry_id,
        "created_at": row.created_at,
    } for row in queryset])


@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def sales_return_create(request):
    data = request.data
    try:
        line = get_object_or_404(SaleLine, pk=data.get("sale_line_id"))
        row = create_sales_return(
            sale_line=line, warehouse=data.get("warehouse_id"),
            quantity=data.get("quantity"), return_date=data.get("return_date"),
            reason=data.get("reason"), user=request.user,
            document_number=data.get("document_number"),
            idempotency_key=data.get("idempotency_key"),
            acknowledge_negative=data.get("acknowledge_negative", False),
        )
    except (SalesValidationError, ReturnValidationError, ValueError, TypeError) as exc:
        return _domain_error(exc)
    return Response({"id": row.pk, "document_number": row.document_number, "status": row.status,
                     "sale_line_id": row.sale_line_id, "warehouse_id": row.warehouse_id,
                     "quantity": row.quantity, "return_date": row.return_date,
                     "reason": row.reason, "entitlement_amount": row.entitlement_amount,
                     "entitlement_currency_id": row.entitlement_currency_id,
                     "journal_entry_id": row.journal_entry_id},
                    status=http_status.HTTP_201_CREATED)


@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def sales_return_reverse(request, pk):
    row = get_object_or_404(SalesReturn, pk=pk)
    try:
        reversed_row = reverse_sales_return(
            row, reversal_date=request.data.get("reversal_date"),
            reason=request.data.get("reason"), user=request.user,
            idempotency_key=request.data.get("idempotency_key"),
        )
    except (SalesValidationError, ReturnValidationError, ValueError, TypeError) as exc:
        return _domain_error(exc)
    return Response({"id": reversed_row.pk, "status": reversed_row.status})


@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def refund_create(request, return_id):
    sales_return = get_object_or_404(SalesReturn, pk=return_id)
    data = request.data
    try:
        currency = get_object_or_404(Currency, pk=data.get("refund_currency_id"))
        refund = create_refund(
            sales_return=sales_return, refund_date=data.get("refund_date"),
            refund_currency=currency, entitlement_amount=data.get("entitlement_amount"),
            rate=data.get("rate"), reason=data.get("reason", ""), user=request.user,
            document_number=data.get("document_number"), idempotency_key=data.get("idempotency_key"),
        )
    except (SalesValidationError, ReturnValidationError, ValueError, TypeError) as exc:
        return _domain_error(exc)
    return Response({"id": refund.pk, "document_number": refund.document_number, "status": refund.status,
                     "refund_date": refund.refund_date, "refund_currency_id": refund.refund_currency_id,
                     "refund_amount": refund.refund_amount, "entitlement_amount": refund.entitlement_amount,
                     "agreed_rate": refund.agreed_rate, "journal_entry_id": refund.journal_entry_id},
                    status=http_status.HTTP_201_CREATED)


@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def refund_reverse(request, pk):
    refund = get_object_or_404(Refund, pk=pk)
    try:
        reversed_refund = reverse_refund(
            refund, reason=request.data.get("reason"), user=request.user,
        )
    except (SalesValidationError, ReturnValidationError, ValueError, TypeError) as exc:
        return _domain_error(exc)
    return Response({"id": reversed_refund.pk, "status": reversed_refund.status})
