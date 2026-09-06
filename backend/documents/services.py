from django.db import transaction
from .models import NumberSequence


def next_document_number(document_type: str, jalali_year: int) -> str:
    """Generate a backend-owned number; caller must persist it with its document."""
    if not document_type or not document_type.isalnum():
        raise ValueError("Document type must be alphanumeric")
    if jalali_year < 1:
        raise ValueError("Jalali year must be positive")
    with transaction.atomic():
        sequence, _ = NumberSequence.objects.select_for_update().get_or_create(
            document_type=document_type.upper(),
            defaults={"jalali_year": jalali_year, "next_value": 1},
        )
        if sequence.jalali_year != jalali_year:
            sequence.jalali_year = jalali_year
            sequence.next_value = 1
        value = sequence.next_value
        sequence.next_value = value + 1
        sequence.save(update_fields=["jalali_year", "next_value", "updated_at"])
        return f"{sequence.document_type}-{jalali_year}-{value:05d}"
