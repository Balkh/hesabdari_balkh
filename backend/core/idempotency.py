from contextlib import contextmanager
from django.db import IntegrityError, transaction
from .models import IdempotencyRecord


class DuplicateOperationError(RuntimeError):
    pass


@contextmanager
def idempotent_operation(*, key: str, operation: str):
    """Reserve a critical operation key for the duration of one atomic operation."""
    if not key or len(key) > 128:
        raise ValueError("A valid idempotency key is required")
    try:
        with transaction.atomic():
            record = IdempotencyRecord.objects.create(key=key, operation=operation)
            yield record
    except IntegrityError as exc:
        raise DuplicateOperationError("This operation has already been submitted") from exc
