from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

Money = Decimal


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: int | None = None
    is_active: bool = True
    sort_order: int = 0


class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    image_url: str | None
    parent_id: int | None
    is_active: bool
    sort_order: int


class ProductIn(BaseModel):
    category_id: int
    name: str = Field(min_length=2, max_length=250)
    short_description: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    sku: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    price_usd: Money = Field(ge=0, max_digits=10, decimal_places=2)
    sale_price_usd: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    specs: dict[str, str] | None = None
    weight_kg: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=3)
    length_cm: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    width_cm: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    height_cm: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    warranty: str | None = Field(default=None, max_length=255)
    is_featured: bool = False
    status: str = Field(default="draft", pattern=r"^(draft|published)$")
    initial_stock: int = Field(default=0, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def sale_lower(self):
        if self.sale_price_usd is not None and self.sale_price_usd >= self.price_usd:
            raise ValueError("El precio de oferta debe ser menor al precio normal")
        return self


class ProductUpdate(BaseModel):
    """Todos los campos opcionales; initial_stock no aplica (el stock se cambia con ajustes de inventario)."""
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=2, max_length=250)
    short_description: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    sku: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    price_usd: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    sale_price_usd: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    clear_sale_price: bool = False
    specs: dict[str, str] | None = None
    warranty: str | None = Field(default=None, max_length=255)
    is_featured: bool | None = None


class VariantIn(BaseModel):
    sku: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    attributes: dict[str, str] = Field(min_length=1)
    price_usd: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    sale_price_usd: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    initial_stock: int = Field(default=0, ge=0, le=1_000_000)


class StockAdjust(BaseModel):
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(pattern=r"^(purchase|adjustment|return)$")
    note: str | None = Field(default=None, max_length=500)
    variant_id: int | None = None

    @model_validator(mode="after")
    def nonzero(self):
        if self.delta == 0:
            raise ValueError("El ajuste no puede ser 0")
        return self


class ImageOrder(BaseModel):
    ids: list[int] = Field(min_length=1)


class ProductCard(BaseModel):
    id: int
    slug: str
    name: str
    brand: str | None
    category_id: int
    price_usd: Decimal
    sale_price_usd: Decimal | None
    effective_price_usd: Decimal
    available: int
    in_stock: bool
    image_url: str | None
    status: str
    sku: str


class Page(BaseModel):
    items: list[ProductCard]
    total: int
    page: int
    page_size: int
