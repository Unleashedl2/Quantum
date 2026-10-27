import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession
from app.api.deps import client_ip, require_permission
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import get_db
from app.models import Role, Session, User
from app.schemas.account import BlockIn, StaffCreate, StaffOut
from app.services import tokens
from app.services.audit import audit
from app.services.auth import now

router = APIRouter(prefix="/api/staff", tags=["staff"])


def _out(u: User) -> StaffOut:
    return StaffOut(id=u.id, first_name=u.first_name, last_name=u.last_name, email=u.email,
                    roles=sorted(u.role_names), is_active=u.is_active)


def _can_touch(actor: User, target: User) -> None:
    """Un Admin nunca puede operar sobre un Master ni sobre sí mismo en bloqueos."""
    if "master" in target.role_names and "master" not in actor.role_names:
        raise HTTPException(403, "Solo un Master puede gestionar a otro Master")


@router.get("", response_model=list[StaffOut])
def list_staff(actor: User = Depends(require_permission("staff.manage")), db: DbSession = Depends(get_db)):
    return [_out(u) for u in db.scalars(select(User).where(User.is_staff.is_(True)).order_by(User.id)).all()]


@router.post("", response_model=StaffOut, status_code=201)
def create_staff(data: StaffCreate, request: Request, actor: User = Depends(require_permission("staff.manage")),
                 db: DbSession = Depends(get_db)):
    if data.role == "master" and "master" not in actor.role_names:
        raise HTTPException(403, "Solo un Master puede crear otro Master")
    if db.scalar(select(User.id).where(User.email == data.email)):
        raise HTTPException(409, "Ya existe una cuenta con ese correo")
    role = db.scalar(select(Role).where(Role.name == data.role))
    # Contraseña aleatoria que nadie conoce; la persona define la suya con un enlace de un solo uso.
    user = User(first_name=data.first_name, last_name=data.last_name, email=data.email, is_staff=True,
                password_hash=hash_password(secrets.token_urlsafe(32)), must_change_password=True, roles=[role])
    db.add(user); db.flush()
    raw = tokens.issue_token(db, user, "reset", 60 * 24)
    tokens._queue_mail(db, user.email, "Tu acceso a Quantum Store",
                       f"Define tu contraseña (válido 24 h): {settings.public_base_url}/restablecer?token={raw}")
    audit(db, "staff.created", actor.id, "user", user.id, {"role": data.role}, client_ip(request))
    db.commit()
    return _out(user)


@router.post("/{user_id}/block", status_code=204)
def block(user_id: int, data: BlockIn, request: Request, actor: User = Depends(require_permission("staff.manage")),
          db: DbSession = Depends(get_db)):
    target = db.get(User, user_id)
    if not target or not target.is_staff:
        raise HTTPException(404, "Usuario no encontrado")
    if target.id == actor.id:
        raise HTTPException(400, "No puedes bloquear tu propia cuenta")
    _can_touch(actor, target)
    target.is_active, target.blocked_reason = False, data.reason
    db.execute(update(Session).where(Session.user_id == target.id, Session.revoked_at.is_(None)).values(revoked_at=now()))
    audit(db, "staff.blocked", actor.id, "user", target.id, {"reason": data.reason}, client_ip(request))
    db.commit()


@router.post("/{user_id}/unblock", status_code=204)
def unblock(user_id: int, request: Request, actor: User = Depends(require_permission("staff.manage")),
            db: DbSession = Depends(get_db)):
    target = db.get(User, user_id)
    if not target or not target.is_staff:
        raise HTTPException(404, "Usuario no encontrado")
    _can_touch(actor, target)
    target.is_active, target.blocked_reason = True, None
    audit(db, "staff.unblocked", actor.id, "user", target.id, ip=client_ip(request))
    db.commit()
