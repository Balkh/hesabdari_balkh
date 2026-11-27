"""Dependency-free domain errors shared by encryption and OS key providers."""


class KeyUnavailableError(RuntimeError):
    """The configured OS key provider cannot safely supply the key."""


class SecretDecryptionError(RuntimeError):
    """Ciphertext, key version, identity binding, or authentication tag invalid."""
