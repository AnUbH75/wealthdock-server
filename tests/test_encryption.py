"""Tests for SQLAlchemy encryption TypeDecorators."""

import json
from decimal import Decimal
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from wealthdock_server.core.config import Settings
from wealthdock_server.db.encryption import (
    DecryptionError,
    EncryptedDecimal,
    EncryptedJSON,
    EncryptedString,
)


# Setup local test Base for test model definitions
class BaseForTest(DeclarativeBase):
    pass


class DummyFinancialRecord(BaseForTest):
    __tablename__ = "dummy_financial_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_number: Mapped[str | None] = mapped_column(EncryptedString(255), nullable=True)
    balance: Mapped[Decimal | None] = mapped_column(EncryptedDecimal, nullable=True)
    bank_credentials: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON, nullable=True)


def test_encryption_key_validation() -> None:
    """Verify settings validation for encryption key correctness."""
    # Valid key should succeed (single key)
    valid_key = Fernet.generate_key().decode()
    settings = Settings(encryption_key=valid_key)  # type: ignore[call-arg]
    assert settings.encryption_keys == [valid_key]

    # Multiple valid keys should succeed (list of keys)
    valid_key_2 = Fernet.generate_key().decode()
    settings = Settings(encryption_keys=[valid_key, valid_key_2])
    assert settings.encryption_keys == [valid_key, valid_key_2]

    # Multiple valid keys (comma-separated string)
    settings = Settings(encryption_key=f"{valid_key},{valid_key_2}")  # type: ignore[call-arg]
    assert settings.encryption_keys == [valid_key, valid_key_2]

    # Multiple valid keys (JSON list)
    settings = Settings(encryption_key=f'["{valid_key}", "{valid_key_2}"]')  # type: ignore[call-arg]
    assert settings.encryption_keys == [valid_key, valid_key_2]

    # Invalid key should fail validation
    with pytest.raises(ValidationError) as exc_info:
        Settings(encryption_key="invalid-key-short-and-not-base64")  # type: ignore[call-arg]
    assert "Invalid encryption key" in str(exc_info.value)


def test_encrypted_columns_lifecycle() -> None:
    """Verify that columns are encrypted at rest and decrypted on retrieve."""
    # Create in-memory SQLite database (sync)
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    # Create tables
    BaseForTest.metadata.create_all(engine)

    account_num = "1234567890"
    bal_val = Decimal("1500.75")
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

        # Verify they can be decrypted back with Fernet manually (using current active key)
        from wealthdock_server.core.config import get_settings

        active_key = get_settings().encryption_keys[0]
        f = Fernet(active_key.encode("utf-8"))

        decrypted_acc = f.decrypt(raw_account_number.encode("utf-8")).decode("utf-8")
        decrypted_bal = Decimal(f.decrypt(raw_balance.encode("utf-8")).decode("utf-8"))
        decrypted_creds = json.loads(
            f.decrypt(raw_bank_credentials.encode("utf-8")).decode("utf-8")
        )

        assert decrypted_acc == account_num
        assert decrypted_bal == bal_val
        assert decrypted_creds == creds_val

    engine.dispose()


def test_encrypted_columns_none() -> None:
    """Verify handling of None values on all three types."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    BaseForTest.metadata.create_all(engine)

    with session_factory() as session:
        record = DummyFinancialRecord(
            account_number=None,
            balance=None,
            bank_credentials=None,
        )
        session.add(record)
        session.commit()
        record_id = record.id

    with session_factory() as session:
        db_record = session.execute(
            select(DummyFinancialRecord).where(DummyFinancialRecord.id == record_id)
        ).scalar_one()

        assert db_record.account_number is None
        assert db_record.balance is None
        assert db_record.bank_credentials is None

    # Check raw SQL values are indeed NULL
    with session_factory() as session:
        row = session.execute(
            text(
                "select account_number, balance, bank_credentials "
                "from dummy_financial_records where id = :id"
            ),
            {"id": record_id},
        ).one()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None

    engine.dispose()


def test_encrypted_string_max_length_roundtrip() -> None:
    """Verify that a string exactly at max length (255) inserts/decrypts.

    It should pass without database truncation or failure.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    BaseForTest.metadata.create_all(engine)

    max_length_str = "A" * 255

    # 1. Insert exactly 255 characters
    with session_factory() as session:
        record = DummyFinancialRecord(
            account_number=max_length_str,
            balance=Decimal("100.00"),
            bank_credentials={"test": True},
        )
        session.add(record)
        session.commit()
        record_id = record.id

    # 2. Query and verify roundtrip
    with session_factory() as session:
        db_record = session.execute(
            select(DummyFinancialRecord).where(DummyFinancialRecord.id == record_id)
        ).scalar_one()
        assert db_record.account_number == max_length_str

    # 3. Verify value longer than 255 raises StatementError wrap around ValueError on insert
    too_long_str = "A" * 256
    with session_factory() as session:
        record2 = DummyFinancialRecord(
            account_number=too_long_str,
            balance=Decimal("100.00"),
            bank_credentials={"test": True},
        )
        session.add(record2)
        with pytest.raises(StatementError) as exc_info:
            session.commit()
        assert "Plaintext value length exceeds max limit of 255" in str(exc_info.value)

    engine.dispose()


def test_decryption_with_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that using the wrong key raises DecryptionError."""
    # Write a record encrypted with key A
    key_a = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key_a)

    # Force settings reload
    from wealthdock_server.core.config import get_settings

    get_settings.cache_clear()

    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    BaseForTest.metadata.create_all(engine)

    with session_factory() as session:
        record = DummyFinancialRecord(
            account_number="1234567890",
            balance=Decimal("100.00"),
            bank_credentials={"test": True},
        )
        session.add(record)
        session.commit()
        record_id = record.id

    # Change active key to key B (wrong key)
    key_b = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key_b)
    get_settings.cache_clear()

    # Querying should fail with DecryptionError
    with session_factory() as session:
        with pytest.raises(DecryptionError) as exc_info:
            session.execute(
                select(DummyFinancialRecord).where(DummyFinancialRecord.id == record_id)
            ).scalar_one()
        assert "Decryption failed for EncryptedString field" in str(exc_info.value)

    engine.dispose()


def test_key_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify MultiFernet key rotation decrypts old key values and encrypts with the new key."""
    # 1. Start with Key A
    key_a = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key_a)

    from wealthdock_server.core.config import get_settings

    get_settings.cache_clear()

    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    BaseForTest.metadata.create_all(engine)

    # Encrypt record 1 with Key A
    with session_factory() as session:
        record1 = DummyFinancialRecord(
            account_number="acc-key-a",
            balance=Decimal("50.00"),
            bank_credentials={"key": "A"},
        )
        session.add(record1)
        session.commit()
        record1_id = record1.id

    # 2. Rotate to Key B as primary, keeping Key A as secondary
    key_b = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", f"{key_b},{key_a}")
    get_settings.cache_clear()

    # Decrypt record 1 (should succeed using Key A)
    with session_factory() as session:
        db_record1 = session.execute(
            select(DummyFinancialRecord).where(DummyFinancialRecord.id == record1_id)
        ).scalar_one()
        assert db_record1.account_number == "acc-key-a"
        assert db_record1.balance == Decimal("50.00")
        assert db_record1.bank_credentials == {"key": "A"}

    # Write record 2 (should be encrypted with Key B)
    with session_factory() as session:
        record2 = DummyFinancialRecord(
            account_number="acc-key-b",
            balance=Decimal("150.00"),
            bank_credentials={"key": "B"},
        )
        session.add(record2)
        session.commit()
        record2_id = record2.id

    # Verify record 2 is readable
    with session_factory() as session:
        db_record2 = session.execute(
            select(DummyFinancialRecord).where(DummyFinancialRecord.id == record2_id)
        ).scalar_one()
        assert db_record2.account_number == "acc-key-b"
        assert db_record2.balance == Decimal("150.00")

    # Verify record 2 raw ciphertext cannot be decrypted by Key A alone
    with session_factory() as session:
        row = session.execute(
            text("select account_number from dummy_financial_records where id = :id"),
            {"id": record2_id},
        ).one()
        raw_ct = row[0]

        from cryptography.fernet import InvalidToken

        # Trying to decrypt with key A alone should fail
        f_a = Fernet(key_a.encode("utf-8"))
        with pytest.raises(InvalidToken):
            f_a.decrypt(raw_ct.encode("utf-8"))

        # Decrypting with key B alone should succeed
        f_b = Fernet(key_b.encode("utf-8"))
        assert f_b.decrypt(raw_ct.encode("utf-8")).decode("utf-8") == "acc-key-b"

    engine.dispose()


def test_encrypted_decimal_invalid_value() -> None:
    """Verify EncryptedDecimal raises ValueError when decrypted value is not valid Decimal."""
    from wealthdock_server.core.config import get_settings

    decorator = EncryptedDecimal()
    # Encrypt a non-numeric string using the current key to bypass decryption
    valid_key = get_settings().encryption_keys[0]
    cipher = Fernet(valid_key.encode("utf-8"))
    bad_ct = cipher.encrypt(b"not-a-number").decode("utf-8")

    with pytest.raises(ValueError) as exc_info:
        decorator.process_result_value(bad_ct, None)
    assert "Failed to parse decrypted value" in str(exc_info.value)


def test_encrypted_decimal_json_decryption_failure() -> None:
    """Verify decryption failure raises DecryptionError on EncryptedDecimal and EncryptedJSON."""
    dec_decorator = EncryptedDecimal()
    json_decorator = EncryptedJSON()

    # Generate a ciphertext with a different key
    wrong_key = Fernet.generate_key().decode()
    cipher = Fernet(wrong_key.encode("utf-8"))
    bad_ct = cipher.encrypt(b"100.00").decode("utf-8")

    with pytest.raises(DecryptionError):
        dec_decorator.process_result_value(bad_ct, None)

    with pytest.raises(DecryptionError):
        json_decorator.process_result_value(bad_ct, None)
