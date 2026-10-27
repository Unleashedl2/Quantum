from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession, selectinload
from app.core.config import settings
from app.models import (Bank, Inventory, InventoryMovement, Notification, Order, Payment, PaymentEvent,
                        PaymentMethod, User)
from app.services.audit import audit
from app.services.auth import now
from app.services.cart import ShopError
from app.services.orders import change_status

OPEN = ("declared", "pending_review", "approved", "needs_info")
MAX_REJECTED = 5


def _notify(db, *, user_id, audience, kind, order, title, body=None):
    db.add(Notification(user_id=user_id, audience=audience, kind=kind, order_id=order.id, title=title, body=body))


def _event(db, payment, action, actor_id, note=None, detail=None):
    db.add(PaymentEvent(payment_id=payment.id, action=action, note=note, detail=detail, actor_user_id=actor_id))


def instructions_for(pm: PaymentMethod) -> dict:
    cfg = pm.config or {}
    return {"code": pm.code, "name": pm.name, "instructions": pm.instructions, "accounts": cfg.get("accounts", []),
            "usdt_address": cfg.get("address"), "networks": sorted((cfg.get("networks") or {}).keys())}


def _to_dt(d: date | None) -> datetime | None:
    return datetime.combine(d, time(12, 0), tzinfo=ZoneInfo(settings.timezone)) if d else None


def _validate(db: DbSession, pm: PaymentMethod, order: Order, d) -> tuple[dict, dict, list[str]]:
    """Devuelve (campos de Payment, detalles JSON, banderas para el revisor)."""
    flags: list[str] = []
    if d.paid_at and d.paid_at > date.today():
        raise ShopError("La fecha del pago no puede estar en el futuro")
    fields = {"amount_declared_usd": d.amount.quantize(Decimal("0.01")), "paid_at": _to_dt(d.paid_at),
              "reference": d.reference, "origin_bank_id": None, "receiving_bank_id": None}
    details: dict = {"customer_note": d.note}
    code = pm.code

    def bank(bid, label, required):
        if bid is None:
            if required:
                raise ShopError(f"Selecciona {label}")
            return None
        b = db.get(Bank, bid)
        if not b or not b.is_active:
            raise ShopError(f"{label.capitalize()} no es válido")
        return b.id

    if code in ("bank_transfer", "mobile_payment"):
        fields["origin_bank_id"] = bank(d.origin_bank_id, "el banco de origen" if code == "bank_transfer" else "el banco emisor", True)
        fields["receiving_bank_id"] = bank(d.receiving_bank_id, "el banco receptor", code == "mobile_payment")
        if not d.reference:
            raise ShopError("Indica el número de referencia")
        if not d.paid_at:
            raise ShopError("Indica la fecha del pago")
        if d.amount <= 0:
            raise ShopError("El importe debe ser mayor a 0")
    elif code == "cash":
        if not d.cash_modality:
            raise ShopError("Selecciona la modalidad de pago en efectivo")
        details["cash_modality"] = d.cash_modality
        if d.cash_modality == "advance_paid" and d.amount <= 0:
            raise ShopError("Indica el importe entregado")
        if d.cash_modality == "on_delivery":
            fields["amount_declared_usd"] = Decimal("0.00")
            details["settlement"] = "pending_on_delivery"   # el dinero aún no se ha cobrado
            flags.append("cash_on_delivery_not_collected")
    elif code == "usdt":
        cfg = pm.config or {}
        nets = cfg.get("networks") or {}
        if not nets or not cfg.get("address"):
            raise ShopError("El pago en USDT no está configurado por la tienda", 409)
        if d.network not in nets:
            raise ShopError("Selecciona una red válida")
        if not d.tx_hash:
            raise ShopError("Indica el hash o identificador de la transacción")
        if d.amount <= 0:
            raise ShopError("Indica la cantidad enviada")
        details.update({"network": d.network, "tx_hash": d.tx_hash, "amount_usdt": str(d.amount),
                        "receiving_address": cfg["address"]})
        fields["reference"] = d.tx_hash[:40]
    else:
        raise ShopError("Método de pago no soportado", 409)

    if code != "cash" or d.cash_modality == "advance_paid":
        if abs(fields["amount_declared_usd"] - order.total_usd) > Decimal("0.01"):
            flags.append("amount_mismatch")
    if fields["reference"]:
        dup = db.scalars(select(Order.number).join(Payment, Payment.order_id == Order.id)
                         .where(Payment.method_id == pm.id, func.lower(Payment.reference) == fields["reference"].lower(),
                                Payment.order_id != order.id, Payment.status != "rejected")).all()
        if dup:
            flags.append("duplicate_reference")
            details["duplicate_of_orders"] = sorted(set(dup))
    if code == "usdt" and details.get("tx_hash"):
        dup = db.scalars(select(Order.number).join(Payment, Payment.order_id == Order.id)
                         .where(Payment.method_id == pm.id, Payment.details["tx_hash"].astext == details["tx_hash"],
                                Payment.order_id != order.id, Payment.status != "rejected")).all()
        if dup and "duplicate_reference" not in flags:
            flags.append("duplicate_reference"); details["duplicate_of_orders"] = sorted(set(dup))
    details["flags"] = flags
    return fields, details, flags


def _own_order(db: DbSession, user: User, number: str, lock: bool = False) -> Order:
    q = select(Order).where(Order.number == number, Order.user_id == user.id).options(selectinload(Order.items))
    o = db.scalar(q.with_for_update() if lock else q)
    if not o:
        raise ShopError("Pedido no encontrado", 404)
    return o


def current_payment(db: DbSession, order_id: int) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.order_id == order_id).order_by(Payment.id.desc()))


def declare(db: DbSession, user: User, number: str, d, ip: str | None) -> Payment:
    order = _own_order(db, user, number, lock=True)
    if order.status != "pending_payment":
        raise ShopError("Este pedido no está esperando un pago", 409)
    pm = db.get(PaymentMethod, order.payment_method_id)
    if not pm or not pm.is_active:
        raise ShopError("El método de pago de este pedido ya no está disponible. Contacta a la tienda.", 409)
    if db.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == order.id, Payment.status == "rejected")) >= MAX_REJECTED:
        raise ShopError("Se alcanzó el máximo de intentos de pago. Contacta a la tienda.", 429)
    fields, details, flags = _validate(db, pm, order, d)
    pay = Payment(order_id=order.id, method_id=pm.id, status="declared", details=details, **fields)
    db.add(pay)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ShopError("Ya existe un pago registrado para este pedido", 409)
    _event(db, pay, "declared", user.id, d.note, {"flags": flags})
    change_status(db, order, "payment_validation", user.id, "Pago declarado por el cliente; pendiente de validación")
    order.reservation_expires_at = None   # la reserva ya no vence mientras el pago está en revisión
    _notify(db, user_id=user.id, audience="customer", kind="payment_declared", order=order,
            title=f"Recibimos tu pago declarado del pedido {order.number}",
            body="Un administrador lo verificará. Declarar un pago no equivale a que esté aprobado.")
    _notify(db, user_id=None, audience="staff", kind="payment_pending_review", order=order,
            title=f"Pago por validar · {order.number}", body=f"{pm.name} · {fields['amount_declared_usd']} USD" + (" · ⚠ " + ", ".join(flags) if flags else ""))
    audit(db, "payment.declared", user.id, "payment", pay.id, {"order": order.number, "method": pm.code}, ip)
    db.commit()
    return pay


def respond(db: DbSession, user: User, number: str, d, ip: str | None) -> Payment:
    """El cliente corrige o completa su pago cuando se le pidió información adicional."""
    order = _own_order(db, user, number, lock=True)
    pay = current_payment(db, order.id)
    if not pay or pay.status != "needs_info":
        raise ShopError("No hay una solicitud de información pendiente", 409)
    pm = db.get(PaymentMethod, pay.method_id)
    fields, details, flags = _validate(db, pm, order, d)
    for k, v in fields.items():
        setattr(pay, k, v)
    pay.details, pay.status = details, "declared"
    _event(db, pay, "customer_responded", user.id, d.note, {"flags": flags})
    _notify(db, user_id=None, audience="staff", kind="payment_pending_review", order=order,
            title=f"El cliente respondió · {order.number}", body="Pago actualizado, pendiente de validación")
    audit(db, "payment.customer_responded", user.id, "payment", pay.id, ip=ip)
    db.commit()
    return pay


def set_proof(db: DbSession, user: User, number: str, key: str) -> str | None:
    order = _own_order(db, user, number, lock=True)
    pay = current_payment(db, order.id)
    if not pay or pay.status not in ("declared", "pending_review", "needs_info"):
        raise ShopError("No se puede adjuntar un comprobante en este momento", 409)
    old, pay.proof_storage_key = pay.proof_storage_key, key
    _event(db, pay, "proof_uploaded", user.id)
    db.commit()
    return old


def consume_reservation(db: DbSession, order: Order, actor_id: int | None) -> None:
    """Pago aprobado: la reserva pasa a salida física de inventario."""
    pids = {i.product_id for i in order.items if i.product_id}
    rows = db.scalars(select(Inventory).where(Inventory.product_id.in_(pids)).order_by(Inventory.id).with_for_update()).all() if pids else []
    inv = {(r.product_id, r.variant_id): r for r in rows}
    for it in order.items:
        r = inv.get((it.product_id, it.variant_id))
        if not r or r.quantity_reserved < it.quantity or r.quantity_on_hand < it.quantity:
            raise ShopError("Inconsistencia de inventario al aprobar; revisa el stock del producto", 409)
        r.quantity_reserved -= it.quantity
        r.quantity_on_hand -= it.quantity
        db.add(InventoryMovement(inventory_id=r.id, delta=-it.quantity, reason="sale", order_id=order.id,
                                 user_id=actor_id, note=f"Venta pedido {order.number}"))


def review(db: DbSession, actor: User, payment_id: int, d, ip: str | None) -> Payment:
    pay = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if not pay:
        raise ShopError("Pago no encontrado", 404)
    order = db.scalar(select(Order).where(Order.id == pay.order_id).options(selectinload(Order.items)).with_for_update())
    pm = db.get(PaymentMethod, pay.method_id)
    note = (d.note or "").strip() or None
    act = d.action
    if act == "note":
        if not note:
            raise ShopError("Escribe la observación")
        _event(db, pay, "note", actor.id, note)
    elif act == "start_review":
        if pay.status != "declared":
            raise ShopError("Solo un pago declarado puede pasar a revisión", 409)
        pay.status = "pending_review"
        _event(db, pay, "start_review", actor.id, note)
    elif act == "request_info":
        if pay.status not in ("declared", "pending_review"):
            raise ShopError("No se puede solicitar información en este estado", 409)
        if not note or len(note) < 5:
            raise ShopError("Indica qué información necesitas del cliente")
        pay.status, pay.review_reason = "needs_info", note
        _event(db, pay, "info_requested", actor.id, note)
        _notify(db, user_id=order.user_id, audience="customer", kind="payment_needs_info", order=order,
                title=f"Necesitamos más información sobre tu pago ({order.number})", body=note)
    elif act == "reject":
        if pay.status not in ("declared", "pending_review", "needs_info"):
            raise ShopError("No se puede rechazar un pago en este estado", 409)
        if not note or len(note) < 5:
            raise ShopError("El motivo del rechazo es obligatorio")
        pay.status, pay.review_reason, pay.reviewed_by, pay.reviewed_at = "rejected", note, actor.id, now()
        _event(db, pay, "rejected", actor.id, note)
        change_status(db, order, "pending_payment", actor.id, f"Pago rechazado: {note}")
        order.reservation_expires_at = now() + timedelta(hours=settings.reservation_hours)
        _notify(db, user_id=order.user_id, audience="customer", kind="payment_rejected", order=order,
                title=f"Tu pago del pedido {order.number} fue rechazado", body=f"Motivo: {note}. Puedes declarar un nuevo pago.")
    elif act == "approve":
        if pay.status not in ("declared", "pending_review"):
            raise ShopError("Solo se aprueban pagos declarados o en revisión (si pediste información, espera la respuesta)", 409)
        if order.status != "payment_validation":
            raise ShopError("El pedido no está en validación de pago", 409)
        if not d.verified_with or len(d.verified_with.strip()) < 5:
            raise ShopError("Indica con qué medio verificaste que el dinero fue recibido")
        detail = {"verified_with": d.verified_with.strip()}
        if pm.code == "usdt":
            net = (pay.details or {}).get("network")
            need = int((((pm.config or {}).get("networks") or {}).get(net) or {}).get("min_confirmations", 20))
            if d.confirmations is None or d.confirmations < need:
                raise ShopError(f"En {net} se requieren al menos {need} confirmaciones para aprobar")
            detail["confirmations"] = d.confirmations
        pay.status, pay.reviewed_by, pay.reviewed_at = "approved", actor.id, now()
        pay.review_reason = note or d.verified_with.strip()
        pay.details = {**(pay.details or {}), "verification": detail}
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise ShopError("Esa referencia ya fue aprobada en otro pago; revisa un posible duplicado", 409)
        consume_reservation(db, order, actor.id)
        _event(db, pay, "approved", actor.id, note, detail)
        _notify(db, user_id=order.user_id, audience="customer", kind="payment_approved", order=order,
                title=f"Pago aprobado · pedido {order.number}", body="Pronto comenzaremos a preparar tu envío.")
    audit(db, f"payment.{act}", actor.id, "payment", pay.id, {"order": order.number}, ip)
    db.commit()
    return pay


def start_preparing(db: DbSession, actor: User, number: str, ip: str | None) -> Order:
    order = db.scalar(select(Order).where(Order.number == number).with_for_update())
    if not order:
        raise ShopError("Pedido no encontrado", 404)
    ok = db.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == order.id, Payment.status == "approved"))
    if not ok:
        raise ShopError("El pedido no tiene un pago aprobado", 409)
    change_status(db, order, "preparing", actor.id, "Pago aprobado; preparando el envío")
    _notify(db, user_id=order.user_id, audience="customer", kind="order_preparing", order=order,
            title=f"Estamos preparando tu pedido {order.number}")
    audit(db, "order.preparing", actor.id, "order", order.id, ip=ip)
    db.commit()
    return order
