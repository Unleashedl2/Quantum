from app.core.security import hash_password, validate_password_strength, verify_password


def test_argon2id_hash_and_verify():
    h = hash_password("Contraseña#Fuerte1")
    assert h.startswith("$argon2id$")
    assert verify_password("Contraseña#Fuerte1", h)
    assert not verify_password("otra", h)
    assert not verify_password("x", None)


def test_temp_password_is_not_valid_as_permanent():
    # '123456' solo se acepta en el comando de inicialización; nunca como contraseña elegida
    assert validate_password_strength("123456") is not None
    assert validate_password_strength("Contraseña#Fuerte1") is None
