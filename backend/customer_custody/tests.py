from datetime import date

from django.test import TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import PostedImmutabilityError
from categories.services import create_category
from currencies.models import Currency
from customer_custody.models import CustomerCustodyEvent, CustomerOwnershipEntitlement, CustodyEventType
from customer_custody.services import (
    CustomerCustodyValidationError,
    create_ownership_entitlement,
    custody_balance,
    place_customer_custody,
    release_customer_custody,
)
from parties.services import create_party
from products.services import create_product
from uom.services import create_uom
from warehouses.services import create_warehouse
from sales.models import PaymentMode, SalesChannel
from sales.services import create_sale, finalize_sale


class CustomerCustodyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()

    def setUp(self):
        category = create_category(name="Custody Category")
        unit = create_uom(name="Custody Unit")
        self.product = create_product(code="CUST-1", name="Custody Product", category=category, primary_uom=unit)
        self.customer = create_party(name="Custody Customer", is_customer=True)
        self.warehouse = create_warehouse(name="Custody Warehouse")
        self.day = date(2026, 10, 1)
        self.sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            document_number="SI-CUST-1",
            lines=[{"product": self.product, "unit": unit, "quantity": 100, "unit_price": "10"}],
        )

    def test_finalized_sale_creates_one_immutable_ownership_entitlement(self):
        finalize_sale(sale=self.sale)
        entitlement = CustomerOwnershipEntitlement.objects.get()
        self.assertEqual(entitlement.quantity, 100)
        self.assertEqual(entitlement.customer, self.customer)
        self.assertEqual(entitlement.product, self.product)
        self.assertEqual(entitlement.ownership_date, self.day)
        self.assertRaises(PostedImmutabilityError, entitlement.save)
        self.assertRaises(PostedImmutabilityError, entitlement.delete)

    def test_ownership_is_not_created_for_draft_sale(self):
        self.assertEqual(CustomerOwnershipEntitlement.objects.count(), 0)

    def test_partial_multi_warehouse_custody_and_release(self):
        finalize_sale(sale=self.sale)
        entitlement = CustomerOwnershipEntitlement.objects.get()
        second = create_warehouse(name="Custody Warehouse 2")
        place_customer_custody(
            entitlement=entitlement, warehouse=self.warehouse, quantity=60,
            event_date=self.day, reference="CUST-PLACE-1", idempotency_key="cust-place-1",
        )
        place_customer_custody(
            entitlement=entitlement, warehouse=second, quantity=40,
            event_date=self.day, reference="CUST-PLACE-2", idempotency_key="cust-place-2",
        )
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 60)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=second), 40)
        release_customer_custody(
            entitlement=entitlement, warehouse=self.warehouse, quantity=20,
            event_date=self.day, reference="WC-1", idempotency_key="cust-release-1",
        )
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 40)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=second), 40)

    def test_custody_cannot_exceed_owned_quantity(self):
        finalize_sale(sale=self.sale)
        entitlement = CustomerOwnershipEntitlement.objects.get()
        place_customer_custody(
            entitlement=entitlement, warehouse=self.warehouse, quantity=100,
            event_date=self.day, reference="CUST-PLACE-1", idempotency_key="cust-place-3",
        )
        with self.assertRaises(CustomerCustodyValidationError):
            place_customer_custody(
                entitlement=entitlement, warehouse=self.warehouse, quantity=1,
                event_date=self.day, reference="CUST-PLACE-2", idempotency_key="cust-place-4",
            )

    def test_release_cannot_exceed_warehouse_custody(self):
        finalize_sale(sale=self.sale)
        entitlement = CustomerOwnershipEntitlement.objects.get()
        place_customer_custody(
            entitlement=entitlement, warehouse=self.warehouse, quantity=40,
            event_date=self.day, reference="CUST-PLACE-1", idempotency_key="cust-place-5",
        )
        with self.assertRaises(CustomerCustodyValidationError):
            release_customer_custody(
                entitlement=entitlement, warehouse=self.warehouse, quantity=41,
                event_date=self.day, reference="WC-OVER", idempotency_key="cust-release-over",
            )

    def test_release_is_immutable_and_idempotent(self):
        finalize_sale(sale=self.sale)
        entitlement = CustomerOwnershipEntitlement.objects.get()
        place_customer_custody(
            entitlement=entitlement, warehouse=self.warehouse, quantity=20,
            event_date=self.day, reference="CUST-PLACE-1", idempotency_key="cust-place-6",
        )
        event = release_customer_custody(
            entitlement=entitlement, warehouse=self.warehouse, quantity=10,
            event_date=self.day, reference="WC-IDEM", idempotency_key="cust-release-idem",
        )
        self.assertRaises(PostedImmutabilityError, event.save)
        self.assertRaises(PostedImmutabilityError, event.delete)
        retry = release_customer_custody(
            entitlement=entitlement, warehouse=self.warehouse, quantity=10,
            event_date=self.day, reference="WC-IDEM", idempotency_key="cust-release-idem",
        )
        self.assertEqual(event.pk, retry.pk)
        self.assertEqual(CustomerCustodyEvent.objects.filter(event_type=CustodyEventType.RELEASED).count(), 1)
