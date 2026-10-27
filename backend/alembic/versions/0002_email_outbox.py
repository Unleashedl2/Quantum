"""Cola de correos (Fase 2)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
from app.models.system import EmailOutbox

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # checkfirst: en instalaciones nuevas 0001 (create_all) ya pudo crearla
    EmailOutbox.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    EmailOutbox.__table__.drop(op.get_bind(), checkfirst=True)
