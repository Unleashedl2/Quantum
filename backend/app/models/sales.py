from datetime import datetime
from decimal import Decimal
from sqlalchemy import (Sequence, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, func,
                        Numeric, String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin
from app.models.catalog import MONEY

order_number_seq = Sequence("order_number_seq", metadata=Base.metadata)

ORDER_STATUSES = ("pending_payment", "payment_validation", "preparing", "shipped", "out_for_delivery",
                  "delivered", "cancelled", "returned")
PAYMENT_STATUSES = ("declared", "pending_review", "approved", "rejected", "needs_info")


class Bank(Base, TimestampMixin):
    """Catálogo administrable; la carga inicial viene de seeds/banks_ve.csv y debe verificarse."""
    __tablename__ = "banks"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(4), unique=True)     # código SUDEBAN de 4 dígitos
    name: Mapped[str] = mapped_column(String(160), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_note: Mapped[str | None] = mapped_column(String(255))


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)    # bank_transfer|mobile_payment|cash|usdt
    name: Mapped[str] = mapped_column(String(80))
    instructions: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict | None] = mapped_column(JSONB)            # cuentas receptoras, red y dirección USDT, etc.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class ShippingMethod(Base):
    __tablename__ = "shipping_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)    # mrw|zoom|liberty_express|tealca
    name: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    api_integrated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # false = guías manuales


class Cart(Base, TimestampMixin):
    __tablename__ = "carts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    items: Mapped[list["CartItem"]] = relationship(back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base, TimestampMixin):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(Integer)
    cart: Mapped[Cart] = relationship(back_populates="items")
    __table_args__ = (CheckConstraint("quantity > 0", name="qty_pos"),
                      UniqueConstraint("cart_id", "product_id", "variant_id", name="uq_cart_item"))


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending_payment", index=True)
    subtotal_usd: Mapped[Decimal] = mapped_column(MONEY)
    shipping_usd: Mapped[Decimal] = mapped_column(MONEY, default=0)
    total_usd: Mapped[Decimal] = mapped_column(MONEY)
    # Copia histórica de la dirección de entrega (no depende de user_addresses)
    ship_recipient: Mapped[str] = mapped_column(String(160))
    ship_phone: Mapped[str] = mapped_column(String(30))
    ship_state: Mapped[str] = mapped_column(String(80))
    ship_municipality: Mapped[str] = mapped_column(String(120))
    ship_address: Mapped[str] = mapped_column(Text)
    ship_reference: Mapped[str | None] = mapped_column(Text)
    delivery_notes: Mapped[str | None] = mapped_column(Text)
    shipping_method_id: Mapped[int | None] = mapped_column(ForeignKey("shipping_methods.id"))
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"))
    reservation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))   # evita pedidos duplicados por doble clic
    # Si se convierte a Bs: se guarda tasa, fuente y fecha; nunca se recalcula.
    fx_rate_ves: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    fx_source: Mapped[str | None] = mapped_column(String(80))
    fx_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_ves: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("total_usd = subtotal_usd + shipping_usd", name="total_consistent"),
        CheckConstraint("status IN ('pending_payment','payment_validation','preparing','shipped',"
                        "'out_for_delivery','delivered','cancelled','returned')", name="status_valid"),
        Index("ix_orders_user_created", "user_id", "created_at"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id", ondelete="SET NULL"))
    # Snapshot histórico: el catálogo puede cambiar sin alterar facturas
    product_name: Mapped[str] = mapped_column(String(250))
    sku: Mapped[str] = mapped_column(String(80))
    description_snapshot: Mapped[str | None] = mapped_column(Text)
    variant_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    unit_price_usd: Mapped[Decimal] = mapped_column(MONEY)
    quantity: Mapped[int] = mapped_column(Integer)
    line_total_usd: Mapped[Decimal] = mapped_column(MONEY)
    order: Mapped[Order] = relationship(back_populates="items")
    __table_args__ = (CheckConstraint("quantity > 0", name="qty_pos"),
                      CheckConstraint("line_total_usd = unit_price_usd * quantity", name="line_consistent"))


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    method_id: Mapped[int] = mapped_column(ForeignKey("payment_methods.id"))
    status: Mapped[str] = mapped_column(String(16), default="declared", index=True)
    amount_declared_usd: Mapped[Decimal] = mapped_column(MONEY)
    origin_bank_id: Mapped[int | None] = mapped_column(ForeignKey("banks.id"))
    receiving_bank_id: Mapped[int | None] = mapped_column(ForeignKey("banks.id"))
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict | None] = mapped_column(JSONB)          # red USDT, hash, modalidad de efectivo...
    proof_storage_key: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("status IN ('declared','pending_review','approved','rejected','needs_info')", name="status_valid"),
        CheckConstraint("status NOT IN ('approved','rejected') OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
                        name="review_audited"),
    )


class Shipment(Base, TimestampMixin):
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), unique=True)
    shipping_method_id: Mapped[int] = mapped_column(ForeignKey("shipping_methods.id"))
    tracking_number: Mapped[str | None] = mapped_column(String(80), index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    carrier_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    proof_storage_key: Mapped[str | None] = mapped_column(String(500))


class ShipmentEvent(Base):
    """Historial append-only: nunca se actualiza ni se borra."""
    __tablename__ = "shipment_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryConfirmation(Base):
    __tablename__ = "delivery_confirmations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), unique=True)
    method: Mapped[str] = mapped_column(String(20))               # customer_otp | admin_release
    code_hash: Mapped[str | None] = mapped_column(String(64))
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    release_reason: Mapped[str | None] = mapped_column(Text)
    evidence_note: Mapped[str | None] = mapped_column(Text)


class OrderEvent(Base):
    """Historial de estados del pedido: append-only (no se actualiza ni se borra)."""
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentEvent(Base):
    """Historial de validación de pagos: append-only."""
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(24))   # declared|start_review|approved|rejected|info_requested|customer_responded|note|proof_uploaded
    note: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
