"""Índices de catálogo (Fase 3)

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL no considera iguales dos NULL en UNIQUE(product_id, variant_id): este índice parcial lo impide.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_product_novariant "
               "ON inventory (product_id) WHERE variant_id IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_shortdesc_trgm ON products USING gin (short_description gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_sale ON products (sale_price_usd) WHERE sale_price_usd IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_sale")
    op.execute("DROP INDEX IF EXISTS ix_products_shortdesc_trgm")
    op.execute("DROP INDEX IF EXISTS uq_inventory_product_novariant")
