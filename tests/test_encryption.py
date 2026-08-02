"""Tests for SQLAlchemy encryption TypeDecorators."""

import json
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from wealthdock_server.core.config import Settings
from wealthdock_server.db.encryption import EncryptedFloat, EncryptedJSON, EncryptedString


# Setup local test Base for test model definitions
class BaseForTest(DeclarativeBase):
    pass


class DummyFinancialRecord(BaseForTest):
    __tablename__ = "dummy_financial_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_number: Mapped[str] = mapped_column(EncryptedString(255))
    balance: Mapped[float] = mapped_column(EncryptedFloat)
    bank_credentials: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON)


def test_encryption_key_validation() -> None:
    """Verify settings validation for encryption key correctness."""
    # Valid key should succeed
    valid_key = Fernet.generate_key().decode()
    settings = Settings(encryption_key=valid_key)
    assert settings.encryption_key == valid_key

    # Invalid key should fail validation
    with pytest.raises(ValidationError) as exc_info:
        Settings(encryption_key="invalid-key-short-and-not-base64")
    assert "Invalid encryption_key" in str(exc_info.value)


def test_encrypted_columns_lifecycle() -> None:
    """Verify that columns are encrypted at rest and decrypted on retrieve."""
    # Create in-memory SQLite database (sync)
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    # Create tables
    BaseForTest.metadata.create_all(engine)

    account_num = "1234567890"
    bal_val = 1500.75
    creds_val = {"token": "xyz123abc", "expires_in": 3600}

    # 1. Insert records using SQLAlchemy
    with session_factory() as session:
        record = DummyFinancialRecord(
            account_number=account_num, balance=bal_val, bank_credentials=creds_val
        )
        session.add(record)
        session.commit()
        record_id = record.id

    # 2. Query and assert decryption via SQLAlchemy ORM
    with session_factory() as session:
        result = session.execute(
            select(DummyFinancialRecord).where(DummyFinancialRecord.id == record_id)
        )
        db_record = result.scalar_one()

        assert db_record.account_number == account_num
        assert db_record.balance == bal_val
        assert db_record.bank_credentials == creds_val

    # 3. Read directly using raw SQL execution to verify they are stored encrypted at rest
    with session_factory() as session:
        result_raw = session.execute(
            text(
                "select account_number, balance, bank_credentials "
                "from dummy_financial_records where id = :id"
            ),
            {"id": record_id},
        )
        row = result_raw.one()
        raw_account_number = row[0]
        raw_balance = row[1]
        raw_bank_credentials = row[2]

        # Verify raw values are NOT plaintext
        assert raw_account_number != account_num
        assert raw_balance != str(bal_val)
        assert raw_bank_credentials != json.dumps(creds_val)

        # Verify they can be decrypted back with Fernet manually (using default setting key)
        from wealthdock_server.core.config import get_settings

        f = Fernet(get_settings().encryption_key.encode("utf-8"))

        decrypted_acc = f.decrypt(raw_account_number.encode("utf-8")).decode("utf-8")
        decrypted_bal = float(f.decrypt(raw_balance.encode("utf-8")).decode("utf-8"))
        decrypted_creds = json.loads(
            f.decrypt(raw_bank_credentials.encode("utf-8")).decode("utf-8")
        )

        assert decrypted_acc == account_num
        assert decrypted_bal == bal_val
        assert decrypted_creds == creds_val

    engine.dispose()
