from datetime import date, timezone
from django.test import SimpleTestCase
from .dates import gregorian_to_jalali, jalali_to_gregorian, utc_timestamp


class DateFoundationTests(SimpleTestCase):
    def test_gregorian_and_jalali_conversion(self):
        value = date(2026, 9, 6)
        jalali = gregorian_to_jalali(value)
        self.assertEqual(jalali_to_gregorian(jalali), value)

    def test_conversion_accepts_dash_separator(self):
        self.assertEqual(jalali_to_gregorian("1405-06-15"), date(2026, 9, 6))

    def test_utc_timestamp_is_aware_and_utc(self):
        result = utc_timestamp()
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.tzinfo, timezone.utc)
