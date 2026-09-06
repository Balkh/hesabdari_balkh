from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class SecurityFoundationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="admin", password="Strong-test-password-123")
        self.client = APIClient()

    def test_protected_endpoint_rejects_anonymous_user(self):
        response = self.client.get("/api/v1/security/me/")
        self.assertEqual(response.status_code, 403)

    def test_authenticated_user_can_access_protected_endpoint(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/security/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "admin")
