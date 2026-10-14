from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounting.coa import seed_chart_of_accounts
from currencies.models import Currency
from inventory.services import assign_warehouse_account, receive_stock
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from categories.services import create_category
from uom.services import create_uom
from warehouses.services import create_warehouse

from sales.models import Sale, SaleStatus, WarehouseCheck
from sales.services import SalesValidationError


class SalesApiTests(TestCase):
    SALES_URL = "/api/v1/sales/"
    CHECKS_URL = "/api/v1/sales/warehouse-checks/"

    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.user = get_user_model().objects.create_user("sales-api-user", password="test")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        category = create_category(name="Sales API Category", user=self.user)
        self.unit = create_uom(name="Sales API Unit", user=self.user)
        self.product = create_product(
            code="SALE-API-1", name="Sales API Product", name_fa="محصول فروش",
            category=category, primary_uom=self.unit, user=self.user,
        )
        self.customer = create_party(name="Sales API Customer", is_customer=True, user=self.user)
        self.warehouse = create_warehouse(name="Sales API Warehouse", user=self.user)
        assign_warehouse_account(warehouse=self.warehouse, account="1410")

    def payload(self, key="sale-api-key", quantity=5):
        return {
            "idempotency_key": key,
            "customer_id": self.customer.pk,
            "sale_date": "2026-01-10",
            "currency_id": self.afn.pk,
            "channel": "WHOLESALE",
            "payment_mode": "CREDIT",
            "lines": [{
                "product_id": self.product.pk, "unit_id": self.unit.pk,
                "quantity": quantity, "unit_price": "10.0000", "discount": "0.00",
            }],
        }

    def test_create_sale_is_authenticated_and_idempotent_for_same_payload(self):
        self.client.force_authenticate(user=None)
        denied = self.client.post(self.SALES_URL, self.payload(), format="json")
        self.assertIn(denied.status_code, (401, 403))

        self.client.force_authenticate(user=self.user)
        first = self.client.post(self.SALES_URL, self.payload(), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(self.SALES_URL, self.payload(), format="json")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(first.data["status"], SaleStatus.DRAFT)
        self.assertEqual(first.data["total"], "50.00")

    def test_idempotency_key_rejects_different_payload(self):
        first = self.client.post(self.SALES_URL, self.payload(quantity=5), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(self.SALES_URL, self.payload(quantity=6), format="json")
        self.assertEqual(second.status_code, 400, second.data)
        self.assertEqual(Sale.objects.count(), 1)

    def test_sale_finalize_and_warehouse_check_are_separate_actions(self):
        created = self.client.post(self.SALES_URL, self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        sale_id = created.data["id"]
        line_id = created.data["lines"][0]["id"]

        finalized = self.client.post(f"{self.SALES_URL}{sale_id}/finalize/", {}, format="json")
        self.assertEqual(finalized.status_code, 200, finalized.data)
        self.assertEqual(finalized.data["status"], SaleStatus.FINALIZED)
        self.assertIsNotNone(finalized.data["journal_entry_id"])
        self.assertEqual(finalized.data["lines"][0]["quantity"], 5)

        check_payload = {
            "idempotency_key": "sales-api-check-key",
            "sale_line_id": line_id, "warehouse_id": self.warehouse.pk, "quantity": 2,
        }
        check_response = self.client.post(self.CHECKS_URL, check_payload, format="json")
        self.assertEqual(check_response.status_code, 201, check_response.data)
        check_id = check_response.data["id"]
        self.assertEqual(check_response.data["status"], "DRAFT")

        repeated = self.client.post(self.CHECKS_URL, check_payload, format="json")
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data["id"], check_id)
        self.assertEqual(WarehouseCheck.objects.count(), 1)

        released = self.client.post(
            f"{self.CHECKS_URL}{check_id}/finalize/",
            {"acknowledge_negative": True, "temporary_unit_cost": "4.0000"},
            format="json",
        )
        self.assertEqual(released.status_code, 200, released.data)
        self.assertEqual(released.data["status"], "FINALIZED")
        self.assertIsNotNone(released.data["stock_movement_id"])
        self.assertIsNotNone(released.data["cogs_journal_id"])

    def test_warehouse_check_cannot_be_created_before_sale_finalization(self):
        created = self.client.post(self.SALES_URL, self.payload(), format="json")
        line_id = created.data["lines"][0]["id"]
        response = self.client.post(self.CHECKS_URL, {
            "idempotency_key": "draft-sale-check-key",
            "sale_line_id": line_id, "warehouse_id": self.warehouse.pk, "quantity": 1,
        }, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(WarehouseCheck.objects.count(), 0)

    def test_pre_delivery_cancel_endpoint_requires_confirmation_and_is_idempotent(self):
        created = self.client.post(self.SALES_URL, self.payload(key="sale-cancel-api"), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        sale_id = created.data["id"]
        line_id = created.data["lines"][0]["id"]
        finalized = self.client.post(f"{self.SALES_URL}{sale_id}/finalize/", {}, format="json")
        self.assertEqual(finalized.status_code, 200, finalized.data)

        receive_stock(
            product=self.product, warehouse=self.warehouse, quantity=5,
            unit_cost="4", currency=self.afn, movement_date=date(2026, 1, 10),
            reference="RCPT-SALES-API-CANCEL",
        )
        created_check = self.client.post(self.CHECKS_URL, {
            "idempotency_key": "check-cancel-api",
            "sale_line_id": line_id, "warehouse_id": self.warehouse.pk, "quantity": 5,
        }, format="json")
        self.assertEqual(created_check.status_code, 201, created_check.data)
        check_id = created_check.data["id"]
        finalized_check = self.client.post(
            f"{self.CHECKS_URL}{check_id}/finalize/", {}, format="json",
        )
        self.assertEqual(finalized_check.status_code, 200, finalized_check.data)
        self.assertEqual(stock_for(self.product, self.warehouse), 0)

        missing_confirmation = self.client.post(
            f"{self.CHECKS_URL}{check_id}/cancel/",
            {"reversal_date": "2026-01-11", "reason": "Not delivered",
             "idempotency_key": "check-cancel-api-key"},
            format="json",
        )
        self.assertEqual(missing_confirmation.status_code, 400, missing_confirmation.data)

        payload = {
            "reversal_date": "2026-01-11",
            "reason": "Goods did not physically leave the warehouse",
            "idempotency_key": "check-cancel-api-key",
            "confirm_not_delivered": True,
        }
        first = self.client.post(f"{self.CHECKS_URL}{check_id}/cancel/", payload, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        second = self.client.post(f"{self.CHECKS_URL}{check_id}/cancel/", payload, format="json")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        detail = self.client.get(f"{self.CHECKS_URL}{check_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertTrue(detail.data["is_cancelled"])
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
