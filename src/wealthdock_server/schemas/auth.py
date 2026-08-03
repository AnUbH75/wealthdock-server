"""Pydantic schemas for auth endpoints."""

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    """Schema for user registration requests."""

    email: EmailStr = Field(..., description="User's email address.")
    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        description="Password must be between 8 and 72 characters long.",
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email address to lowercase and strip whitespace."""
        if isinstance(v, str):
            return v.lower().strip()
        return v


class UserLogin(BaseModel):
    """Schema for user login requests."""

    email: EmailStr = Field(..., description="User's email address.")
    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        description="Password must be between 8 and 72 characters long.",
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email address to lowercase and strip whitespace."""
        if isinstance(v, str):
            return v.lower().strip()
        return v


class Token(BaseModel):
    """Schema representing an authentication token response."""

    access_token: str
    token_type: str
    email: str
