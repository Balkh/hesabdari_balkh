"""Thin API contract for compensating landed-cost reversals."""
from rest_framework import serializers

from .models import LandedCostReversal


class LandedCostReversalCreateSerializer(serializers.Serializer):
    reversal_date = serializers.DateField(required=True)
    reason = serializers.CharField(required=True, allow_blank=False, max_length=500)
    idempotency_key = serializers.CharField(required=True, allow_blank=False, max_length=128)


class LandedCostReversalReadSerializer(serializers.ModelSerializer):
    adjustment_reversal_count = serializers.SerializerMethodField()

    class Meta:
        model = LandedCostReversal
        fields = [
            "id", "cost_document_id", "reversal_date", "reason",
            "journal_entry_id", "idempotency_key", "created_by_id",
            "created_at", "adjustment_reversal_count",
        ]
        read_only_fields = fields

    def get_adjustment_reversal_count(self, obj):
        return obj.adjustment_reversals.count()
