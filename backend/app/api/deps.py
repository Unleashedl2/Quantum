from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session as DbSession
from app.db.session import get_db
from app.models import Session, User
from app.services.auth import get_session

COOKIE = "qs_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def current_auth(request: Request, db: DbSession = Depends(get_db),
                 qs_session: str | None = Cookie(default=None),
                 x_csrf_token: str | None = Header(default=None)) -> tuple[Session, User]:
    res = get_session(db, qs_session)
    if not res:
        raise HTTPException(401, "No autenticado")
    sess, user = res
    # CSRF (token sincronizado): obligatorio en métodos no seguros
    if request.method in UNSAFE and (not x_csrf_token or x_csrf_token != sess.csrf_token):
        raise HTTPException(403, "Token CSRF inválido")
    return sess, user


def current_user(auth=Depends(current_auth)) -> User:
    return auth[1]


def ready_user(user: User = Depends(current_user)) -> User:
    """Bloquea todo lo que no sea cambiar contraseña mientras sea temporal."""
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contraseña temporal antes de continuar")
    return user


def require_permission(code: str):
    def checker(user: User = Depends(ready_user)) -> User:
        if not user.is_staff or code not in user.permission_codes:
            raise HTTPException(403, "Permiso insuficiente")
        return user
    return checker


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
