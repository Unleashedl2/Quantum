from datetime import datetime
from decimal import Decimal
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, func,
                        Numeric, SmallInteger, String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin

MONEY = Numeric(12, 2)


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(250))
    slug: Mapped[str] = mapped_column(String(280), unique=True)
    short_description: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    price_usd: Mapped[Decimal] = mapped_column(MONEY)
    sale_price_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    specs: Mapped[dict | None] = mapped_column(JSONB)            # características técnicas
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    warranty: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")  # draft|published|archived
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # borrado lógico

    images: Mapped[list["ProductImage"]] = relationship(back_populates="product", order_by="ProductImage.sort_order",
                                                        cascade="all, delete-orphan")
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("price_usd >= 0", name="price_nonneg"),
        CheckConstraint("sale_price_usd IS NULL OR (sale_price_usd >= 0 AND sale_price_usd < price_usd)",
                        name="sale_lt_price"),
        CheckConstraint("status IN ('draft','published','archived')", name="status_valid"),
        Index("ix_products_status_cat", "status", "category_id"),
        Index("ix_products_created", "created_at"),
    )


class ProductImage(Base):
    __tablename__ = "product_images"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(500))        # URL en almacenamiento S3; nunca el binario
    storage_key: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(60))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    alt_text: Mapped[str | None] = mapped_column(String(250))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    product: Mapped[Product] = relationship(back_populates="images")


class ProductVariant(Base, TimestampMixin):
    __tablename__ = "product_variants"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    attributes: Mapped[dict] = mapped_column(JSONB)       # {"talla":"M","color":"Negro"}
    price_usd: Mapped[Decimal | None] = mapped_column(MONEY)   # null = usa el del producto
    sale_price_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    product: Mapped[Product] = relationship(back_populates="variants")


class Inventory(Base):
    """Una fila por producto (variant_id NULL) o por variante. CHECK impide stock negativo."""
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id", ondelete="CASCADE"))
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    quantity_reserved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint("quantity_on_hand >= 0", name="onhand_nonneg"),
        CheckConstraint("quantity_reserved >= 0 AND quantity_reserved <= quantity_on_hand", name="reserved_valid"),
        UniqueConstraint("product_id", "variant_id", name="uq_inventory_product_variant"),
    )


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inventory_id: Mapped[int] = mapped_column(ForeignKey("inventory.id", ondelete="RESTRICT"), index=True)
    delta: Mapped[int] = mapped_column(Integer)           # + entrada / - salida
    reason: Mapped[str] = mapped_column(String(30))       # purchase|sale|reserve|release|adjustment|return
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductReview(Base, TimestampMixin):
    __tablename__ = "product_reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id", ondelete="RESTRICT"))  # compra verificada
    rating: Mapped[int] = mapped_column(SmallInteger)
    title: Mapped[str | None] = mapped_column(String(160))
    body: Mapped[str | None] = mapped_column(Text)
    moderation_status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        UniqueConstraint("order_item_id", name="uq_review_one_per_order_item"),  # sin duplicados por compra/producto
    )


class ProductQuestion(Base, TimestampMixin):
    __tablename__ = "product_questions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    moderation_status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")


class ProductAnswer(Base, TimestampMixin):
    __tablename__ = "product_answers"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("product_questions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
