"""Remediation regression evidence; synthetic data only."""
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, SimpleTestCase
from django.conf import settings

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry, JournalLine
from categories.services import create_category
from currencies.models import Currency
from customer_custody.models import CustomerCustodyEvent, CustomerOwnershipEntitlement
from documents.models import NumberSequence
from inventory.models import StockMovement
from inventory.services import assign_warehouse_account, receive_stock
from inventory.stock import stock_for
from parties.services import create_party
from party_ledger.models import PartyLedgerAttribution
from products.services import create_product
from sales.models import Sale, SaleLine, SaleLineWarehouseAllocation, WarehouseCheck
from sales.services import create_sale, finalize_sale, prepare_warehouse_check, finalize_warehouse_check
from security.audit_chain import verify_audit_chain, AuditChainVerificationError
from security.backup_service import (BackupError, create_signed_checkpoint,
    verify_signed_checkpoint, encrypt_backup_file, create_audit_checkpoint_file)
from security.models import AuditEvent, AuditAction
from security.services import record_audit_event
from security.test_backup_service import StaticBackupKeyProvider
from security.test_support import AuditTriggerAwareTransactionTestCase
from uom.services import create_uom
from warehouses.services import create_warehouse
from core.models import IdempotencyRecord


class RemediationSalesTests(TestCase):
    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        category = create_category(name="FR category")
        self.unit = create_uom(name="FR unit")
        self.product = create_product(code="FR-SALE", name="FR product", name_fa="کالا",
                                      category=category, primary_uom=self.unit)
        self.customer = create_party(name="FR customer", is_customer=True)
        self.warehouse = create_warehouse(name="FR warehouse")
        assign_warehouse_account(warehouse=self.warehouse, account="1410")
        self.day = date(2026, 2, 1)
        receive_stock(product=self.product, warehouse=self.warehouse, quantity=10,
                      unit_cost="4", currency=self.afn, movement_date=self.day, reference="FR-RECEIPT")

    def _sale(self):
        return create_sale(customer=self.customer, sale_date=self.day, currency=self.afn,
                           channel="WHOLESALE", payment_mode="CREDIT",
                           lines=[{"product": self.product, "unit": self.unit, "quantity": 4,
                                   "unit_price": "10", "warehouse": self.warehouse}])

    def _state(self):
        return (
            tuple(model.objects.count() for model in (Sale, SaleLine, SaleLineWarehouseAllocation,
                  WarehouseCheck, JournalEntry, JournalLine, StockMovement, PartyLedgerAttribution,
                  CustomerOwnershipEntitlement, CustomerCustodyEvent, IdempotencyRecord)),
            list(NumberSequence.objects.order_by("pk").values()),
            verify_audit_chain(), stock_for(self.product, self.warehouse),
        )

    def _fail(self, call, entity, action):
        def reject(**kw):
            self.assertEqual(kw["entity"], entity)
            self.assertEqual(kw["action"], action)
            raise RuntimeError("synthetic final aggregate audit failure")
        before = self._state()
        with patch("sales.services.record_audit_event", side_effect=reject):
            with self.assertRaisesMessage(RuntimeError, "synthetic final aggregate audit failure"):
                call()
        self.assertEqual(self._state(), before)

    def test_draft_failure_rolls_back_number_and_lines(self):
        self._fail(self._sale, "Sale", AuditAction.CREATE)
        sale = self._sale()
        event = AuditEvent.objects.get(entity="Sale", entity_id=str(sale.pk), action=AuditAction.CREATE)
        self.assertEqual(event.new_state["status"], "DRAFT")
        self.assertEqual(len(event.new_state["lines"]), 1)
        self.assertEqual(event.new_state["allocations"][0]["quantity"], 4)
        self.assertTrue(verify_audit_chain()["valid"])

    def test_finalize_failure_reverts_revenue_cogs_stock_and_ownership(self):
        sale = self._sale()
        self._fail(lambda: finalize_sale(sale=sale), "Sale", AuditAction.POST)
        sale.refresh_from_db()
        self.assertEqual(sale.status, "DRAFT")
        finalize_sale(sale=sale)
        sale.refresh_from_db()
        self.assertEqual(sale.status, "FINALIZED")
        self.assertEqual(sale.journal_entry.total_debit, Decimal("40.00"))
        self.assertEqual(sale.journal_entry.total_credit, Decimal("40.00"))
        cogs = JournalEntry.objects.get(source_type="SALES_COGS")
        self.assertEqual(cogs.total_debit, Decimal("16.00"))
        self.assertEqual(cogs.total_credit, Decimal("16.00"))
        self.assertEqual(stock_for(self.product, self.warehouse), 6)
        before = self._state()
        finalize_sale(sale=sale)
        self.assertEqual(self._state(), before)
        event = AuditEvent.objects.get(entity="Sale", entity_id=str(sale.pk), action=AuditAction.POST)
        self.assertEqual(event.previous_state["status"], "DRAFT")
        self.assertEqual(event.new_state["status"], "FINALIZED")

    def test_check_create_and_release_failure_rolls_back_custody_without_duplicate_cogs(self):
        sale = self._sale()
        finalize_sale(sale=sale)
        def prepare():
            return prepare_warehouse_check(sale_line=sale.lines.get(), warehouse=self.warehouse,
                                           quantity=2, number="WC-FR-1")
        self._fail(prepare, "WarehouseCheck", AuditAction.CREATE)
        check = prepare()
        self._fail(lambda: finalize_warehouse_check(check=check), "WarehouseCheck", AuditAction.POST)
        check.refresh_from_db()
        self.assertEqual(check.status, "DRAFT")
        cogs_count = JournalEntry.objects.filter(source_type="SALES_COGS").count()
        finalize_warehouse_check(check=check)
        check.refresh_from_db()
        self.assertEqual(check.status, "FINALIZED")
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), cogs_count)
        self.assertEqual(stock_for(self.product, self.warehouse), 6)
        before = self._state()
        finalize_warehouse_check(check=check)
        self.assertEqual(self._state(), before)
        self.assertEqual(AuditEvent.objects.filter(entity="WarehouseCheck", entity_id=str(check.pk)).count(), 2)


class RemediationArtifactTests(SimpleTestCase):
    def test_signed_checkpoint_and_ciphertext_never_overwrite(self):
        provider = StaticBackupKeyProvider()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.json"
            create_signed_checkpoint({"event_count": 1}, checkpoint, provider=provider)
            original = checkpoint.read_bytes()
            with self.assertRaisesMessage(BackupError, "refusing to overwrite"):
                create_signed_checkpoint({"event_count": 2}, checkpoint, provider=provider)
            self.assertEqual(checkpoint.read_bytes(), original)
            self.assertEqual(verify_signed_checkpoint(checkpoint, provider=provider)["event_count"], 1)
            plain = root / "plain"
            plain.write_bytes(b"synthetic")
            encrypted = root / "backup.hbak"
            encrypt_backup_file(plain, encrypted, provider=provider)
            before = encrypted.read_bytes()
            # Simulate a concurrent winner after the initial existence check.
            with patch.object(Path, "exists", return_value=False):
                with self.assertRaisesMessage(BackupError, "refusing to overwrite"):
                    encrypt_backup_file(plain, encrypted, provider=provider)
            self.assertEqual(encrypted.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["backup.hbak", "checkpoint.json", "plain"])

    def test_verification_never_reads_private_signing_key(self):
        provider = StaticBackupKeyProvider()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            create_signed_checkpoint({"event_count": 1}, path, provider=provider)
            with patch.object(provider, "get_checkpoint_signing_private_key", side_effect=AssertionError("private key read")) as private:
                self.assertEqual(verify_signed_checkpoint(path, provider=provider)["event_count"], 1)
                private.assert_not_called()


class RemediationStandaloneCheckpointTests(AuditTriggerAwareTransactionTestCase):
    def test_standalone_destination_guard_and_collision_preserve_history(self):
        provider = StaticBackupKeyProvider()
        with transaction.atomic():
            record_audit_event(action=AuditAction.CREATE, entity="FRCheckpoint")
        initial = verify_audit_chain()
        with self.assertRaises(BackupError):
            create_audit_checkpoint_file(Path(settings.BASE_DIR) / "must-not-write.json", provider=provider)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            with patch("security.backup_service.assert_audit_trigger_schema",
                       side_effect=AuditChainVerificationError("synthetic missing guard")):
                with self.assertRaises(BackupError):
                    create_audit_checkpoint_file(path, provider=provider)
            self.assertFalse(path.exists())
            self.assertEqual(verify_audit_chain(), initial)
            create_audit_checkpoint_file(path, provider=provider)
            after = verify_audit_chain()
            original = path.read_bytes()
            self.assertEqual(after["event_count"], initial["event_count"] + 1)
            with self.assertRaisesMessage(BackupError, "refusing to overwrite"):
                create_audit_checkpoint_file(path, provider=provider)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(verify_audit_chain(), after)
