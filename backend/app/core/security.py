import hashlib
import hmac
import re
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()  # Argon2id por defecto
_DUMMY_HASH = _ph.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    """Verifica contra un hash señuelo si el usuario no existe (mitiga enumeración por tiempo)."""
    try:
        ok = _ph.verify(hashed or _DUMMY_HASH, password)
        return bool(ok) and hashed is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


def validate_password_strength(pw: str) -> str | None:
    """Devuelve un mensaje de error o None si es válida."""
    if len(pw) < 12:
        return "La contraseña debe tener al menos 12 caracteres"
    if not re.search(r"[a-z]", pw) or not re.search(r"[A-Z]", pw):
        return "Debe incluir mayúsculas y minúsculas"
    if not re.search(r"\d", pw):
        return "Debe incluir al menos un número"
    if not re.search(r"[^\w\s]", pw):
        return "Debe incluir al menos un símbolo"
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Los tokens de sesión/reset se guardan solo como hash SHA-256."""
    return hashlib.sha256(token.encode()).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
