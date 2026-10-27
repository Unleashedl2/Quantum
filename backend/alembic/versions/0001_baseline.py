"""Esquema base de Quantum Store (Fase 1)

Revision ID: 0001
Revises:
"""
from alembic import op
from app.db.base import Base
import app.models  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # Línea base: crea todas las tablas definidas en app/models.
    # Los cambios posteriores deben ir en migraciones incrementales:
    #   alembic revision --autogenerate -m "descripcion"
    Base.metadata.create_all(bind=bind)
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_name_trgm ON products USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_brand_trgm ON products USING gin (brand gin_trgm_ops)")


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
