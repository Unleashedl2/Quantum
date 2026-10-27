"""Comandos de administración.  Uso:  python -m app.cli init-system | init-admins | verify-banks-note"""
import csv
import sys
from pathlib import Path
from sqlalchemy import select
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Bank, PaymentMethod, Permission, Role, ShippingMethod, User
from app.services.audit import audit

PERMISSIONS = {
    "products.manage": "Gestionar productos", "categories.manage": "Gestionar categorías",
    "orders.view": "Ver pedidos", "payments.review": "Validar pagos", "shipping.manage": "Gestionar envíos",
    "customers.view": "Ver clientes", "customers.block": "Bloquear clientes", "reports.view": "Ver reportes",
    "reports.export": "Exportar reportes", "banks.manage": "Gestionar bancos",
    "staff.manage": "Gestionar usuarios administrativos", "permissions.manage": "Asignar permisos",
    "settings.theme": "Personalizar identidad visual", "settings.general": "Configuración general",
    "audit.view": "Ver auditoría", "reviews.moderate": "Moderar valoraciones y preguntas",
}
ADMIN_PERMS = {"products.manage", "categories.manage", "orders.view", "payments.review", "shipping.manage",
               "customers.view", "reports.view", "reviews.moderate"}

PAYMENT_METHODS = [("bank_transfer", "Transferencia bancaria"), ("mobile_payment", "Pago móvil"),
                   ("cash", "Efectivo"), ("usdt", "USDT")]
SHIPPING = [("mrw", "MRW"), ("zoom", "Zoom"), ("liberty_express", "Liberty Express"), ("tealca", "Tealca")]


def init_system() -> None:
    """Idempotente: crea permisos, roles, métodos de pago/envío y bancos (sin duplicar)."""
    with SessionLocal() as db:
        perms = {}
        for code, desc in PERMISSIONS.items():
            p = db.scalar(select(Permission).where(Permission.code == code)) or Permission(code=code, description=desc)
            db.add(p); perms[code] = p
        db.flush()
        for name, codes in (("master", set(PERMISSIONS)), ("admin", ADMIN_PERMS), ("customer", set())):
            r = db.scalar(select(Role).where(Role.name == name)) or Role(name=name)
            r.permissions = [perms[c] for c in codes]
            db.add(r)
        for code, name in PAYMENT_METHODS:
            if not db.scalar(select(PaymentMethod).where(PaymentMethod.code == code)):
                db.add(PaymentMethod(code=code, name=name))
        for code, name in SHIPPING:
            if not db.scalar(select(ShippingMethod).where(ShippingMethod.code == code)):
                db.add(ShippingMethod(code=code, name=name, api_integrated=False))
        path = Path(__file__).resolve().parent.parent / "seeds" / "banks_ve.csv"
        added = 0
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not db.scalar(select(Bank).where(Bank.code == row["code"])):
                    db.add(Bank(code=row["code"], name=row["name"], verified_at=None,
                                source_note="Carga inicial; verificar contra listado vigente de SUDEBAN")); added += 1
        db.commit()
        print(f"Sistema inicializado. Bancos nuevos: {added} (pendientes de verificación).")


def init_admins() -> None:
    if settings.is_production:
        sys.exit("Rechazado: las contraseñas temporales no se permiten con APP_ENV=production. "
                 "Cree las cuentas con una contraseña robusta propia.")
    if not settings.init_temp_password:
        sys.exit("Defina INIT_TEMP_PASSWORD en el entorno para inicializar las cuentas.")
    with SessionLocal() as db:
        for email, role_name, first in ((settings.master_email, "master", "Master"), (settings.admin_email, "admin", "Admin")):
            role = db.scalar(select(Role).where(Role.name == role_name))
            if not role:
                sys.exit("Ejecute primero: python -m app.cli init-system")
            if db.scalar(select(User).where(User.email == email)):
                print(f"{email}: ya existe, se omite (sin duplicados)."); continue
            u = User(first_name=first, last_name="Quantum Store", email=email, is_staff=True,
                     password_hash=hash_password(settings.init_temp_password),
                     must_change_password=True, roles=[role])   # obliga cambio en primer acceso
            db.add(u); db.flush()
            audit(db, "staff.bootstrap", None, "user", u.id, {"role": role_name})
            print(f"{email}: creado con rol {role_name}; deberá cambiar la contraseña al ingresar.")
        db.commit()


def expire_orders() -> None:
    """Cancela pedidos sin pago cuya reserva venció. Programar cada 10-15 min (cron/systemd timer)."""
    from app.services.orders import expire_unpaid_orders
    with SessionLocal() as db:
        print(f"Pedidos cancelados por reserva vencida: {expire_unpaid_orders(db)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"init-system": init_system, "init-admins": init_admins, "expire-orders": expire_orders}.get(cmd, lambda: sys.exit(__doc__))()
