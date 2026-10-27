from datetime import timedelta
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession
from app.core.config import settings
from app.core.security import hash_password, new_token, token_hash, validate_password_strength
from app.models import EmailOutbox, PasswordResetToken, Session, User
from app.services.audit import audit
from app.services.auth import AuthError, now
import logging

log = logging.getLogger("quantumstore.mail")


def _queue_mail(db: DbSession, to: str, subject: str, body: str) -> None:
    db.add(EmailOutbox(to_email=to, subject=subject, body=body))
    if not settings.is_production:
        log.info("[DEV] correo en cola para %s: %s", to, body)  # en producción nunca se registran enlaces


def issue_token(db: DbSession, user: User, purpose: str, ttl_minutes: int) -> str:
    # Invalida tokens previos sin usar del mismo propósito
    db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id,
                                                PasswordResetToken.purpose == purpose,
                                                PasswordResetToken.used_at.is_(None)).values(used_at=now()))
    raw = new_token()
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash(raw), purpose=purpose,
                              expires_at=now() + timedelta(minutes=ttl_minutes)))
    return raw


def _consume(db: DbSession, raw: str, purpose: str) -> PasswordResetToken:
    t = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash(raw),
                                                   PasswordResetToken.purpose == purpose))
    if not t or t.used_at or t.expires_at <= now():
        raise AuthError("El enlace no es válido o ha expirado", 400)
    t.used_at = now()
    return t


def request_password_reset(db: DbSession, email: str, ip: str | None) -> None:
    """Respuesta idéntica exista o no la cuenta (no enumera usuarios)."""
    user = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None), User.is_active.is_(True)))
    if user:
        raw = issue_token(db, user, "reset", settings.token_ttl_minutes_reset)
        link = f"{settings.public_base_url}/restablecer?token={raw}"
        _queue_mail(db, user.email, "Restablece tu contraseña", f"Usa este enlace (válido 1 hora): {link}")
        audit(db, "auth.reset_requested", user.id, ip=ip)
    db.commit()


def reset_password(db: DbSession, raw: str, new_password: str, ip: str | None) -> None:
    if (msg := validate_password_strength(new_password)):
        raise AuthError(msg)
    t = _consume(db, raw, "reset")
    user = db.get(User, t.user_id)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.failed_login_count, user.locked_until = 0, None
    db.execute(update(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None)).values(revoked_at=now()))
    audit(db, "auth.password_reset", user.id, ip=ip)
    db.commit()


def send_verification(db: DbSession, user: User) -> None:
    if user.email_verified_at:
        return
    raw = issue_token(db, user, "verify_email", 60 * 24)
    link = f"{settings.public_base_url}/verificar?token={raw}"
    _queue_mail(db, user.email, "Verifica tu correo", f"Confirma tu correo (válido 24 h): {link}")
    db.commit()


def verify_email(db: DbSession, raw: str) -> None:
    t = _consume(db, raw, "verify_email")
    user = db.get(User, t.user_id)
    user.email_verified_at = now()
    audit(db, "auth.email_verified", user.id)
    db.commit()
