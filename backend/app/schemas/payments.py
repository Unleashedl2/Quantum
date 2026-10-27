from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field


class PaymentDeclareIn(BaseModel):
    origin_bank_id: int | None = None
    receiving_bank_id: int | None = None
    reference: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{4,40}$")
    paid_at: date | None = None
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=6)
    cash_modality: Literal["advance_paid", "on_delivery"] | None = None
    network: str | None = Field(default=None, max_length=20)
    tx_hash: str | None = Field(default=None, pattern=r"^(0x)?[A-Fa-f0-9]{64}$")
    note: str | None = Field(default=None, max_length=500)


class ReviewIn(BaseModel):
    action: Literal["start_review", "approve", "reject", "request_info", "note"]
    note: str | None = Field(default=None, max_length=1000)
    verified_with: str | None = Field(default=None, max_length=300)   # con qué medio se verificó el dinero
    confirmations: int | None = Field(default=None, ge=0, le=100000)  # USDT


class BankIn(BaseModel):
    code: str = Field(pattern=r"^\d{4}$")
    name: str = Field(min_length=3, max_length=160)
    is_active: bool = True
    source_note: str | None = Field(default=None, max_length=255)


class BankUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=160)
    is_active: bool | None = None
    source_note: str | None = Field(default=None, max_length=255)


class AccountCfg(BaseModel):
    bank: str = Field(min_length=2, max_length=120)
    holder: str = Field(min_length=2, max_length=160)
    number: str = Field(min_length=4, max_length=60)      # cuenta o teléfono
    document: str | None = Field(default=None, max_length=30)


class NetworkCfg(BaseModel):
    min_confirmations: int = Field(default=20, ge=1, le=1000)


class MethodConfig(BaseModel):
    accounts: list[AccountCfg] = []
    address: str | None = Field(default=None, min_length=20, max_length=120, pattern=r"^[A-Za-z0-9]+$")
    networks: dict[str, NetworkCfg] = {}


class MethodUpdate(BaseModel):
    is_active: bool | None = None
    instructions: str | None = Field(default=None, max_length=2000)
    config: MethodConfig | None = None
