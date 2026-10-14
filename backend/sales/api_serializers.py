"""Thin REST serializers for the Sales domain.

Accounting, stock, ownership and custody rules stay in sales.services and
sales.returns_services; serializers only validate request shapes and render data.
"""
from rest_framework import serializers

from currencies.models import Currency
from goods_in_transit.models import GoodsInTransitLot
from parties.models import Party
from products.models import Product
from uom.models import UnitOfMeasure
from warehouses.models import Warehouse

from .models import Sale, SaleLine, WarehouseCheck, WarehouseCheckReversal


class SaleLineReadSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit_id = serializers.IntegerField(read_only=True)
    unit_name = serializers.CharField(source="unit.name", read_only=True)
    transit_lot_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = SaleLine
        fields = [
            "id", "product_id", "product_code", "product_name", "unit_id",
            "unit_name", "quantity", "unit_price", "discount", "line_total",
            "net_total", "transit_lot_id",
        ]
        read_only_fields = fields


class SaleReadSerializer(serializers.ModelSerializer):
    created_by_id = serializers.IntegerField(read_only=True, allow_null=True)
    customer_id = serializers.IntegerField(read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    currency_id = serializers.IntegerField(read_only=True)
    currency_code = serializers.CharField(source="currency.code", read_only=True)
    journal_entry_id = serializers.IntegerField(read_only=True, allow_null=True)
    lines = SaleLineReadSerializer(many=True, read_only=True)

    class Meta:
        model = Sale
        fields = [
            "id", "document_number", "customer_id", "customer_name", "sale_date",
            "currency_id", "currency_code", "exchange_rate", "rate_date",
            "sale_type", "channel", "payment_mode", "subtotal", "total_discount",
            "total", "status", "journal_entry_id", "created_by_id", "created_at",
            "finalized_at", "lines",
        ]
        read_only_fields = fields


class SaleLineCreateSerializer(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(
        source="product", queryset=Product.objects.filter(is_active=True)
    )
    unit_id = serializers.PrimaryKeyRelatedField(
        source="unit", queryset=UnitOfMeasure.objects.filter(is_active=True)
    )
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=20, decimal_places=4, min_value=0)
    discount = serializers.DecimalField(max_digits=20, decimal_places=2, min_value=0, required=False, default=0)
    transit_lot_id = serializers.PrimaryKeyRelatedField(
        source="transit_lot", queryset=GoodsInTransitLot.objects.all(), required=False, allow_null=True,
    )


class SaleCreateSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=128, allow_blank=False)
    customer_id = serializers.PrimaryKeyRelatedField(
        source="customer", queryset=Party.objects.filter(is_active=True, is_customer=True)
    )
    sale_date = serializers.DateField()
    currency_id = serializers.PrimaryKeyRelatedField(
        source="currency", queryset=Currency.objects.filter(is_active=True)
    )
    exchange_rate = serializers.DecimalField(
        max_digits=20, decimal_places=4, min_value=0, required=False, allow_null=True,
    )
    rate_date = serializers.DateField(required=False, allow_null=True)
    sale_type = serializers.ChoiceField(choices=("AVAILABLE", "FUTURE"), required=False, default="AVAILABLE")
    channel = serializers.ChoiceField(choices=("WHOLESALE", "RETAIL"))
    payment_mode = serializers.ChoiceField(choices=("CASH", "CREDIT"))
    document_number = serializers.CharField(max_length=30, required=False, allow_blank=False)
    lines = SaleLineCreateSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        rate = attrs.get("exchange_rate")
        rate_date = attrs.get("rate_date")
        if (rate is None) != (rate_date is None) and not attrs["currency"].is_base:
            raise serializers.ValidationError({"exchange_rate": "exchange_rate and rate_date must be supplied together."})
        if attrs["currency"].is_base and rate is not None and rate != 1:
            raise serializers.ValidationError({"exchange_rate": "Base currency rate must be 1.0000."})
        return attrs


class WarehouseCheckReadSerializer(serializers.ModelSerializer):
    sale_id = serializers.IntegerField(read_only=True)
    sale_document_number = serializers.CharField(source="sale.document_number", read_only=True)
    sale_line_id = serializers.IntegerField(read_only=True)
    product_id = serializers.IntegerField(source="sale_line.product_id", read_only=True)
    product_name = serializers.CharField(source="sale_line.product.name", read_only=True)
    customer_name = serializers.CharField(source="sale.customer.name", read_only=True)
    warehouse_id = serializers.IntegerField(read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    stock_movement_id = serializers.IntegerField(read_only=True, allow_null=True)
    cogs_journal_id = serializers.IntegerField(read_only=True, allow_null=True)
    is_cancelled = serializers.SerializerMethodField()

    class Meta:
        model = WarehouseCheck
        fields = [
            "id", "number", "sale_id", "sale_document_number", "sale_line_id",
            "product_id", "product_name", "customer_name", "warehouse_id",
            "warehouse_name", "quantity", "status", "stock_movement_id",
            "cogs_journal_id", "finalized_at", "created_at", "is_cancelled",
        ]
        read_only_fields = fields

    def get_is_cancelled(self, obj):
        return hasattr(obj, "reversal")


class WarehouseCheckCreateSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=128, allow_blank=False)
    sale_line_id = serializers.PrimaryKeyRelatedField(
        source="sale_line", queryset=SaleLine.objects.select_related("sale")
    )
    warehouse_id = serializers.PrimaryKeyRelatedField(
        source="warehouse", queryset=Warehouse.objects.filter(is_active=True)
    )
    quantity = serializers.IntegerField(min_value=1, required=False)
    number = serializers.CharField(max_length=30, required=False, allow_blank=False)


class WarehouseCheckFinalizeSerializer(serializers.Serializer):
    acknowledge_negative = serializers.BooleanField(required=False, default=False)
    temporary_unit_cost = serializers.DecimalField(
        max_digits=20, decimal_places=4, min_value=0, required=False, allow_null=True,
    )
    temporary_currency_id = serializers.PrimaryKeyRelatedField(
        source="temporary_currency", queryset=Currency.objects.filter(is_active=True),
        required=False, allow_null=True,
    )
    temporary_rate = serializers.DecimalField(
        max_digits=20, decimal_places=4, min_value=0, required=False, allow_null=True,
    )
    temporary_rate_date = serializers.DateField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=False)


class WarehouseCheckCancelSerializer(serializers.Serializer):
    reversal_date = serializers.DateField()
    reason = serializers.CharField(max_length=500, allow_blank=False)
    idempotency_key = serializers.CharField(max_length=128, allow_blank=False)
    confirm_not_delivered = serializers.BooleanField()
