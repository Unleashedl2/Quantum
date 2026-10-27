"""Pagos, validación y notificaciones (Fase 5)

Revision ID: 0005
Revises: 0004
"""
from alembic import op
from app.models.sales import PaymentEvent

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    PaymentEvent.__table__.create(op.get_bind(), checkfirst=True)
    # Un solo pago "abierto" por pedido (un pago rechazado permite declarar otro)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_order_open ON payments (order_id) "
               "WHERE status IN ('declared','pending_review','approved','needs_info')")
    # La misma referencia no puede estar aprobada dos veces para el mismo método
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_approved_ref ON payments (method_id, lower(reference)) "
               "WHERE status = 'approved' AND reference IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payments_status_created ON payments (status, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_audience ON notifications (audience, read_at, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notifications_audience")
    op.execute("DROP INDEX IF EXISTS ix_payments_status_created")
    op.execute("DROP INDEX IF EXISTS uq_payments_approved_ref")
    op.execute("DROP INDEX IF EXISTS uq_payments_order_open")
    PaymentEvent.__table__.drop(op.get_bind(), checkfirst=True)
