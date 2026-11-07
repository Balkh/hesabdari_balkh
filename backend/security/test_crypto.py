import os
import unittest
from unittest.mock import patch

from security.crypto import (
    EncryptedSecret,
    KeyUnavailableError,
    SecretDecryptionError,
    decrypt_secret,
    encrypt_secret,
)


class MemoryKeyProvider:
    """Test-only key provider; production must use an OS-backed provider."""

    def __init__(self, key=None):
        self.key = key or bytes(range(32))

    def active_key_id(self):
        return "test-key-v1"

    def get_key(self, key_id):
        if key_id != "test-key-v1":
            raise KeyError(key_id)
        return self.key


class AESGCMSecretTests(unittest.TestCase):
    def setUp(self):
        self.provider = MemoryKeyProvider()

    def test_round_trip_and_metadata_does_not_contain_plaintext(self):
        plaintext = b"otpauth-secret-material"
        envelope = encrypt_secret(
            plaintext, purpose="totp", subject_id="user:42", provider=self.provider
        )
        self.assertEqual(
            decrypt_secret(
                envelope, purpose="totp", subject_id="user:42", provider=self.provider
            ),
            plaintext,
        )
        self.assertNotIn(plaintext, envelope.ciphertext)
        self.assertEqual(len(envelope.nonce), 12)
        self.assertEqual(envelope.version, 1)

    def test_nonce_is_96_bit_and_changes_between_encryptions(self):
        first = encrypt_secret(
            b"same", purpose="totp", subject_id="user:42", provider=self.provider
        )
        second = encrypt_secret(
            b"same", purpose="totp", subject_id="user:42", provider=self.provider
        )
        self.assertEqual(len(first.nonce), 12)
        self.assertNotEqual(first.nonce, second.nonce)

    def test_ciphertext_tampering_is_rejected(self):
        envelope = encrypt_secret(
            b"secret", purpose="totp", subject_id="user:42", provider=self.provider
        )
        changed = bytearray(envelope.ciphertext)
        changed[-1] ^= 1
        tampered = EncryptedSecret(
            envelope.version, envelope.key_id, envelope.nonce, bytes(changed)
        )
        with self.assertRaises(SecretDecryptionError):
            decrypt_secret(
                tampered, purpose="totp", subject_id="user:42", provider=self.provider
            )

    def test_wrong_user_or_purpose_is_rejected(self):
        envelope = encrypt_secret(
            b"secret", purpose="totp", subject_id="user:42", provider=self.provider
        )
        for purpose, subject in (("recovery", "user:42"), ("totp", "user:43")):
            with self.subTest(purpose=purpose, subject=subject):
                with self.assertRaises(SecretDecryptionError):
                    decrypt_secret(
                        envelope, purpose=purpose, subject_id=subject,
                        provider=self.provider,
                    )

    def test_wrong_key_is_rejected(self):
        envelope = encrypt_secret(
            b"secret", purpose="totp", subject_id="user:42", provider=self.provider
        )
        wrong = MemoryKeyProvider(key=b"X" * 32)
        with self.assertRaises(SecretDecryptionError):
            decrypt_secret(
                envelope, purpose="totp", subject_id="user:42", provider=wrong
            )

    def test_missing_or_invalid_key_fails_closed(self):
        class Missing:
            def active_key_id(self):
                return "missing"

            def get_key(self, key_id):
                raise OSError("not available")

        with self.assertRaises(KeyUnavailableError):
            encrypt_secret(b"secret", purpose="totp", subject_id="u1", provider=Missing())

        class Invalid:
            def active_key_id(self):
                return "invalid"

            def get_key(self, key_id):
                return b"short"

        with self.assertRaises(KeyUnavailableError):
            encrypt_secret(b"secret", purpose="totp", subject_id="u1", provider=Invalid())

    def test_unsupported_envelope_version_is_rejected(self):
        envelope = encrypt_secret(
            b"secret", purpose="totp", subject_id="user:42", provider=self.provider
        )
        future = EncryptedSecret(
            999, envelope.key_id, envelope.nonce, envelope.ciphertext
        )
        with self.assertRaises(SecretDecryptionError):
            decrypt_secret(
                future, purpose="totp", subject_id="user:42", provider=self.provider
            )


if __name__ == "__main__":
    unittest.main()
