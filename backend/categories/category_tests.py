"""Phase 4.1 — Category master tests.

Pins interpretation record U-2/R-1/R-9/R-11: flat identity, non-unique
names, no code, deactivation via UPDATE, no delete path. Frozen suites
untouched.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

from security.models import AuditAction, AuditEvent

from .models import Category
from .services import (
    CategoryValidationError,
    create_category,
    resolve_category,
    set_category_active,
    update_category,
)


class CategoryFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("c41user", password="x")

    def _make(self, name="Grocery", **kwargs):
        params = {"user": self.user}
        params.update(kwargs)
        return create_category(name=name, **params)


class CategoryCreationTests(CategoryFixture, TestCase):
    def test_create_valid_defaults(self):
        category = self._make()
        self.assertEqual(category.name, "Grocery")
        self.assertEqual(category.name_fa, "")
        self.assertTrue(category.is_active)
        self.assertIsNotNone(category.created_at)
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="Category",
            entity_id=str(category.pk),
        )
        self.assertEqual(event.user, self.user)
        self.assertIsNone(event.previous_state)
        self.assertEqual(event.new_state["name"], "Grocery")

    def test_create_with_farsi_name_and_inactive(self):
        category = self._make(name="Oil", name_fa="روغن", is_active=False)
        self.assertEqual(category.name_fa, "روغن")
        self.assertFalse(category.is_active)

    def test_blank_name_rejected_without_row_or_audit(self):
        with self.assertRaises(CategoryValidationError):
            self._make(name="   ")
        self.assertEqual(Category.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_non_text_name_rejected(self):
        with self.assertRaises(CategoryValidationError):
            self._make(name=123)
        self.assertEqual(Category.objects.count(), 0)

    def test_duplicate_names_allowed(self):
        first = self._make(name="Grocery")
        second = self._make(name="Grocery")
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(Category.objects.filter(name="Grocery").count(), 2)

    def test_names_trimmed(self):
        category = self._make(name="  Oil  ", name_fa="  روغن  ")
        self.assertEqual(category.name, "Oil")
        self.assertEqual(category.name_fa, "روغن")

    def test_user_none_allowed_with_null_actor(self):
        category = create_category(name="NoActor")
        event = AuditEvent.objects.get(entity="Category")
        self.assertIsNone(event.user)
        self.assertEqual(event.entity_id, str(category.pk))

    def test_anonymous_rejected(self):
        with self.assertRaises(CategoryValidationError):
            create_category(name="Ghost", user=AnonymousUser())
        self.assertEqual(Category.objects.count(), 0)

    def test_db_blank_guard(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(name="")
        self.assertEqual(Category.objects.count(), 0)


class CategoryUpdateTests(CategoryFixture, TestCase):
    def test_update_name_with_audit(self):
        category = self._make()
        updated = update_category(category, name="Food", user=self.user)
        self.assertEqual(updated.name, "Food")
        event = AuditEvent.objects.get(
            action=AuditAction.UPDATE, entity="Category"
        )
        self.assertEqual(event.previous_state["name"], "Grocery")
        self.assertEqual(event.new_state["name"], "Food")

    def test_update_noop_creates_no_audit(self):
        category = self._make()
        audits_before = AuditEvent.objects.count()
        update_category(category, name="Grocery", user=self.user)
        update_category(category, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_update_blank_name_rejected(self):
        category = self._make()
        with self.assertRaises(CategoryValidationError):
            update_category(category, name="  ", user=self.user)
        category.refresh_from_db()
        self.assertEqual(category.name, "Grocery")

    def test_deactivate_reactivate_with_reason(self):
        category = self._make()
        set_category_active(category, is_active=False, user=self.user,
                            reason="seasonal")
        category.refresh_from_db()
        self.assertFalse(category.is_active)
        event = AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="Category"
        ).order_by("id").last()
        self.assertEqual(event.reason, "seasonal")
        self.assertFalse(event.new_state["is_active"])
        set_category_active(category, is_active=True, user=self.user)
        category.refresh_from_db()
        self.assertTrue(category.is_active)

    def test_deactivate_noop_creates_no_audit(self):
        category = self._make()
        audits_before = AuditEvent.objects.count()
        set_category_active(category, is_active=True, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_non_text_reason_rejected(self):
        category = self._make()
        with self.assertRaises(CategoryValidationError):
            set_category_active(category, is_active=False, reason=7)
        category.refresh_from_db()
        self.assertTrue(category.is_active)

    def test_resolve_accepts_instance_or_pk(self):
        category = self._make()
        self.assertEqual(resolve_category(category).pk, category.pk)
        self.assertEqual(resolve_category(category.pk).pk, category.pk)
        with self.assertRaises(CategoryValidationError):
            resolve_category(424242)
        with self.assertRaises(CategoryValidationError):
            resolve_category("not-a-pk")
        with self.assertRaises(CategoryValidationError):
            resolve_category(Category(name="unsaved"))

    def test_audit_failure_leaves_no_orphan(self):
        with mock.patch("categories.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self._make(name="Orphan")
        self.assertEqual(Category.objects.count(), 0)
