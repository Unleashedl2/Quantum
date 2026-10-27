from sqlalchemy import select
from tests.test_auth_flow import REG


def _login(client, email, pw):
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def test_reset_flow_revokes_sessions_and_token_is_single_use(client):
    from app.db.session import SessionLocal
    from app.models import EmailOutbox, PasswordResetToken
    from app.services import tokens
    from app.models import User
    reg = {**REG, "email": "luis@example.com", "national_id": "V22222222"}
    assert client.post("/api/auth/register", json=reg).status_code == 201
    hdr = _login(client, reg["email"], reg["password"])
    assert client.get("/api/me/profile").status_code == 200
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == reg["email"]))
        raw = tokens.issue_token(db, u, "reset", 60); db.commit()
    new_pw = "NuevaClave#2026x"
    assert client.post("/api/auth/reset-password", json={"token": raw, "new_password": new_pw}).status_code == 204
    assert client.post("/api/auth/reset-password", json={"token": raw, "new_password": new_pw}).status_code == 400
    assert client.get("/api/me/profile").status_code == 401        # sesión anterior revocada
    _login(client, reg["email"], new_pw)


def test_forgot_password_does_not_reveal_accounts(client):
    a = client.post("/api/auth/forgot-password", json={"email": "no-existe@example.com"})
    b = client.post("/api/auth/forgot-password", json={"email": REG["email"]})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()


def test_address_isolation_between_customers(client):
    addr = {"recipient_name": "Ana", "phone": "+584121234567", "state": "Miranda", "municipality": "Chacao",
            "full_address": "Av. Principal casa 1"}
    hdr = _login(client, "luis@example.com", "NuevaClave#2026x")
    aid = client.post("/api/me/addresses", json=addr, headers=hdr).json()["id"]
    client.post("/api/auth/logout", headers=hdr)
    reg2 = {**REG, "email": "maria@example.com", "national_id": "V33333333"}
    client.post("/api/auth/register", json=reg2)
    hdr2 = _login(client, reg2["email"], reg2["password"])
    assert client.put(f"/api/me/addresses/{aid}", json=addr, headers=hdr2).status_code == 404
    assert client.delete(f"/api/me/addresses/{aid}", headers=hdr2).status_code == 404


def test_customer_cannot_use_staff_endpoints(client):
    hdr = _login(client, "maria@example.com", REG["password"])
    assert client.get("/api/staff").status_code == 403
