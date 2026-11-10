import unittest
from unittest.mock import patch

from security.mfa import (
    RECOVERY_CODE_COUNT,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    totp_code,
    verify_recovery_code,
    verify_totp,
)


class TOTPPrimitiveTests(unittest.TestCase):
    # RFC 6238 SHA-1 test vector: secret "12345678901234567890".
    SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

    def test_rfc6238_sha1_vector(self):
        self.assertEqual(totp_code(self.SECRET, timestamp=59), "287082")

    def test_current_and_adjacent_time_steps_are_accepted(self):
        instant = 1_700_000_000
        current = totp_code(self.SECRET, timestamp=instant)
        previous = totp_code(self.SECRET, timestamp=instant - 30)
        following = totp_code(self.SECRET, timestamp=instant + 30)
        self.assertTrue(verify_totp(self.SECRET, current, timestamp=instant))
        self.assertTrue(verify_totp(self.SECRET, previous, timestamp=instant))
        self.assertTrue(verify_totp(self.SECRET, following, timestamp=instant))

    def test_outside_window_and_malformed_codes_are_rejected(self):
        instant = 1_700_000_000
        too_old = totp_code(self.SECRET, timestamp=instant - 60)
        self.assertFalse(verify_totp(self.SECRET, too_old, timestamp=instant))
        for malformed in ("", "12345", "1234567", "12a456", None):
            self.assertFalse(verify_totp(self.SECRET, malformed, timestamp=instant))

    def test_generated_secret_is_high_entropy_base32(self):
        secret = generate_totp_secret()
        self.assertEqual(len(secret), 32)
        self.assertTrue(all(ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for ch in secret))

    def test_window_cannot_be_widened_beyond_owner_approval(self):
        with self.assertRaises(ValueError):
            verify_totp(self.SECRET, "000000", timestamp=59, valid_window=2)


class RecoveryCodePrimitiveTests(unittest.TestCase):
    def test_exactly_ten_unique_high_entropy_codes(self):
        codes = generate_recovery_codes()
        self.assertEqual(len(codes), RECOVERY_CODE_COUNT)
        self.assertEqual(len(set(codes)), RECOVERY_CODE_COUNT)
        self.assertTrue(all(len(code) == 16 for code in codes))

    def test_recovery_code_uses_salted_one_way_hash(self):
        code = generate_recovery_codes()[0]
        encoded = hash_recovery_code(code)
        self.assertNotEqual(encoded, code)
        self.assertTrue(verify_recovery_code(code, encoded))
        self.assertFalse(verify_recovery_code(code + "X", encoded))


if __name__ == "__main__":
    unittest.main()
