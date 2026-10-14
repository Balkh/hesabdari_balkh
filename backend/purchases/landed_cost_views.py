"""Operational API over the frozen landed-cost domain services.

No business/accounting rules are implemented in this layer. Posted documents
are read-only except for the explicit POST /post/ lifecycle action.
"""
from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from currencies.models import Currency
from parties.models import Party
from security.permissions import IsAuthenticatedForERP

from .models import LandedCostDocument, LandedCostReversal
from .landed_cost_serializers import LandedCostDocumentReadSerializer, LandedCostDraftCreateSerializer
from .landed_cost_reversal_serializers import (
    LandedCostReversalCreateSerializer, LandedCostReversalReadSerializer,
)
from .landed_cost_services import (
    LandedCostPostingError, LandedCostValidationError,
    create_landed_cost_draft, post_landed_cost,
)
from .landed_cost_reversal import reverse_landed_cost

_AUTH_CLASSES = [SessionAuthentication, BasicAuthentication]


def _domain_error(exc):
    return Response(
        {"error": {"code": "http_400", "message": str(exc)}},
        status=http_status.HTTP_400_BAD_REQUEST,
    )


def _document_queryset():
    return LandedCostDocument.objects.select_related(
        "payee", "currency", "journal_entry", "reversal",
    ).prefetch_related(
        "allocations__purchase_line__purchase",
        "allocations__purchase_line__product",
    ).order_by("cost_date", "document_number")


@api_view(["GET", "POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def landed_cost_collection(request):
    if request.method == "GET":
        return Response(LandedCostDocumentReadSerializer(
            _document_queryset(), many=True,
        ).data)
    serializer = LandedCostDraftCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    payee = get_object_or_404(Party, pk=data.pop("payee_id"))
    currency = get_object_or_404(Currency, pk=data.pop("currency_id"))
    key = data["idempotency_key"]
    existed = LandedCostDocument.objects.filter(idempotency_key=key).exists()
    try:
        document = create_landed_cost_draft(
            payee=payee, currency=currency, user=request.user, **data,
        )
    except (LandedCostValidationError, LandedCostPostingError, ValueError) as exc:
        return _domain_error(exc)
    status_code = http_status.HTTP_200_OK if existed else http_status.HTTP_201_CREATED
    return Response(
        LandedCostDocumentReadSerializer(document).data,
        status=status_code,
    )


@api_view(["GET"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def landed_cost_detail(request, pk):
    document = get_object_or_404(_document_queryset(), pk=pk)
    return Response(LandedCostDocumentReadSerializer(document).data)


@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def landed_cost_post(request, pk):
    document = get_object_or_404(LandedCostDocument, pk=pk)
    try:
        posted = post_landed_cost(cost_document=document, user=request.user)
    except (LandedCostValidationError, LandedCostPostingError, ValueError) as exc:
        return _domain_error(exc)
    return Response(LandedCostDocumentReadSerializer(posted).data)



@api_view(["POST"])
@authentication_classes(_AUTH_CLASSES)
@permission_classes([IsAuthenticatedForERP])
def landed_cost_reverse(request, pk):
    document = get_object_or_404(LandedCostDocument, pk=pk)
    serializer = LandedCostReversalCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    key = data["idempotency_key"]
    existed = LandedCostReversal.objects.filter(idempotency_key=key).exists()
    try:
        reversal = reverse_landed_cost(
            cost_document=document, user=request.user, **data,
        )
    except (LandedCostValidationError, LandedCostPostingError, ValueError) as exc:
        return _domain_error(exc)
    return Response(
        LandedCostReversalReadSerializer(reversal).data,
        status=http_status.HTTP_200_OK if existed else http_status.HTTP_201_CREATED,
    )
