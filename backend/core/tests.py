from django.test import TestCase
from rest_framework.test import APIClient


class HealthCheckTests(TestCase):
    def test_health_check_reports_service_and_database(self):
        response = APIClient().get("/api/v1/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["database"], "ok")

from datetime import date, timezone
from .dates import gregorian_to_jalali, jalali_to_gregorian, utc_timestamp


class DateFoundationTests(TestCase):
    def test_gregorian_and_jalali_conversion(self):
        value = date(2026, 9, 6)
        jalali = gregorian_to_jalali(value)
        self.assertEqual(jalali_to_gregorian(jalali), value)

    def test_utc_timestamp_is_aware_and_utc(self):
        result = utc_timestamp()
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.tzinfo, timezone.utc)

class ApiErrorContractTests(TestCase):
    def test_unknown_route_uses_standard_error_shape(self):
        response = APIClient().get("/api/v1/health/missing/")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertIn("error", body)
        self.assertIn("code", body["error"])
        self.assertIn("message", body["error"])
