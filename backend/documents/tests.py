from django.test import TestCase
from .services import next_document_number


class NumberingTests(TestCase):
    def test_numbers_are_backend_owned_and_sequential(self):
        self.assertEqual(next_document_number("si", 1405), "SI-1405-00001")
        self.assertEqual(next_document_number("SI", 1405), "SI-1405-00002")

    def test_new_jalali_year_restarts_sequence(self):
        next_document_number("PI", 1405)
        self.assertEqual(next_document_number("PI", 1406), "PI-1406-00001")

    def test_invalid_type_and_year_are_rejected(self):
        with self.assertRaises(ValueError):
            next_document_number("SI-", 1405)
        with self.assertRaises(ValueError):
            next_document_number("SI", 0)
