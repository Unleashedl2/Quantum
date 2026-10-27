"""Integración Fase 4: carrito, checkout, reservas e inventario."""
import threading
from sqlalchemy import select
from tests.conftest import new_client
from tests.test_auth_flow import REG
from tests.test_catalog import _staff_headers

ADDR = {"recipient_name": "Ana", "phone": "+584121234567", "state": "Miranda", "municipality": "Chacao",
        "full_address": "Av. Principal casa 1"}
PASS = "Contraseña#Fuerte1"


def _customer(email, nid):
    c = new_client()
    assert c.post("/api/auth/register", json={**REG, "email": email, "national_id": nid}).status_code == 201
    r = c.post("/api/auth/login", json={"email": email, "password": PASS})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    addr = c.post("/api/me/addresses", json=ADDR, headers=h).json()["id"]
    return c, h, addr


def _product(client, sku, stock, price="20.00", sale=None):
    h = _staff_headers(client)
    cats = client.get("/api/admin/categories").json()
    cid = cats[0]["id"] if cats else client.post("/api/admin/categories", json={"name": "General"}, headers=h).json()["id"]
    body = {"category_id": cid, "name": f"Producto {sku}", "sku": sku, "price_usd": price, "initial_stock": stock,
            "status": "published", **({"sale_price_usd": sale} if sale else {})}
    r = client.post("/api/admin/products", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"], h


def _methods(c):
    return c.get("/api/shipping-methods").json()[0]["id"], c.get("/api/payment-methods").json()[0]["id"]


def _available(client, slug):
    return client.get(f"/api/products/{slug}").json()["available"]


def test_cart_limits_and_server_side_prices(client):
    pid, _ = _product(client, "CART-1", 3, price="20.00", sale="15.00")
    c, h, _a = _customer("c1@example.com", "V50000001")
    assert c.post("/api/cart/items", json={"product_id": pid, "quantity": 4}, headers=h).status_code == 409
    r = c.post("/api/cart/items", json={"product_id": pid, "quantity": 2, "unit_price_usd": "0.01"}, headers=h)
    assert r.status_code == 200
    v = r.json()
    assert v["items"][0]["unit_price_usd"] == "15.00" and v["subtotal_usd"] == "30.00"   # precio del servidor
    assert c.post("/api/cart/items", json={"product_id": pid, "quantity": 2}, headers=h).status_code == 409  # 2+2 > 3


def test_checkout_reserves_stock_and_keeps_historical_price(client):
    pid, sh = _product(client, "CHK-1", 5, price="30.00")
    c, h, addr = _customer("c2@example.com", "V50000002")
    c.post("/api/cart/items", json={"product_id": pid, "quantity": 2}, headers=h)
    ship, pay = _methods(c)
    body = {"address_id": addr, "shipping_method_id": ship, "payment_method_id": pay}
    s = c.post("/api/checkout/summary", json=body, headers=h).json()
    assert s["total_usd"] == "60.00"
    r = c.post("/api/orders", json=body, headers={**h, "Idempotency-Key": "abc-123"})
    assert r.status_code == 201
    o = r.json()
    assert o["status"] == "pending_payment" and o["total_usd"] == "60.00"
    # doble envío con la misma clave: no duplica
    r2 = c.post("/api/orders", json=body, headers={**h, "Idempotency-Key": "abc-123"})
    assert r2.status_code == 200 and r2.json()["number"] == o["number"]
    slug = client.get("/api/admin/products", params={"q": "CHK-1"}).json()["items"][0]["slug"]
    assert _available(client, slug) == 3                          # 5 - 2 reservadas
    assert c.get("/api/cart").json()["items"] == []               # carrito vaciado
    # El administrador cambia el precio: el pedido conserva el original
    client.patch(f"/api/admin/products/{pid}", json={"price_usd": "99.00", "name": "Renombrado"}, headers=sh)
    d = c.get(f"/api/orders/{o['number']}").json()
    assert d["items"][0]["unit_price_usd"] == "30.00" and d["items"][0]["product_name"] == "Producto CHK-1"


def test_last_unit_cannot_be_oversold_concurrently(client):
    pid, _ = _product(client, "RACE-1", 1)
    users = [_customer(f"race{i}@example.com", f"V6000000{i}") for i in range(2)]
    ship, pay = _methods(users[0][0])
    for c, h, _a in users:
        assert c.post("/api/cart/items", json={"product_id": pid, "quantity": 1}, headers=h).status_code == 200
    results, barrier = [], threading.Barrier(2)

    def buy(c, h, addr):
        barrier.wait()
        results.append(c.post("/api/orders", json={"address_id": addr, "shipping_method_id": ship,
                                                   "payment_method_id": pay}, headers=h).status_code)
    ts = [threading.Thread(target=buy, args=u) for u in users]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(results) == [201, 409]                          # solo uno se queda con la última unidad
    from app.db.session import SessionLocal
    from app.models import Inventory
    with SessionLocal() as db:
        inv = db.scalar(select(Inventory).where(Inventory.product_id == pid, Inventory.variant_id.is_(None)))
        assert inv.quantity_reserved == 1 and inv.quantity_on_hand == 1


def test_orders_are_private_and_cancel_releases_stock(client):
    pid, _ = _product(client, "CAN-1", 4)
    a, ha, addr_a = _customer("own@example.com", "V70000001")
    b, hb, _ = _customer("other@example.com", "V70000002")
    a.post("/api/cart/items", json={"product_id": pid, "quantity": 3}, headers=ha)
    ship, pay = _methods(a)
    o = a.post("/api/orders", json={"address_id": addr_a, "shipping_method_id": ship, "payment_method_id": pay},
               headers=ha).json()
    assert b.get(f"/api/orders/{o['number']}").status_code == 404           # ajeno
    assert b.post(f"/api/orders/{o['number']}/cancel", headers=hb).status_code == 404
    slug = client.get("/api/admin/products", params={"q": "CAN-1"}).json()["items"][0]["slug"]
    assert _available(client, slug) == 1
    assert a.post(f"/api/orders/{o['number']}/cancel", headers=ha).json()["status"] == "cancelled"
    assert _available(client, slug) == 4                                    # stock liberado
    assert a.post(f"/api/orders/{o['number']}/cancel", headers=ha).status_code == 409   # no se cancela dos veces


def test_expired_reservations_are_released(client):
    pid, _ = _product(client, "EXP-1", 2)
    c, h, addr = _customer("exp@example.com", "V80000001")
    c.post("/api/cart/items", json={"product_id": pid, "quantity": 2}, headers=h)
    ship, pay = _methods(c)
    o = c.post("/api/orders", json={"address_id": addr, "shipping_method_id": ship, "payment_method_id": pay},
               headers=h).json()
    from sqlalchemy import update
    from app.db.session import SessionLocal
    from app.models import Order
    from app.services.auth import now
    from datetime import timedelta
    from app.services.orders import expire_unpaid_orders
    with SessionLocal() as db:
        db.execute(update(Order).where(Order.number == o["number"]).values(reservation_expires_at=now() - timedelta(hours=1)))
        db.commit()
        assert expire_unpaid_orders(db) >= 1
    assert c.get(f"/api/orders/{o['number']}").json()["status"] == "cancelled"
    slug = client.get("/api/admin/products", params={"q": "EXP-1"}).json()["items"][0]["slug"]
    assert _available(client, slug) == 2


def test_empty_cart_and_foreign_address_rejected(client):
    c, h, _a = _customer("empty@example.com", "V90000001")
    other, ho, other_addr = _customer("empty2@example.com", "V90000002")
    ship, pay = _methods(c)
    assert c.post("/api/orders", json={"address_id": other_addr, "shipping_method_id": ship,
                                       "payment_method_id": pay}, headers=h).status_code == 400
