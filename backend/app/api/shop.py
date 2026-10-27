from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession, selectinload
from app.api.deps import client_ip, ready_user
from app.db.session import get_db
from app.models import Order, OrderEvent, PaymentMethod, ShippingMethod, User
from app.schemas.shop import CartAddIn, CartSetIn, CheckoutIn
from app.services import cart as cart_svc
from app.services import orders as order_svc
from app.services.cart import ShopError

router = APIRouter(prefix="/api", tags=["shop"])


def _fail(e: ShopError):
    detail = {"message": e.message, "issues": e.issues} if e.issues else e.message
    raise HTTPException(e.status, detail)


# ---------- métodos disponibles ----------
@router.get("/shipping-methods")
def shipping_methods(response: Response, db: DbSession = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=60"
    rows = db.scalars(select(ShippingMethod).where(ShippingMethod.is_active.is_(True)).order_by(ShippingMethod.id)).all()
    return [{"id": r.id, "code": r.code, "name": r.name} for r in rows]


@router.get("/payment-methods")
def payment_methods(response: Response, db: DbSession = Depends(get_db)):
    """No expone `config` (cuentas receptoras): se muestra solo tras crear el pedido (Fase 5)."""
    response.headers["Cache-Control"] = "public, max-age=60"
    rows = db.scalars(select(PaymentMethod).where(PaymentMethod.is_active.is_(True)).order_by(PaymentMethod.id)).all()
    return [{"id": r.id, "code": r.code, "name": r.name, "instructions": r.instructions} for r in rows]


# ---------- carrito ----------
@router.get("/cart")
def get_cart(user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    view = cart_svc.build_view(db, cart_svc.get_cart(db, user))
    db.commit()
    return view


@router.post("/cart/items")
def add_to_cart(data: CartAddIn, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    try:
        cart_svc.add_item(db, user, data.product_id, data.variant_id, data.quantity)
    except ShopError as e:
        _fail(e)
    return cart_svc.build_view(db, cart_svc.get_cart(db, user))


@router.patch("/cart/items/{item_id}")
def set_cart_item(item_id: int, data: CartSetIn, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    try:
        cart_svc.set_quantity(db, user, item_id, data.quantity)
    except ShopError as e:
        _fail(e)
    return cart_svc.build_view(db, cart_svc.get_cart(db, user))


@router.delete("/cart/items/{item_id}")
def delete_cart_item(item_id: int, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    try:
        cart_svc.remove_item(db, user, item_id)
    except ShopError as e:
        _fail(e)
    return cart_svc.build_view(db, cart_svc.get_cart(db, user))


# ---------- checkout y pedidos ----------
@router.post("/checkout/summary")
def checkout_summary(data: CheckoutIn, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    try:
        return order_svc.summary(db, user, data.address_id, data.shipping_method_id, data.payment_method_id)
    except ShopError as e:
        _fail(e)


def _order_out(db: DbSession, o: Order, detail: bool = True) -> dict:
    base = {"id": o.id, "number": o.number, "status": o.status, "subtotal_usd": o.subtotal_usd,
            "shipping_usd": o.shipping_usd, "total_usd": o.total_usd, "created_at": o.created_at,
            "reservation_expires_at": o.reservation_expires_at, "item_count": sum(i.quantity for i in o.items)}
    if not detail:
        return base
    events = db.scalars(select(OrderEvent).where(OrderEvent.order_id == o.id).order_by(OrderEvent.id)).all()
    sm = db.get(ShippingMethod, o.shipping_method_id) if o.shipping_method_id else None
    pm = db.get(PaymentMethod, o.payment_method_id) if o.payment_method_id else None
    return {**base,
            "items": [{"product_name": i.product_name, "sku": i.sku, "variant": i.variant_snapshot,
                       "unit_price_usd": i.unit_price_usd, "quantity": i.quantity,
                       "line_total_usd": i.line_total_usd} for i in o.items],
            "shipping": {"recipient": o.ship_recipient, "phone": o.ship_phone, "state": o.ship_state,
                         "municipality": o.ship_municipality, "address": o.ship_address,
                         "reference": o.ship_reference, "notes": o.delivery_notes,
                         "carrier": sm.name if sm else None},
            "payment_method": pm.name if pm else None,
            "events": [{"status": e.status, "note": e.note, "at": e.created_at} for e in events]}


@router.post("/orders", status_code=201)
def create_order(data: CheckoutIn, request: Request, response: Response, user: User = Depends(ready_user),
                 idempotency_key: str | None = Header(default=None, max_length=64), db: DbSession = Depends(get_db)):
    try:
        order, created = order_svc.create_order(db, user, data.address_id, data.shipping_method_id,
                                                data.payment_method_id, data.delivery_notes, idempotency_key,
                                                client_ip(request))
    except ShopError as e:
        _fail(e)
    if not created:
        response.status_code = 200   # misma solicitud repetida: devuelve el pedido original
    o = db.scalar(select(Order).where(Order.id == order.id).options(selectinload(Order.items)))
    return _order_out(db, o)


@router.get("/orders")
def my_orders(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=50),
              user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Order).where(Order.user_id == user.id)) or 0
    rows = db.scalars(select(Order).where(Order.user_id == user.id).options(selectinload(Order.items))
                      .order_by(Order.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [_order_out(db, o, detail=False) for o in rows], "total": total, "page": page,
            "page_size": page_size}


@router.get("/orders/{number}")
def order_detail(number: str, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    o = db.scalar(select(Order).where(Order.number == number, Order.user_id == user.id)
                  .options(selectinload(Order.items)))
    if not o:   # 404 también para pedidos ajenos: no revela su existencia
        raise HTTPException(404, "Pedido no encontrado")
    return _order_out(db, o)


@router.post("/orders/{number}/cancel")
def cancel_order(number: str, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    o = db.scalar(select(Order).where(Order.number == number, Order.user_id == user.id))
    if not o:
        raise HTTPException(404, "Pedido no encontrado")
    try:
        order_svc.cancel_unpaid(db, o.id, user.id, "Cancelado por el cliente", owner_id=user.id)
    except ShopError as e:
        _fail(e)
    o = db.scalar(select(Order).where(Order.id == o.id).options(selectinload(Order.items)))
    return _order_out(db, o)
