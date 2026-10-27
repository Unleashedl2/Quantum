from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    national_id: str = Field(pattern=r"^[VEve]?-?\d{5,9}$")
    state: str = Field(min_length=2, max_length=80)
    municipality: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=5, max_length=500)
    phone: str = Field(pattern=r"^\+?\d{10,15}$")
    email: EmailStr
    password: str
    password_confirm: str
    accept_terms: bool

    @field_validator("national_id")
    @classmethod
    def norm_id(cls, v: str) -> str:
        return v.upper().replace("-", "")


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class MeOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    roles: list[str]
    permissions: list[str]
    must_change_password: bool
    csrf_token: str
    # La cédula NO se incluye en ninguna respuesta de la API pública.
