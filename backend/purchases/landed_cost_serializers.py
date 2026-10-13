"""Thin REST shapes for the late landed-cost domain services.

Write serializers validate wire format only. All accounting, allocation,
historical-rate and immutability rules remain in purchases.landed_cost_services.
"""
from decimal import Decimal

from rest_framework import serializers

from .models import (
    LandedCostAllocation, LandedCostAllocationMethod, LandedCostDocument,
)


class LandedCostAllocationReadSerializer(serializers.ModelSerializer):
    purchase_line_id = serializers.IntegerField(read_only=True)
    purchase_document_number = serializers.CharField(
        source="purchase_line.purchase.document_number", read_only=True,
    )
    product_id = serializers.IntegerField(source="purchase_line.product_id", read_only=True)
    product_code = serializers.CharField(source="purchase_line.product.code", read_only=True)
    product_name = serializers.CharField(source="purchase_line.product.name", read_only=True)
    quantity = serializers.IntegerField(source="purchase_line.quantity", read_only=True)

    class Meta:
        model = LandedCostAllocation
        fields = [
            "id", "purchase_line_id", "purchase_document_number",
            "product_id", "product_code", "product_name", "quantity",
            "method", "measured_weight_kg", "amount", "afn_amount",
        ]
        read_only_fields = fields


class LandedCostDocumentReadSerializer(serializers.ModelSerializer):
    payee_id = serializers.IntegerField(read_only=True)
    payee_name = serializers.CharField(source="payee.name", read_only=True)
    currency_id = serializers.IntegerField(read_only=True)
    currency_code = serializers.CharField(source="currency.code", read_only=True)
    allocations = LandedCostAllocationReadSerializer(many=True, read_only=True)

    class Meta:
        model = LandedCostDocument
        fields = [
            "id", "document_number", "payee_id", "payee_name",
            "cost_date", "currency_id", "currency_code", "amount",
            "exchange_rate", "rate_date", "afn_amount", "category",
            "description", "status", "journal_entry_id", "created_by_id",
            "created_at", "posted_at", "allocations",
        ]
        read_only_fields = fields


class LandedCostDraftCreateSerializer(serializers.Serializer):
    document_number = serializers.CharField(required=True, allow_blank=False, max_length=30)
    payee_id = serializers.IntegerField(required=True, min_value=1)
    cost_date = serializers.DateField(required=True)
    currency_id = serializers.IntegerField(required=True, min_value=1)
    amount = serializers.DecimalField(required=True, max_digits=20, decimal_places=2, min_value=Decimal("0.01"))
    exchange_rate = serializers.DecimalField(required=True, max_digits=20, decimal_places=4, min_value=Decimal("0.0001"))
    rate_date = serializers.DateField(required=True)
    category = serializers.CharField(required=True, allow_blank=False, max_length=40)
    description = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    purchase_line_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=True, allow_empty=False,
    )
    allocation_method = serializers.ChoiceField(
        choices=LandedCostAllocationMethod.choices,
        required=True,
    )
    idempotency_key = serializers.CharField(required=True, allow_blank=False, max_length=128)
