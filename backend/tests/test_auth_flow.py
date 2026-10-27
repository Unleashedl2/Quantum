REG = {"first_name": "Ana", "last_name": "Pérez", "national_id": "V12345678", "state": "Miranda",
       "municipality": "Chacao", "address": "Av. Principal, casa 1", "phone": "+584121234567",
       "email": "ana@example.com", "password": "Contraseña#Fuerte1", "password_confirm": "Contraseña#Fuerte1",
       "accept_terms": True}


def test_register_login_me_logout(client):
    assert client.post("/api/auth/register", json=REG).status_code == 201
    assert client.post("/api/auth/register", json=REG).status_code == 409        # sin duplicados
    r = client.post("/api/auth/login", json={"email": REG["email"], "password": REG["password"]})
    assert r.status_code == 200 and "national_id" not in r.json()                # cédula no se expone
    csrf = r.json()["csrf_token"]
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 403                     # sin CSRF
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401                          # sesión revocada


def test_lockout_after_repeated_failures(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"email": REG["email"], "password": "mala"})
    r = client.post("/api/auth/login", json={"email": REG["email"], "password": REG["password"]})
    assert r.status_code == 401
