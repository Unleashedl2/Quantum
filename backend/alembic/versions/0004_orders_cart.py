"""Carrito, pedidos y reservas (Fase 4)

Revision ID: 0004
Revises: 0003
"""
from alembic import op
from app.models.sales import OrderEvent

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS order_number_seq")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method_id integer REFERENCES payment_methods(id)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS reservation_expires_at timestamptz")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS idempotency_key varchar(64)")
    OrderEvent.__table__.create(op.get_bind(), checkfirst=True)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_user_idem ON orders (user_id, idempotency_key) "
               "WHERE idempotency_key IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_expiry ON orders (reservation_expires_at) "
               "WHERE status = 'pending_payment'")
    # NULL != NULL en UNIQUE: sin este índice parcial se podría duplicar la línea de un producto sin variante
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_item_novariant ON cart_items (cart_id, product_id) "
               "WHERE variant_id IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cart_item_novariant")
    op.execute("DROP INDEX IF EXISTS ix_orders_expiry")
    op.execute("DROP INDEX IF EXISTS uq_orders_user_idem")
    OrderEvent.__table__.drop(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS idempotency_key")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS reservation_expires_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS payment_method_id")
