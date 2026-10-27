from datetime import timedelta
from decimal import Decimal
from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session as DbSession, selectinload
from app.core.config import settings
from app.models import (Cart, CartItem, Inventory, InventoryMovement, Notification, Order, OrderEvent, OrderItem,
                        Payment, PaymentMethod, ShippingMethod, User, UserAddress)
from app.models.sales import order_number_seq
from app.services import catalog as cat
from app.services.audit import audit
from app.services.auth import now
from app.services.cart import ShopError, load_context, line_issue

# Flujo de estados autorizado. Los saltos no listados se rechazan.
ALLOWED = {
    "pending_payment": {"payment_validation", "cancelled"},
    "payment_validation": {"preparing", "pending_payment", "cancelled"},
    "preparing": {"shipped", "cancelled"},
    "shipped": {"out_for_delivery", "delivered"},
    "out_for_delivery": {"delivered"},
    "delivered": {"returned"},
}
ISSUE_TEXT = {"unavailable": "ya no está disponible", "out_of_stock": "está agotado",
              "insufficient_stock": "no tiene stock suficiente"}


def change_status(db: DbSession, order: Order, new: str, actor_id: int | None, note: str | None) -> None:
    if new not in ALLOWED.get(order.status, set()):
        raise ShopError(f"Transición no permitida: {order.status} → {new}", 409)
    order.status = new
    db.add(OrderEvent(order_id=order.id, status=new, note=note, actor_user_id=actor_id))


def _issues(ctx, items, avail_of) -> list[dict]:
    out = []
    for it in items:
        issue = line_issue(ctx, it, max(0, avail_of(it)))
        if issue:
            p = ctx["products"].get(it.product_id)
            out.append({"item_id": it.id, "issue": issue, "available": max(0, avail_of(it)),
                        "message": f"«{p.name if p else 'Producto'}» {ISSUE_TEXT[issue]}"})
    return out


def _refs(db: DbSession, user: User, address_id: int, shipping_id: int, payment_id: int):
    addr = db.scalar(select(UserAddress).where(UserAddress.id == address_id, UserAddress.user_id == user.id))
    if not addr:
        raise ShopError("La dirección de entrega no es válida")
    sm, pm = db.get(ShippingMethod, shipping_id), db.get(PaymentMethod, payment_id)
    if not sm or not sm.is_active:
        raise ShopError("El transportista seleccionado no está disponible")
    if not pm or not pm.is_active:
        raise ShopError("El método de pago seleccionado no está disponible")
    return addr, sm, pm


def summary(db: DbSession, user: User, address_id: int, shipping_id: int, payment_id: int) -> dict:
    """Vista previa del checkout. No reserva ni modifica nada; los importes los calcula el servidor."""
    from app.services.cart import build_view, get_cart
    view = build_view(db, get_cart(db, user))
    addr, sm, pm = _refs(db, user, address_id, shipping_id, payment_id)
    shipping = settings.shipping_flat_usd
    return {**view, "shipping_usd": shipping, "total_usd": view["subtotal_usd"] + shipping,
            "address": {"recipient_name": addr.recipient_name, "phone": addr.phone, "state": addr.state,
                        "municipality": addr.municipality, "full_address": addr.full_address,
                        "reference": addr.reference},
            "shipping_method": sm.name, "payment_method": pm.name,
            "shipping_note": "Costo de envío a coordinar con el transportista" if shipping == 0 else None}


def create_order(db: DbSession, user: User, address_id: int, shipping_id: int, payment_id: int,
                 notes: str | None, idem_key: str | None, ip: str | None) -> tuple[Order, bool]:
    if idem_key:
        prev = db.scalar(select(Order).where(Order.user_id == user.id, Order.idempotency_key == idem_key))
        if prev:
            return prev, False
    # Serializa checkouts simultáneos del mismo cliente
    cart = db.scalar(select(Cart).where(Cart.user_id == user.id).with_for_update())
    items = db.scalars(select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)).all() if cart else []
    if not items:
        raise ShopError("Tu carrito está vacío")
    addr, sm, pm = _refs(db, user, address_id, shipping_id, payment_id)
    ctx = load_context(db, items)
    # Bloqueo de filas de inventario en orden de id (evita interbloqueos); stock se verifica YA bloqueado
    inv_rows = db.scalars(select(Inventory).where(Inventory.product_id.in_({i.product_id for i in items}))
                          .order_by(Inventory.id).with_for_update()).all()
    inv = {(r.product_id, r.variant_id): r for r in inv_rows}
    avail_of = lambda it: (lambda r: (r.quantity_on_hand - r.quantity_reserved) if r else 0)(inv.get((it.product_id, it.variant_id)))
    problems = _issues(ctx, items, avail_of)
    if problems:
        db.rollback()
        raise ShopError("Algunos productos de tu carrito cambiaron. Revísalos antes de continuar.", 409, problems)

    shipping = settings.shipping_flat_usd
    lines = []
    for it in items:
        p, v = ctx["products"][it.product_id], ctx["variants"].get(it.variant_id) if it.variant_id else None
        unit = cat.unit_price(p, v)
        lines.append((it, p, v, unit))
    subtotal = sum((u * it.quantity for it, _, _, u in lines), Decimal("0.00"))
    order = Order(number=f"QS-{db.scalar(select(order_number_seq.next_value())):06d}", user_id=user.id,
                  status="pending_payment", subtotal_usd=subtotal, shipping_usd=shipping, total_usd=subtotal + shipping,
                  ship_recipient=addr.recipient_name, ship_phone=addr.phone, ship_state=addr.state,
                  ship_municipality=addr.municipality, ship_address=addr.full_address, ship_reference=addr.reference,
                  delivery_notes=notes, shipping_method_id=sm.id, payment_method_id=pm.id,
                  reservation_expires_at=now() + timedelta(hours=settings.reservation_hours),
                  idempotency_key=idem_key)
    db.add(order)
    db.flush()
    for it, p, v, unit in lines:
        db.add(OrderItem(order_id=order.id, product_id=p.id, variant_id=v.id if v else None, product_name=p.name,
                         sku=v.sku if v else p.sku,
                         description_snapshot=(p.short_description or (p.description or "")[:500] or None),
                         variant_snapshot=dict(v.attributes) if v else None, unit_price_usd=unit,
                         quantity=it.quantity, line_total_usd=unit * it.quantity))
        row = inv[(it.product_id, it.variant_id)]
        row.quantity_reserved += it.quantity     # reserva: el stock físico se descuenta al aprobar el pago
        db.add(InventoryMovement(inventory_id=row.id, delta=-it.quantity, reason="reserve", order_id=order.id,
                                 user_id=user.id, note=f"Reserva pedido {order.number}"))
    db.add(OrderEvent(order_id=order.id, status="pending_payment", note="Pedido creado", actor_user_id=user.id))
    db.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    db.add(Notification(user_id=user.id, audience="customer", kind="order_created", order_id=order.id,
                        title=f"Recibimos tu pedido {order.number}",
                        body="Registra tu pago para que podamos validarlo."))
    db.add(Notification(user_id=None, audience="staff", kind="new_order", order_id=order.id,
                        title=f"Nueva compra {order.number}", body=f"Total {order.total_usd} USD"))
    audit(db, "order.created", user.id, "order", order.id, {"number": order.number, "total": str(order.total_usd)}, ip)
    db.commit()
    return order, True


def release_reservation(db: DbSession, order: Order, actor_id: int | None, note: str) -> None:
    pids = {i.product_id for i in order.items if i.product_id}
    rows = db.scalars(select(Inventory).where(Inventory.product_id.in_(pids)).order_by(Inventory.id)
                      .with_for_update()).all() if pids else []
    inv = {(r.product_id, r.variant_id): r for r in rows}
    for it in order.items:
        r = inv.get((it.product_id, it.variant_id))
        if r:
            r.quantity_reserved = max(0, r.quantity_reserved - it.quantity)
            db.add(InventoryMovement(inventory_id=r.id, delta=it.quantity, reason="release", order_id=order.id,
                                     user_id=actor_id, note=note))


def cancel_unpaid(db: DbSession, order_id: int, actor_id: int | None, note: str, owner_id: int | None = None) -> Order:
    order = db.scalar(select(Order).where(Order.id == order_id).options(selectinload(Order.items)).with_for_update())
    if not order or (owner_id is not None and order.user_id != owner_id):
        raise ShopError("Pedido no encontrado", 404)
    if order.status != "pending_payment":
        raise ShopError("Este pedido ya no se puede cancelar desde aquí", 409)
    release_reservation(db, order, actor_id, note)
    change_status(db, order, "cancelled", actor_id, note)
    if order.user_id:
        db.add(Notification(user_id=order.user_id, audience="customer", kind="order_cancelled", order_id=order.id,
                            title=f"Pedido {order.number} cancelado", body=note))
    audit(db, "order.cancelled", actor_id, "order", order.id, {"note": note})
    db.commit()
    return order


def expire_unpaid_orders(db: DbSession) -> int:
    """Cancela pedidos sin pago declarado cuya reserva venció y libera su stock. Idempotente."""
    ids = db.scalars(select(Order.id).where(Order.status == "pending_payment",
                                            Order.reservation_expires_at < now(),
                                            ~exists().where(Payment.order_id == Order.id, Payment.status != "rejected"))).all()
    n = 0
    for oid in ids:
        try:
            cancel_unpaid(db, oid, None, "Reserva vencida sin pago declarado")
            n += 1
        except ShopError:
            db.rollback()
    return n
