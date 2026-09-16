"""Thin REST serializers over the frozen fiscal-period domain (Phase 3.2).

Strict split: serializers validate SHAPE ONLY (field presence and wire
types). Every business decision — range validity, overlap, transitions,
authorization, reason, close validation — is made by
``fiscal_periods.services``, the single source of truth. In particular,
the write serializers are plain ``serializers.Serializer`` (never bound
to the model), so no request can construct or mutate a period except
through the audited lifecycle services.
"""

from rest_framework import serializers

from core.dates import gregorian_to_jalali

from .models import FiscalPeriod


class FiscalPeriodSerializer(serializers.ModelSerializer):
    """Authoritative read shape, plus backend-computed Jalali display dates.

    Jalali strings come from the single ``core.dates`` engine so no client
    ever needs its own converter. Fully read-only: there is no write path
    through this serializer.
    """

    start_date_jalali = serializers.SerializerMethodField()
    end_date_jalali = serializers.SerializerMethodField()

    class Meta:
        model = FiscalPeriod
        fields = [
            "id", "name", "start_date", "end_date", "status",
            "created_at", "closed_at",
            "start_date_jalali", "end_date_jalali",
        ]
        read_only_fields = fields

    def get_start_date_jalali(self, obj):
        return gregorian_to_jalali(obj.start_date)

    def get_end_date_jalali(self, obj):
        return gregorian_to_jalali(obj.end_date)


class PeriodCreateSerializer(serializers.Serializer):
    """Creation input shape. Values pass through to ``create_period()``,
    which decides range validity, overlap, naming and audit."""

    name = serializers.CharField(required=True, allow_blank=True, max_length=200)
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)


class LifecycleReasonSerializer(serializers.Serializer):
    """Lifecycle input shape. The reason passes through as-given (default
    empty); whether a reason is REQUIRED is decided solely by the service
    (mandatory for reopen/unlock, optional for close/lock)."""

    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
