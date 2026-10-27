"""Integración Fase 5: declaración, validación administrativa, bancos y notificaciones."""
from datetime import date
from sqlalchemy import select
from tests.test_orders import ADDR, PASS, _available, _customer, _methods, _product
from tests.test_catalog import _staff_headers

TX = "a" * 64


def _master(client):
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models import Role, User
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == "master-t@example.com")):
            db.add(User(first_name="M", last_name="T", email="master-t@example.com", is_staff=True,
                        password_hash=hash_password("ClaveMaster#2026x"),
                        roles=[db.scalar(select(Role).where(Role.name == "master"))]))
            db.commit()
    r = client.post("/api/auth/login", json={"email": "master-t@example.com", "password": "ClaveMaster#2026x"})
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _method_id(c, code):
    return next(m["id"] for m in c.get("/api/payment-methods").json() if m["code"] == code)


def _order(client, sku, stock=5, qty=1, code="bank_transfer", price="20.00"):
    pid, _ = _product(client, sku, stock, price=price)
    c, h, addr = _customer(f"{sku.lower()}@example.com", "V" + str(abs(hash(sku)))[:8].ljust(8, "1"))
    c.post("/api/cart/items", json={"product_id": pid, "quantity": qty}, headers=h)
    ship, _p = _methods(c)
    o = c.post("/api/orders", json={"address_id": addr, "shipping_method_id": ship,
                                    "payment_method_id": _method_id(c, code)}, headers=h).json()
    return c, h, o["number"], pid


def _banks(c):
    b = c.get("/api/banks").json()
    return b[0]["id"], b[1]["id"]


def _declare_body(c, ref, amount="20.00"):
    o, r = _banks(c)
    return {"origin_bank_id": o, "receiving_bank_id": r, "reference": ref, "paid_at": date.today().isoformat(), "amount": amount}


def _slug(client, sku):
    return client.get("/api/admin/products", params={"q": sku}).json()["items"][0]["slug"]


def test_declared_payment_is_not_approved_and_stock_stays_reserved(client):
    c, h, num, pid = _order(client, "PAY-1", stock=5, qty=2, price="20.00")
    r = c.post(f"/api/orders/{num}/payment", json=_declare_body(c, "REF-0001", "40.00"), headers=h)
    assert r.status_code == 201 and r.json()["status"] == "declared"
    assert c.get(f"/api/orders/{num}").json()["status"] == "payment_validation"
    assert c.post(f"/api/orders/{num}/payment", json=_declare_body(c, "REF-0002", "40.00"), headers=h).status_code in (409,)
    _staff_headers(client)
    assert _available(client, _slug(client, "PAY-1")) == 3          # sigue reservado, no vendido
    assert c.post(f"/api/orders/{num}/cancel", headers=h).status_code == 409   # no cancela con pago en revisión


def test_customer_cannot_review_and_approval_requires_evidence(client):
    c, h, num, pid = _order(client, "PAY-2", stock=3, qty=1)
    pay = c.post(f"/api/orders/{num}/payment", json=_declare_body(c, "REF-1001"), headers=h).json()
    assert c.post(f"/api/admin/payments/{pay['id']}/review", json={"action": "approve", "verified_with": "x" * 10}, headers=h).status_code == 403
    ah = _staff_headers(client)
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json={"action": "approve"}, headers=ah).status_code == 400
    r = client.post(f"/api/admin/payments/{pay['id']}/review",
                    json={"action": "approve", "verified_with": "Estado de cuenta Banesco"}, headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    from app.db.session import SessionLocal
    from app.models import Inventory, Payment
    with SessionLocal() as db:
        inv = db.scalar(select(Inventory).where(Inventory.product_id == pid, Inventory.variant_id.is_(None)))
        assert (inv.quantity_on_hand, inv.quantity_reserved) == (2, 0)       # stock físico descontado
        p = db.get(Payment, pay["id"])
        assert p.reviewed_by is not None and p.reviewed_at is not None       # auditoría del revisor
    # el pedido no avanza solo: el admin lo pasa a preparación
    assert c.get(f"/api/orders/{num}").json()["status"] == "payment_validation"
    assert client.post(f"/api/admin/orders/{num}/prepare", headers=ah).json()["status"] == "preparing"
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json={"action": "approve", "verified_with": "otra vez!"},
                       headers=ah).status_code == 409                          # no se aprueba dos veces


def test_reject_returns_order_to_pending_and_allows_new_declaration(client):
    c, h, num, pid = _order(client, "PAY-3", stock=2)
    pay = c.post(f"/api/orders/{num}/payment", json=_declare_body(c, "REF-2001"), headers=h).json()
    ah = _staff_headers(client)
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json={"action": "reject"}, headers=ah).status_code == 400  # motivo obligatorio
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json={"action": "reject", "note": "No aparece en el banco"}, headers=ah).status_code == 200
    d = c.get(f"/api/orders/{num}").json()
    assert d["status"] == "pending_payment" and d["reservation_expires_at"] is not None
    assert c.get(f"/api/orders/{num}/payment").json()["payment"]["reason"] == "No aparece en el banco"
    assert c.post(f"/api/orders/{num}/payment", json=_declare_body(c, "REF-2002"), headers=h).status_code == 201


def test_request_info_flow_blocks_approval_until_customer_responds(client):
    c, h, num, pid = _order(client, "PAY-4", stock=2)
    pay = c.post(f"/api/orders/{num}/payment", json=_declare_body(c, "REF-3001"), headers=h).json()
    ah = _staff_headers(client)
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json={"action": "request_info", "note": "Falta el banco receptor"}, headers=ah).status_code == 200
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json={"action": "approve", "verified_with": "estado de cuenta"}, headers=ah).status_code == 409
    assert c.put(f"/api/orders/{num}/payment", json=_declare_body(c, "REF-3001"), headers=h).json()["status"] == "declared"
    notes = c.get("/api/notifications").json()
    assert any(n["kind"] == "payment_needs_info" for n in notes["items"]) and notes["unread"] >= 1


def test_usdt_requires_network_hash_and_confirmations(client):
    mh = _master(client)
    mid = _method_id(client, "usdt")
    cfg = {"is_active": True, "config": {"address": "T" + "A" * 33, "networks": {"TRC20": {"min_confirmations": 20}}}}
    assert client.put(f"/api/admin/payment-methods/{mid}", json=cfg, headers=mh).status_code == 200
    c, h, num, pid = _order(client, "PAY-5", stock=2, code="usdt")
    assert c.post(f"/api/orders/{num}/payment", json={"amount": "20", "network": "TRC20"}, headers=h).status_code == 400   # sin hash
    pay = c.post(f"/api/orders/{num}/payment", json={"amount": "20", "network": "TRC20", "tx_hash": TX}, headers=h).json()
    ah = _staff_headers(client)
    body = {"action": "approve", "verified_with": "Explorador TRONSCAN"}
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json=body, headers=ah).status_code == 400
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json={**body, "confirmations": 5}, headers=ah).status_code == 400
    assert client.post(f"/api/admin/payments/{pay['id']}/review", json={**body, "confirmations": 25}, headers=ah).status_code == 200


def test_duplicate_reference_is_flagged_and_cannot_be_approved_twice(client):
    c1, h1, n1, _ = _order(client, "PAY-6", stock=2)
    c2, h2, n2, _ = _order(client, "PAY-7", stock=2)
    p1 = c1.post(f"/api/orders/{n1}/payment", json=_declare_body(c1, "SAME-9001"), headers=h1).json()
    p2 = c2.post(f"/api/orders/{n2}/payment", json=_declare_body(c2, "same-9001"), headers=h2).json()
    ah = _staff_headers(client)
    flags = [i["flags"] for i in client.get("/api/admin/payments", params={"q": n2}, headers=ah).json()["items"]][0]
    assert "duplicate_reference" in flags
    ok = {"action": "approve", "verified_with": "estado de cuenta"}
    assert client.post(f"/api/admin/payments/{p1['id']}/review", json=ok, headers=ah).status_code == 200
    assert client.post(f"/api/admin/payments/{p2['id']}/review", json=ok, headers=ah).status_code == 409


def test_validation_rules_and_cash_on_delivery(client):
    c, h, num, _ = _order(client, "PAY-8", stock=2)
    body = _declare_body(c, "REF-5001")
    assert c.post(f"/api/orders/{num}/payment", json={**body, "paid_at": "2999-01-01"}, headers=h).status_code == 400
    assert c.post(f"/api/orders/{num}/payment", json={**body, "origin_bank_id": 999999}, headers=h).status_code == 400
    assert c.post(f"/api/orders/{num}/payment", json={**body, "reference": "!"}, headers=h).status_code == 422
    c2, h2, n2, _ = _order(client, "PAY-9", stock=2, code="cash")
    r = c2.post(f"/api/orders/{n2}/payment", json={"amount": "0", "cash_modality": "on_delivery"}, headers=h2)
    assert r.status_code == 201
    ah = _staff_headers(client)
    item = client.get("/api/admin/payments", params={"q": n2}, headers=ah).json()["items"][0]
    assert "cash_on_delivery_not_collected" in item["flags"]


def test_banks_admin_and_privacy_of_payments(client):
    ah = _staff_headers(client)
    assert client.get("/api/admin/banks", headers=ah).status_code == 403          # Admin no gestiona bancos
    mh = _master(client)
    assert client.post("/api/admin/banks", json={"code": "0999", "name": "Banco de Prueba"}, headers=mh).status_code == 201
    assert client.post("/api/admin/banks", json={"code": "0999", "name": "Duplicado"}, headers=mh).status_code == 409
    assert any(b["code"] == "0999" for b in client.get("/api/banks", params={"q": "Prueba"}).json())
    c1, h1, n1, _ = _order(client, "PAY-10", stock=2)
    c2, h2, n2, _ = _order(client, "PAY-11", stock=2)
    assert c2.get(f"/api/orders/{n1}/payment").status_code == 404
    assert c2.post(f"/api/orders/{n1}/payment", json=_declare_body(c2, "REF-7001"), headers=h2).status_code == 404
