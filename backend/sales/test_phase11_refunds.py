from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from .returns_services import _refund_amount


class Phase11RefundMathTests(SimpleTestCase):
    def test_usd_entitlement_refunded_in_afn(self):
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        afn = SimpleNamespace(pk=2, is_base=True, code="AFN")
        self.assertEqual(_refund_amount(Decimal("2000.00"), usd, afn, Decimal("65")), Decimal("130000.00"))

    def test_afn_entitlement_refunded_in_usd(self):
        afn = SimpleNamespace(pk=2, is_base=True, code="AFN")
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        self.assertEqual(_refund_amount(Decimal("130000.00"), afn, usd, Decimal("65")), Decimal("2000.00"))

    def test_same_currency_refund_keeps_amount(self):
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        self.assertEqual(_refund_amount(Decimal("2000.00"), usd, usd, Decimal("1")), Decimal("2000.00"))
