from django.test import TestCase
from rest_framework.test import APIClient


class ApiErrorContractTests(TestCase):
    def test_unknown_route_uses_standard_error_shape(self):
        response = APIClient().get("/api/v1/health/missing/")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertIn("error", body)
        self.assertIn("code", body["error"])
        self.assertIn("message", body["error"])
