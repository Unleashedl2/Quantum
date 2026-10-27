from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession
from app.core.config import settings
from app.core.security import (hash_password, needs_rehash, new_token, token_hash, validate_password_strength,
                               verify_password)
from app.models import Role, Session, User
from app.services.audit import audit


def now() -> datetime:
    return datetime.now(timezone.utc)


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


def register_customer(db: DbSession, data, ip: str | None) -> User:
    if not data.accept_terms:
        raise AuthError("Debes aceptar las condiciones y la política de privacidad")
    if data.password != data.password_confirm:
        raise AuthError("Las contraseñas no coinciden")
    if (msg := validate_password_strength(data.password)):
        raise AuthError(msg)
    exists = db.scalar(select(User.id).where((User.email == data.email) | (User.national_id == data.national_id)))
    if exists:
        # Mensaje genérico: no revela cuál dato ya existe
        raise AuthError("No fue posible completar el registro con los datos suministrados", 409)
    role = db.scalar(select(Role).where(Role.name == "customer"))
    user = User(first_name=data.first_name.strip(), last_name=data.last_name.strip(), national_id=data.national_id,
                state=data.state, municipality=data.municipality, address=data.address, phone=data.phone,
                email=data.email, password_hash=hash_password(data.password), accepted_terms_at=now(),
                roles=[role] if role else [])
    db.add(user)
    db.flush()
    audit(db, "user.register", user.id, "user", user.id, ip=ip)
    db.commit()
    return user


def login(db: DbSession, email: str, password: str, ip: str | None, ua: str | None) -> tuple[User, str, Session]:
    user = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user and user.locked_until and user.locked_until > now():
        audit(db, "auth.login_locked", user.id, ip=ip); db.commit()
        raise AuthError("Credenciales inválidas o cuenta temporalmente bloqueada", 401)
    ok = verify_password(password, user.password_hash if user else None)
    if not user or not ok or not user.is_active:
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_attempts:
                user.locked_until = now() + timedelta(minutes=settings.login_lock_minutes)
                user.failed_login_count = 0
                audit(db, "auth.account_locked", user.id, ip=ip)
            audit(db, "auth.login_failed", user.id, ip=ip)
            db.commit()
        raise AuthError("Credenciales inválidas o cuenta temporalmente bloqueada", 401)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now()
    token = new_token()
    sess = Session(user_id=user.id, token_hash=token_hash(token), csrf_token=new_token(), ip=ip,
                   user_agent=(ua or "")[:300], expires_at=now() + timedelta(hours=settings.session_ttl_hours))
    db.add(sess)
    audit(db, "auth.login", user.id, ip=ip)
    db.commit()
    return user, token, sess


def get_session(db: DbSession, token: str | None) -> tuple[Session, User] | None:
    if not token:
        return None
    s = db.scalar(select(Session).where(Session.token_hash == token_hash(token)))
    if not s or s.revoked_at or s.expires_at <= now():
        return None
    u = db.get(User, s.user_id)
    if not u or not u.is_active or u.deleted_at:
        return None
    return s, u


def revoke_session(db: DbSession, s: Session) -> None:
    s.revoked_at = now()
    db.commit()


def change_password(db: DbSession, user: User, current: str, new: str, keep_session_id: int, ip: str | None) -> None:
    if not verify_password(current, user.password_hash):
        raise AuthError("La contraseña actual no es correcta", 400)
    if (msg := validate_password_strength(new)):
        raise AuthError(msg)
    if verify_password(new, user.password_hash):
        raise AuthError("La nueva contraseña debe ser distinta de la actual")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    # Cierra todas las demás sesiones del usuario
    db.execute(update(Session).where(Session.user_id == user.id, Session.id != keep_session_id,
                                     Session.revoked_at.is_(None)).values(revoked_at=now()))
    audit(db, "auth.password_changed", user.id, "user", user.id, ip=ip)
    db.commit()
