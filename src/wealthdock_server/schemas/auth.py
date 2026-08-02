from pydantic import BaseModel


class UserRegister(BaseModel):
    """Schema for user registration requests."""

    email: str
    password: str


class UserLogin(BaseModel):
    """Schema for user login requests."""

    email: str
    password: str


class Token(BaseModel):
    """Schema representing an authentication token response."""

    access_token: str
    token_type: str
    email: str
