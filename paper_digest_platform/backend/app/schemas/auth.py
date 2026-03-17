from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class MessageResponse(BaseModel):
    message: str


class RegisterCodeRequest(BaseModel):
    email: EmailStr


class RegisterConfirmRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=6, max_length=6)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class PasswordResetCodeRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)


class UserProfile(BaseModel):
    id: int
    username: str
    email: EmailStr


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: str
    user: UserProfile

