from pydantic import BaseModel, EmailStr, Field


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(max_length=256)


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ProfileOut(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str | None
    state: str | None
    municipality: str | None
    address: str | None
    email_verified: bool
    # sin national_id: la cédula no se devuelve por API


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, pattern=r"^\+?\d{10,15}$")
    state: str | None = Field(default=None, max_length=80)
    municipality: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)


class AddressIn(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    recipient_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(pattern=r"^\+?\d{10,15}$")
    state: str = Field(min_length=2, max_length=80)
    municipality: str = Field(min_length=2, max_length=120)
    full_address: str = Field(min_length=5, max_length=500)
    reference: str | None = Field(default=None, max_length=500)
    is_default: bool = False


class AddressOut(AddressIn):
    id: int


class StaffCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    role: str = Field(pattern=r"^(admin|master)$")


class StaffOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    roles: list[str]
    is_active: bool


class BlockIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
