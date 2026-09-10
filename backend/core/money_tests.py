"""Stage 2.2 — money/rounding golden tests (Phase 0 §3.11–3.12).

Vectors marked HALF_UP also discriminate against banker's rounding and
truncation: the expected value differs under those methods.
"""

from decimal import Decimal, InvalidOperation

from django.test import SimpleTestCase

from .money import (
    cogs,
    format_rate,
    fx_equivalent,
    line_total,
    normalize_rate,
    quantize_half_up,
    to_decimal,
)


class RoundingGoldenTests(SimpleTestCase):
    def test_line_total_vectors(self):
        vectors = [
            (("2", "10.005"), Decimal("20.01")),
            (("1", "2.345"), Decimal("2.35")),  # HALF_UP (banker's: 2.34)
            (("1", "2.325"), Decimal("2.33")),  # HALF_UP (banker's: 2.32)
            (("2.5", "10.00"), Decimal("25.00")),
            (("3", "0.005"), Decimal("0.02")),  # 0.015 -> 0.02
            ((2, 3), Decimal("6.00")),
            (("0", "99.99"), Decimal("0.00")),
        ]
        for (qty, price), expected in vectors:
            with self.subTest(qty=qty, price=price):
                self.assertEqual(line_total(qty, price), expected)

    def test_cogs_vectors(self):
        vectors = [
            (("2", "1.2325"), Decimal("2.47")),  # 2.465 -> 2.47 (banker's: 2.46)
            (("1", "10.004"), Decimal("10.00")),
            (("5", "2.00"), Decimal("10.00")),
            (("1", "0.005"), Decimal("0.01")),
        ]
        for (qty, avco), expected in vectors:
            with self.subTest(qty=qty, avco=avco):
                self.assertEqual(cogs(qty, avco), expected)

    def test_fx_equivalent_vectors(self):
        vectors = [
            (("1000", "70"), Decimal("70000.00")),  # contract §1.12 example
            (("1", "70.005"), Decimal("70.01")),  # HALF_UP (banker's: 70.00)
            (("100", "68.5"), Decimal("6850.00")),
            (("250.50", "70.25"), Decimal("17597.63")),  # 17597.625 (banker's: .62)
        ]
        for (amount, rate), expected in vectors:
            with self.subTest(amount=amount, rate=rate):
                self.assertEqual(fx_equivalent(amount, rate), expected)

    def test_rate_precision_is_4(self):
        self.assertEqual(normalize_rate("70"), Decimal("70.0000"))
        self.assertEqual(normalize_rate("70.00005"), Decimal("70.0001"))  # 0.5-up at 4dp
        self.assertEqual(normalize_rate("70.00004"), Decimal("70.0000"))
        self.assertEqual(format_rate("70"), "70.0000")
        self.assertEqual(format_rate("68.5"), "68.5000")
        self.assertEqual(format_rate(70), "70.0000")

    def test_quantize_half_up_direct(self):
        self.assertEqual(quantize_half_up("1.005", 2), Decimal("1.01"))
        self.assertEqual(quantize_half_up("1.004", 2), Decimal("1.00"))

    def test_float_bool_and_garbage_rejected(self):
        for fn, args in [
            (line_total, (1.1, 2)),
            (cogs, (1, 2.5)),
            (fx_equivalent, (1.0, 70)),
            (normalize_rate, (70.5,)),
            (to_decimal, (True,)),
        ]:
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(TypeError):
                    fn(*args)
        with self.assertRaises(InvalidOperation):
            to_decimal("abc")
