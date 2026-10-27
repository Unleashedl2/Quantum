"""Integración Fase 3. Requiere TEST_DATABASE_URL (ver README)."""
from sqlalchemy import select
from tests.test_auth_flow import REG


def _staff_headers(client):
    from app.cli import init_system
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models import Role, User
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == "cat-admin@example.com")):
            role = db.scalar(select(Role).where(Role.name == "admin"))
            db.add(User(first_name="Cat", last_name="Admin", email="cat-admin@example.com", is_staff=True,
                        password_hash=hash_password("ClaveAdmin#2026x"), roles=[role]))
            db.commit()
    r = client.post("/api/auth/login", json={"email": "cat-admin@example.com", "password": "ClaveAdmin#2026x"})
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def test_catalog_end_to_end(client):
    h = _staff_headers(client)
    cat = client.post("/api/admin/categories", json={"name": "Tecnología y electrónica"}, headers=h).json()
    sub = client.post("/api/admin/categories", json={"name": "Audio", "parent_id": cat["id"]}, headers=h).json()
    base = {"category_id": sub["id"], "name": "Auriculares Aura X2", "brand": "Aura", "sku": "AUR-X2",
            "price_usd": "60.00", "sale_price_usd": "45.00", "initial_stock": 10, "status": "published",
            "short_description": "Bluetooth con cancelación de ruido"}
    p = client.post("/api/admin/products", json=base, headers=h)
    assert p.status_code == 201
    assert client.post("/api/admin/products", json=base, headers=h).status_code == 409        # SKU único
    bad = {**base, "sku": "BAD-1", "sale_price_usd": "70.00"}
    assert client.post("/api/admin/products", json=bad, headers=h).status_code == 422          # oferta < precio

    # Búsqueda por nombre/marca/descr, filtro por categoría padre (incluye hijas), precio y orden
    assert client.get("/api/products", params={"q": "aura"}).json()["total"] == 1
    assert client.get("/api/products", params={"q": "cancelación"}).json()["total"] == 1
    assert client.get("/api/products", params={"category_id": cat["id"]}).json()["total"] == 1
    assert client.get("/api/products", params={"min_price": 50}).json()["total"] == 0          # usa precio efectivo (45)
    assert client.get("/api/products", params={"q": "100%"}).json()["total"] == 0              # comodines escapados

    slug = p.json()["slug"]
    d = client.get(f"/api/products/{slug}").json()
    assert d["available"] == 10 and d["effective_price_usd"] == "45.00"

    # Inventario: no puede quedar negativo
    pid = p.json()["id"]
    assert client.post(f"/api/admin/products/{pid}/inventory", json={"delta": -11, "reason": "adjustment"},
                       headers=h).status_code == 409
    assert client.post(f"/api/admin/products/{pid}/inventory", json={"delta": -4, "reason": "adjustment"},
                       headers=h).json()["quantity_on_hand"] == 6

    # Archivado lógico: desaparece de lo público
    assert client.post(f"/api/admin/products/{pid}/archive", headers=h).status_code == 204
    assert client.get(f"/api/products/{slug}").status_code == 404

    # Categoría con dependencias no se elimina
    assert client.delete(f"/api/admin/categories/{cat['id']}", headers=h).status_code == 409


def test_customers_cannot_manage_catalog(client):
    client.post("/api/auth/register", json={**REG, "email": "cli@example.com", "national_id": "V44444444"})
    r = client.post("/api/auth/login", json={"email": "cli@example.com", "password": REG["password"]})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    assert client.post("/api/admin/categories", json={"name": "Hack"}, headers=h).status_code == 403


def test_upload_rejects_fake_images_and_unconfigured_storage(client):
    from app.services.storage import InvalidUpload, sniff_image
    import pytest
    assert sniff_image(b"\x89PNG\r\n\x1a\n....")[0] == "image/png"
    with pytest.raises(InvalidUpload):
        sniff_image(b"<script>alert(1)</script>")
