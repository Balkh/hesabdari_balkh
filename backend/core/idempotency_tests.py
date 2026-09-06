from django.test import TestCase
from .idempotency import DuplicateOperationError, idempotent_operation
from .models import IdempotencyRecord


class IdempotencyTests(TestCase):
    def test_first_key_is_reserved(self):
        with idempotent_operation(key="sale-001", operation="sales.post") as record:
            self.assertEqual(record.operation, "sales.post")
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_duplicate_key_is_rejected(self):
        with idempotent_operation(key="payment-001", operation="payments.post"):
            pass
        with self.assertRaises(DuplicateOperationError):
            with idempotent_operation(key="payment-001", operation="payments.post"):
                pass

    def test_failed_atomic_operation_does_not_leave_reservation(self):
        try:
            with idempotent_operation(key="journal-001", operation="journal.post"):
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass
        self.assertFalse(IdempotencyRecord.objects.filter(key="journal-001").exists())
