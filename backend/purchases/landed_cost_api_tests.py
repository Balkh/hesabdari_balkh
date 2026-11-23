from datetime import date
from decimal import Decimal
import base64

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry
from categories.services import create_category
from currencies.models import Currency
from inventory.models import WarehouseInventoryAccount
from parties.services import create_party
from products.services import create_product
from purchases.models import LandedCostDocument, LandedCostReversal, LandedCostStatus
from security.models import Role, UserRoleAssignment
from security.session_service import register_login_session
from purchases.services import create_purchase, post_purchase
from uom.services import create_uom
from warehouses.services import create_warehouse


class LandedCostApiTests(TestCase):
    COLLECTION = "/api/v1/purchases/landed-costs/"

    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.user = get_user_model().objects.create_user("landed-api-user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        category = create_category(name="Landed API Category", user=self.user)
        unit = create_uom(name="Landed API Unit", user=self.user)
        self.product = create_product(
            code="LC-API-PROD", name="Landed API Product", name_fa="محصول هزینه",
            category=category, primary_uom=unit, user=self.user,
        )
        self.supplier = create_party(name="Landed API Supplier", is_supplier=True, user=self.user)
        warehouse = create_warehouse(name="Landed API Warehouse", user=self.user)
        WarehouseInventoryAccount.objects.create(
            warehouse=warehouse, account_id=self._account_id("1410"),
        )
        self.day = date(2026, 1, 15)
        purchase = create_purchase(
            supplier=self.supplier, purchase_date=self.day, currency=self.afn,
            warehouse=warehouse,
            lines=[{"product": self.product, "quantity": 10, "unit_price": "12.00"}],
            user=self.user, document_number="PI-LC-API-001",
        )
        post_purchase(purchase=purchase, user=self.user)
        self.line = purchase.lines.get()

    def _account_id(self, code):
        from accounting.models import Account
        return Account.objects.get(code=code).pk

    def _payload(self, **overrides):
        payload = {
            "document_number": "LC-API-001",
            "payee_id": self.supplier.pk,
            "cost_date": self.day.isoformat(),
            "currency_id": self.afn.pk,
            "amount": "10.00",
            "exchange_rate": "1.0000",
            "rate_date": self.day.isoformat(),
            "category": "FREIGHT",
            "description": "Late direct freight",
            "purchase_line_ids": [self.line.pk],
            "allocation_method": "DIRECT",
            "idempotency_key": "lc-api-key-001",
        }
        payload.update(overrides)
        return payload

    def test_api_creates_posts_and_reads_landed_cost_without_mutation_routes(self):
        response = self.client.post(self.COLLECTION, self._payload(), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["status"], LandedCostStatus.DRAFT)
        self.assertEqual(body["allocations"][0]["purchase_line_id"], self.line.pk)
        document_id = body["id"]

        posted = self.client.post(f"{self.COLLECTION}{document_id}/post/", {}, format="json")
        self.assertEqual(posted.status_code, 200, posted.content)
        self.assertEqual(posted.json()["status"], LandedCostStatus.POSTED)
        self.assertTrue(posted.json()["journal_entry_id"])
        self.assertEqual(JournalEntry.objects.filter(source_type="LANDED_COST").count(), 1)

        detail = self.client.get(f"{self.COLLECTION}{document_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], LandedCostStatus.POSTED)
        self.assertEqual(self.client.get(self.COLLECTION).status_code, 200)
        self.assertEqual(self.client.patch(f"{self.COLLECTION}{document_id}/", {"amount": "99"}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(f"{self.COLLECTION}{document_id}/").status_code, 405)

    def test_api_idempotency_returns_existing_draft_and_rejects_changed_payload(self):
        first = self.client.post(self.COLLECTION, self._payload(), format="json")
        self.assertEqual(first.status_code, 201, first.content)
        retry = self.client.post(self.COLLECTION, self._payload(), format="json")
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(first.json()["id"], retry.json()["id"])
        changed = self.client.post(self.COLLECTION, self._payload(amount="11.00"), format="json")
        self.assertEqual(changed.status_code, 400)
        self.assertEqual(LandedCostDocument.objects.count(), 1)

    def test_api_requires_authentication_and_rejects_unknown_source_line(self):
        anonymous = APIClient()
        self.assertIn(anonymous.get(self.COLLECTION).status_code, (401, 403))
        bad = self.client.post(
            self.COLLECTION,
            self._payload(document_number="LC-API-BAD", idempotency_key="lc-api-bad", purchase_line_ids=[999999]),
            format="json",
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(LandedCostDocument.objects.count(), 0)


    def test_api_reverses_posted_landed_cost_with_compensating_journal(self):
        created = self.client.post(self.COLLECTION, self._payload(), format="json")
        self.assertEqual(created.status_code, 201, created.content)
        document_id = created.json()["id"]
        posted = self.client.post(f"{self.COLLECTION}{document_id}/post/", {}, format="json")
        self.assertEqual(posted.status_code, 200, posted.content)
        self.assertFalse(posted.json()["is_reversed"])

        payload = {
            "reversal_date": self.day.isoformat(),
            "reason": "Carrier cancelled the freight invoice",
            "idempotency_key": "lc-api-reversal-001",
        }
        reversed_response = self.client.post(
            f"{self.COLLECTION}{document_id}/reverse/", payload, format="json",
        )
        self.assertEqual(reversed_response.status_code, 201, reversed_response.content)
        reversal_body = reversed_response.json()
        self.assertEqual(reversal_body["cost_document_id"], document_id)
        self.assertEqual(reversal_body["adjustment_reversal_count"], 0)
        self.assertTrue(reversal_body["journal_entry_id"])
        self.assertEqual(LandedCostReversal.objects.count(), 1)

        detail = self.client.get(f"{self.COLLECTION}{document_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.json()["is_reversed"])
        self.assertEqual(detail.json()["reversal_date"], self.day.isoformat())
        self.assertEqual(detail.json()["status"], LandedCostStatus.POSTED)

        retry = self.client.post(
            f"{self.COLLECTION}{document_id}/reverse/", payload, format="json",
        )
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json()["id"], reversal_body["id"])
        repost = self.client.post(f"{self.COLLECTION}{document_id}/post/", {}, format="json")
        self.assertEqual(repost.status_code, 400)


    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_accountant_can_post_landed_cost_but_cannot_reverse_it(self):
        accountant = Role.objects.get(code="ACCOUNTANT")
        UserRoleAssignment.objects.create(user=self.user, role=accountant)

        # Switch from the domain-test force-auth fixture to a real registered
        # Django session so the operation resolver exercises R2 + W0-2C.
        self.client.force_authenticate(user=None)
        self.assertTrue(self.client.login(username=self.user.username, password="x"))
        register_login_session(self.user, self.client.session.session_key)

        created = self.client.post(self.COLLECTION, self._payload(), format="json")
        self.assertEqual(created.status_code, 201, created.content)
        document_id = created.json()["id"]

        posted = self.client.post(
            f"{self.COLLECTION}{document_id}/post/", {}, format="json"
        )
        self.assertEqual(posted.status_code, 200, posted.content)
        self.assertEqual(posted.json()["status"], LandedCostStatus.POSTED)

        denied = self.client.post(
            f"{self.COLLECTION}{document_id}/reverse/",
            {
                "reversal_date": self.day.isoformat(),
                "reason": "Accountant must not reverse this document",
                "idempotency_key": "lc-api-accountant-reverse-denied",
            },
            format="json",
        )
        self.assertEqual(denied.status_code, 403, denied.content)
        self.assertEqual(LandedCostReversal.objects.count(), 0)
        document = LandedCostDocument.objects.get(pk=document_id)
        self.assertIsNone(document.reversal_id)

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_basic_auth_compatibility_allows_granted_landed_cost_post_without_registry_session(self):
        accountant = Role.objects.get(code="ACCOUNTANT")
        UserRoleAssignment.objects.create(user=self.user, role=accountant)

        token = base64.b64encode(b"landed-api-user:x").decode("ascii")
        basic = APIClient()
        basic.credentials(HTTP_AUTHORIZATION=f"Basic {token}")

        created = basic.post(
            self.COLLECTION,
            self._payload(
                document_number="LC-API-BASIC-001",
                idempotency_key="lc-api-basic-key-001",
            ),
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        document_id = created.json()["id"]

        posted = basic.post(
            f"{self.COLLECTION}{document_id}/post/", {}, format="json"
        )
        self.assertEqual(posted.status_code, 200, posted.content)
        self.assertEqual(posted.json()["status"], LandedCostStatus.POSTED)

        # This pins the currently retained Batch 2/3 BasicAuthentication
        # compatibility path: it does not create a registry-managed session.
        from security.mfa_models import SecurityLoginSession
        self.assertEqual(SecurityLoginSession.objects.filter(user=self.user).count(), 0)
