"""Pytest configuration and test setup."""

import os

from cryptography.fernet import Fernet

# Set up test environment variables before importing any application code
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
