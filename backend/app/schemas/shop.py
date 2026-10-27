from pydantic import BaseModel, Field


class CartAddIn(BaseModel):
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(default=1, ge=1, le=100)


class CartSetIn(BaseModel):
    quantity: int = Field(ge=0, le=100)   # 0 = eliminar


class CheckoutIn(BaseModel):
    address_id: int
    shipping_method_id: int
    payment_method_id: int
    delivery_notes: str | None = Field(default=None, max_length=500)
