"""SQLAlchemy TypeDecorators for encrypting sensitive fields at rest."""

import json
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.types import String, Text, TypeDecorator


class DecryptionError(ValueError):
    """Raised when decryption of an encrypted database field fails."""

    pass


@lru_cache
def _get_fernet_cipher(keys: tuple[str, ...]) -> MultiFernet:
    """Cache MultiFernet instances based on the encryption keys tuple."""
    return MultiFernet([Fernet(key.encode("utf-8")) for key in keys])


class EncryptedString(TypeDecorator[str]):
    """SQLAlchemy TypeDecorator that encrypts string values at rest using Fernet."""

    impl = String
    cache_ok = True

    def __init__(self, length: int | None = None, *args: Any, **kwargs: Any) -> None:
        """Initialize the EncryptedString decorator.

        Args:
            length: Optional maximum length of the plaintext string.
            *args: Additional arguments passed to the parent TypeDecorator.
            **kwargs: Additional keyword arguments passed to the parent TypeDecorator.
        """
        super().__init__(*args, **kwargs)
        self.length = length
        if length is not None:
            # Sizing the column for ciphertext expansion rather than plaintext length.
            # Fernet binary overhead is 57 bytes (1 version + 8 timestamp + 16 IV + 32 HMAC).
            # AES block size is 16 bytes, PKCS7 padding adds between 1 and 16 bytes.
            padded_len = ((length // 16) + 1) * 16
            binary_len = 57 + padded_len
            # Base64url encoding turns N bytes into ceil(N / 3) * 4 bytes.
            ciphertext_length = ((binary_len + 2) // 3) * 4
            self.impl = String(ciphertext_length)  # type: ignore[assignment]

    def _get_fernet(self) -> MultiFernet:
        """Load the MultiFernet cipher using the application settings."""
        from wealthdock_server.core.config import get_settings

        settings = get_settings()
        return _get_fernet_cipher(tuple(settings.encryption_keys))

    def process_bind_param(self, value: str | None, _dialect: Any) -> str | None:
        """Encrypt the plaintext value before saving to the database."""
        if value is None:
            return None
        if self.length is not None and len(value) > self.length:
            raise ValueError(f"Plaintext value length exceeds max limit of {self.length}")
        return self._get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value: str | None, _dialect: Any) -> str | None:
        """Decrypt the stored ciphertext value back to plaintext."""
        if value is None:
            return None
        try:
            return self._get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as e:
            raise DecryptionError(
                f"Decryption failed for {self.__class__.__name__} field. "
                "The decryption key does not match the ciphertext (token)."
            ) from e


class EncryptedDecimal(TypeDecorator[Decimal]):
    """SQLAlchemy TypeDecorator that encrypts Decimal values at rest using Fernet."""

    impl = Text
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the EncryptedDecimal decorator."""
        super().__init__(*args, **kwargs)

    def _get_fernet(self) -> MultiFernet:
        """Load the MultiFernet cipher using the application settings."""
        from wealthdock_server.core.config import get_settings

        settings = get_settings()
        return _get_fernet_cipher(tuple(settings.encryption_keys))

    def process_bind_param(self, value: Decimal | None, _dialect: Any) -> str | None:
        """Encrypt the Decimal value as an encrypted string representation before saving."""
        if value is None:
            return None
        str_val = str(value)
        return self._get_fernet().encrypt(str_val.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value: str | None, _dialect: Any) -> Decimal | None:
        """Decrypt the stored ciphertext value and parse it back to a Decimal."""
        if value is None:
            return None
        try:
            decrypted = self._get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as e:
            raise DecryptionError(
                f"Decryption failed for {self.__class__.__name__} field. "
                "The decryption key does not match the ciphertext (token)."
            ) from e

        try:
            return Decimal(decrypted)
        except InvalidOperation as e:
            raise ValueError(
                f"Failed to parse decrypted value '{decrypted}' as "
                f"Decimal for {self.__class__.__name__}."
            ) from e


class EncryptedJSON(TypeDecorator[Any]):
    """SQLAlchemy TypeDecorator that encrypts JSON-serializable structures at rest using Fernet."""

    impl = Text
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the EncryptedJSON decorator."""
        super().__init__(*args, **kwargs)

    def _get_fernet(self) -> MultiFernet:
        """Load the MultiFernet cipher using the application settings."""
        from wealthdock_server.core.config import get_settings

        settings = get_settings()
        return _get_fernet_cipher(tuple(settings.encryption_keys))

    def process_bind_param(self, value: Any, _dialect: Any) -> str | None:
        """Serialize and encrypt the python object before saving."""
        if value is None:
            return None
        json_val = json.dumps(value)
        return self._get_fernet().encrypt(json_val.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value: str | None, _dialect: Any) -> Any:
        """Decrypt and deserialize the stored ciphertext value back to python objects."""
        if value is None:
            return None
        try:
            decrypted = self._get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as e:
            raise DecryptionError(
                f"Decryption failed for {self.__class__.__name__} field. "
                "The decryption key does not match the ciphertext (token)."
            ) from e
        return json.loads(decrypted)
