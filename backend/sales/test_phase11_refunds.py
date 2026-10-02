from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from .returns_services import (
    ReturnValidationError,
    _allocate_return_entitlement,
    _refund_amount,
)


class Phase11RefundMathTests(SimpleTestCase):
    def test_usd_entitlement_refunded_in_afn(self):
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        afn = SimpleNamespace(pk=2, is_base=True, code="AFN")
        self.assertEqual(
            _refund_amount(Decimal("2000.00"), usd, afn, Decimal("65")),
            Decimal("130000.00"),
        )

    def test_afn_entitlement_refunded_in_usd(self):
        afn = SimpleNamespace(pk=2, is_base=True, code="AFN")
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        self.assertEqual(
            _refund_amount(Decimal("130000.00"), afn, usd, Decimal("65")),
            Decimal("2000.00"),
        )

    def test_same_currency_refund_keeps_amount(self):
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        self.assertEqual(
            _refund_amount(Decimal("2000.00"), usd, usd, Decimal("1")),
            Decimal("2000.00"),
        )

    def test_partial_returns_allocate_exact_full_line_value_without_rounding_leak(self):
        total = Decimal("1.00")
        first = _allocate_return_entitlement(
            net_total=total, sale_quantity=3, returned_quantity=0,
            prior_amount=Decimal("0.00"), quantity=1,
        )
        second = _allocate_return_entitlement(
            net_total=total, sale_quantity=3, returned_quantity=1,
            prior_amount=first, quantity=1,
        )
        third = _allocate_return_entitlement(
            net_total=total, sale_quantity=3, returned_quantity=2,
            prior_amount=first + second, quantity=1,
        )
        self.assertEqual([first, second, third], [
            Decimal("0.33"), Decimal("0.33"), Decimal("0.34")
        ])
        self.assertEqual(first + second + third, total)

    def test_return_entitlement_rejects_quantity_above_remaining_line_quantity(self):
        with self.assertRaises(ReturnValidationError):
            _allocate_return_entitlement(
                net_total=Decimal("100.00"), sale_quantity=3,
                returned_quantity=2, prior_amount=Decimal("66.66"),
                quantity=2,
            )
