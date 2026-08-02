"""SQLAlchemy TypeDecorators for encrypting sensitive fields at rest."""

import json
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy.types import String, Text, TypeDecorator


class EncryptedString(TypeDecorator[str]):
    """SQLAlchemy TypeDecorator that encrypts string values at rest using Fernet."""

    impl = String
    cache_ok = False

    def __init__(self, length: int | None = None, *args: Any, **kwargs: Any) -> None:
        """Initialize the EncryptedString decorator.

        Args:
            length: Optional maximum length of the string.
            *args: Additional arguments passed to the parent TypeDecorator.
            **kwargs: Additional keyword arguments passed to the parent TypeDecorator.
        """
        super().__init__(*args, **kwargs)
        if length is not None:
            self.impl = String(length)  # type: ignore[assignment]
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        """Lazily load the Fernet cipher using the application settings."""
        if self._fernet is None:
            from wealthdock_server.core.config import get_settings

            settings = get_settings()
            self._fernet = Fernet(settings.encryption_key.encode("utf-8"))
        return self._fernet

    def process_bind_param(self, value: str | None, _dialect: Any) -> str | None:
        """Encrypt the plaintext value before saving to the database."""
        if value is None:
            return None
        return self._get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value: str | None, _dialect: Any) -> str | None:
        """Decrypt the stored ciphertext value back to plaintext."""
        if value is None:
            return None
        return self._get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")


class EncryptedFloat(TypeDecorator[float]):
    """SQLAlchemy TypeDecorator that encrypts float values at rest using Fernet."""

    impl = Text
    cache_ok = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the EncryptedFloat decorator."""
        super().__init__(*args, **kwargs)
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        """Lazily load the Fernet cipher using the application settings."""
        if self._fernet is None:
            from wealthdock_server.core.config import get_settings

            settings = get_settings()
            self._fernet = Fernet(settings.encryption_key.encode("utf-8"))
        return self._fernet

    def process_bind_param(self, value: float | None, _dialect: Any) -> str | None:
        """Encrypt the float value as an encrypted string representation before saving."""
        if value is None:
            return None
        str_val = str(value)
        return self._get_fernet().encrypt(str_val.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value: str | None, _dialect: Any) -> float | None:
        """Decrypt the stored ciphertext value and parse it back to a float."""
        if value is None:
            return None
        decrypted = self._get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        return float(decrypted)


class EncryptedJSON(TypeDecorator[Any]):
    """SQLAlchemy TypeDecorator that encrypts JSON-serializable structures at rest using Fernet."""

    impl = Text
    cache_ok = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the EncryptedJSON decorator."""
        super().__init__(*args, **kwargs)
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        """Lazily load the Fernet cipher using the application settings."""
        if self._fernet is None:
            from wealthdock_server.core.config import get_settings

            settings = get_settings()
            self._fernet = Fernet(settings.encryption_key.encode("utf-8"))
        return self._fernet

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
        decrypted = self._get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        return json.loads(decrypted)
