from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DbSession
from app.core.config import settings
from app.db.session import get_db
from app.api.deps import COOKIE, client_ip, current_auth
from app.schemas.auth import ChangePasswordIn, LoginIn, MeOut, RegisterIn
from app.services import auth as svc

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _me(user, sess) -> MeOut:
    return MeOut(id=user.id, first_name=user.first_name, last_name=user.last_name, email=user.email,
                 roles=sorted(user.role_names), permissions=sorted(user.permission_codes),
                 must_change_password=user.must_change_password, csrf_token=sess.csrf_token)


@router.post("/register", status_code=201)
def register(data: RegisterIn, request: Request, db: DbSession = Depends(get_db)):
    try:
        user = svc.register_customer(db, data, client_ip(request))
    except svc.AuthError as e:
        raise HTTPException(e.status, e.message)
    from app.services import tokens
    tokens.send_verification(db, user)
    return {"id": user.id}


@router.post("/login", response_model=MeOut)
def login(data: LoginIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    try:
        user, token, sess = svc.login(db, data.email, data.password, client_ip(request),
                                      request.headers.get("user-agent"))
    except svc.AuthError as e:
        raise HTTPException(e.status, e.message)
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="lax",
                        max_age=settings.session_ttl_hours * 3600, path="/")
    return _me(user, sess)


@router.get("/me", response_model=MeOut)
def me(auth=Depends(current_auth)):
    sess, user = auth
    return _me(user, sess)


@router.post("/logout", status_code=204)
def logout(response: Response, auth=Depends(current_auth), db: DbSession = Depends(get_db)):
    svc.revoke_session(db, auth[0])
    response.delete_cookie(COOKIE, path="/")


@router.post("/change-password", status_code=204)
def change_password(data: ChangePasswordIn, request: Request, auth=Depends(current_auth),
                    db: DbSession = Depends(get_db)):
    sess, user = auth   # permitido aunque must_change_password sea true
    try:
        svc.change_password(db, user, data.current_password, data.new_password, sess.id, client_ip(request))
    except svc.AuthError as e:
        raise HTTPException(e.status, e.message)


from app.schemas.account import ForgotIn, ResetIn, TokenIn  # noqa: E402
from app.services import tokens  # noqa: E402


@router.post("/forgot-password", status_code=202)
def forgot_password(data: ForgotIn, request: Request, db: DbSession = Depends(get_db)):
    tokens.request_password_reset(db, data.email, client_ip(request))
    return {"detail": "Si la cuenta existe, recibirás instrucciones por correo"}


@router.post("/reset-password", status_code=204)
def reset_password(data: ResetIn, request: Request, db: DbSession = Depends(get_db)):
    try:
        tokens.reset_password(db, data.token, data.new_password, client_ip(request))
    except svc.AuthError as e:
        raise HTTPException(e.status, e.message)


@router.post("/verify-email", status_code=204)
def verify_email(data: TokenIn, db: DbSession = Depends(get_db)):
    try:
        tokens.verify_email(db, data.token)
    except svc.AuthError as e:
        raise HTTPException(e.status, e.message)


@router.post("/resend-verification", status_code=202)
def resend_verification(auth=Depends(current_auth), db: DbSession = Depends(get_db)):
    tokens.send_verification(db, auth[1])
    return {"detail": "Si tu correo aún no está verificado, se enviará un enlace"}
