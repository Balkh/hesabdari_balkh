from decimal import Decimal
from django.db import IntegrityError
from django.test import TestCase
from .models import Currency, ExchangeRate


class CurrencyFoundationTests(TestCase):
    def test_afn_and_usd_are_explicit_and_afn_is_base(self):
        afn = Currency.objects.create(code="AFN", name="Afghani", symbol="؋", is_base=True)
        usd = Currency.objects.create(code="USD", name="US Dollar", symbol="$", is_base=False)
        self.assertTrue(afn.is_base)
        self.assertFalse(usd.is_base)
        self.assertEqual(afn.decimal_places, 2)

    def test_only_one_base_currency_is_allowed(self):
        Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        with self.assertRaises(IntegrityError):
            Currency.objects.create(code="USD", name="US Dollar", is_base=True)

    def test_manual_directional_historical_rate(self):
        afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        usd = Currency.objects.create(code="USD", name="US Dollar")
        rate = ExchangeRate.objects.create(
            source_currency=usd,
            target_currency=afn,
            rate=Decimal("68.50000000"),
            effective_date="2026-09-06",
        )
        self.assertEqual(rate.rate, Decimal("68.50000000"))
        self.assertEqual(str(rate), "1 USD = 68.50000000 AFN")
