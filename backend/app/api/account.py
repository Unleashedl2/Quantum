from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession
from app.api.deps import ready_user
from app.db.session import get_db
from app.models import User, UserAddress
from app.schemas.account import AddressIn, AddressOut, ProfileOut, ProfileUpdate
from app.services.audit import audit
from app.services.auth import now

router = APIRouter(prefix="/api/me", tags=["account"])


def _profile(u: User) -> ProfileOut:
    return ProfileOut(first_name=u.first_name, last_name=u.last_name, email=u.email, phone=u.phone, state=u.state,
                      municipality=u.municipality, address=u.address, email_verified=bool(u.email_verified_at))


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(ready_user)):
    return _profile(user)


@router.patch("/profile", response_model=ProfileOut)
def update_profile(data: ProfileUpdate, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(user, k, v)
    audit(db, "user.profile_updated", user.id, "user", user.id, {"fields": list(data.model_dump(exclude_unset=True))})
    db.commit()
    return _profile(user)


def _own_address(db: DbSession, user: User, address_id: int) -> UserAddress:
    a = db.scalar(select(UserAddress).where(UserAddress.id == address_id, UserAddress.user_id == user.id))
    if not a:   # 404 también para direcciones ajenas: no revela su existencia
        raise HTTPException(404, "Dirección no encontrada")
    return a


def _addr_out(a: UserAddress) -> AddressOut:
    return AddressOut(id=a.id, label=a.label, recipient_name=a.recipient_name, phone=a.phone, state=a.state,
                      municipality=a.municipality, full_address=a.full_address, reference=a.reference,
                      is_default=a.is_default)


@router.get("/addresses", response_model=list[AddressOut])
def list_addresses(user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    rows = db.scalars(select(UserAddress).where(UserAddress.user_id == user.id).order_by(UserAddress.id)).all()
    return [_addr_out(a) for a in rows]


def _clear_default(db: DbSession, user: User) -> None:
    db.execute(update(UserAddress).where(UserAddress.user_id == user.id).values(is_default=False))


@router.post("/addresses", response_model=AddressOut, status_code=201)
def create_address(data: AddressIn, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    count = len(db.scalars(select(UserAddress.id).where(UserAddress.user_id == user.id)).all())
    if count >= 10:
        raise HTTPException(400, "Máximo de 10 direcciones")
    if data.is_default or count == 0:
        _clear_default(db, user)
    a = UserAddress(user_id=user.id, **data.model_dump() | {"is_default": data.is_default or count == 0})
    db.add(a); db.commit()
    return _addr_out(a)


@router.put("/addresses/{address_id}", response_model=AddressOut)
def update_address(address_id: int, data: AddressIn, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    a = _own_address(db, user, address_id)
    if data.is_default:
        _clear_default(db, user)
    for k, v in data.model_dump().items():
        setattr(a, k, v)
    db.commit()
    return _addr_out(a)


@router.delete("/addresses/{address_id}", status_code=204)
def delete_address(address_id: int, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    # Los pedidos guardan copia de su dirección, por lo que borrar aquí no altera el historial.
    db.delete(_own_address(db, user, address_id)); db.commit()


@router.post("/delete-request", status_code=202)
def request_account_deletion(user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    """Solicitud (no borrado inmediato): se conservan los datos que deban guardarse por compras asociadas."""
    user.deletion_requested_at = user.deletion_requested_at or now()
    audit(db, "user.deletion_requested", user.id, "user", user.id)
    db.commit()
    return {"detail": "Solicitud registrada; será revisada por el equipo"}
