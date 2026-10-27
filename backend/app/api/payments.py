from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession, aliased
from app.api.deps import client_ip, ready_user, require_permission
from app.core.config import settings
from app.db.session import get_db
from app.models import (Bank, Notification, Order, OrderItem, Payment, PaymentEvent, PaymentMethod, User)
from app.schemas.payments import BankIn, BankUpdate, MethodUpdate, PaymentDeclareIn, ReviewIn
from app.services import payments as svc
from app.services import storage
from app.services.audit import audit
from app.services.auth import now
from app.services.cart import ShopError

router = APIRouter(prefix="/api", tags=["payments"])
REVIEW = require_permission("payments.review")


def _fail(e: ShopError):
    raise HTTPException(e.status, e.message)


def _pay_public(p: Payment | None) -> dict | None:
    if not p:
        return None
    reason = p.review_reason if p.status in ("rejected", "needs_info") else None
    return {"id": p.id, "status": p.status, "amount_declared_usd": p.amount_declared_usd, "reference": p.reference,
            "paid_at": p.paid_at, "origin_bank_id": p.origin_bank_id, "receiving_bank_id": p.receiving_bank_id,
            "has_proof": bool(p.proof_storage_key), "reason": reason,
            "details": {k: v for k, v in (p.details or {}).items() if k in ("cash_modality", "network", "tx_hash")}}


# ---------- bancos (público: solo activos) ----------
@router.get("/banks")
def banks(q: str | None = Query(default=None, max_length=60), db: DbSession = Depends(get_db)):
    stmt = select(Bank).where(Bank.is_active.is_(True)).order_by(Bank.name)
    if q:
        stmt = stmt.where(Bank.name.ilike(f"%{q}%") | (Bank.code == q))
    return [{"id": b.id, "code": b.code, "name": b.name} for b in db.scalars(stmt).all()]


# ---------- cliente ----------
@router.get("/orders/{number}/payment")
def payment_state(number: str, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    o = db.scalar(select(Order).where(Order.number == number, Order.user_id == user.id))
    if not o:
        raise HTTPException(404, "Pedido no encontrado")
    pm = db.get(PaymentMethod, o.payment_method_id) if o.payment_method_id else None
    return {"amount_due_usd": o.total_usd, "method": svc.instructions_for(pm) if pm else None,
            "payment": _pay_public(svc.current_payment(db, o.id))}


@router.post("/orders/{number}/payment", status_code=201)
def declare_payment(number: str, data: PaymentDeclareIn, request: Request, user: User = Depends(ready_user),
                    db: DbSession = Depends(get_db)):
    try:
        return _pay_public(svc.declare(db, user, number, data, client_ip(request)))
    except ShopError as e:
        _fail(e)


@router.put("/orders/{number}/payment")
def respond_payment(number: str, data: PaymentDeclareIn, request: Request, user: User = Depends(ready_user),
                    db: DbSession = Depends(get_db)):
    try:
        return _pay_public(svc.respond(db, user, number, data, client_ip(request)))
    except ShopError as e:
        _fail(e)


@router.post("/orders/{number}/payment/proof", status_code=201)
async def upload_proof(number: str, file: UploadFile = File(...), user: User = Depends(ready_user),
                       db: DbSession = Depends(get_db)):
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    try:
        meta = storage.put_image(f"proofs/{user.id}", data, private=True)
    except storage.StorageNotConfigured as e:
        raise HTTPException(503, str(e))
    except storage.InvalidUpload as e:
        raise HTTPException(400, str(e))
    try:
        old = svc.set_proof(db, user, number, meta["key"])
    except ShopError as e:
        storage.delete_object(meta["key"])
        _fail(e)
    if old:
        storage.delete_object(old)
    return {"ok": True}


# ---------- administración de pagos ----------
@router.get("/admin/payments")
def admin_payments(status: str | None = Query(default=None, pattern="^(declared|pending_review|approved|rejected|needs_info)$"),
                   q: str | None = Query(default=None, max_length=60), page: int = Query(default=1, ge=1),
                   page_size: int = Query(default=20, ge=1, le=100), _: User = Depends(REVIEW),
                   db: DbSession = Depends(get_db)):
    ob, rb = aliased(Bank), aliased(Bank)
    stmt = (select(Payment, Order, User, PaymentMethod, ob.name, rb.name)
            .join(Order, Order.id == Payment.order_id).join(User, User.id == Order.user_id)
            .join(PaymentMethod, PaymentMethod.id == Payment.method_id)
            .outerjoin(ob, ob.id == Payment.origin_bank_id).outerjoin(rb, rb.id == Payment.receiving_bank_id))
    if status:
        stmt = stmt.where(Payment.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Order.number.ilike(like), Payment.reference.ilike(like), User.email.ilike(like),
                              User.first_name.ilike(like), User.last_name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.with_only_columns(Payment.id).subquery())) or 0
    rows = db.execute(stmt.order_by(Payment.created_at.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    oids = [r[1].id for r in rows]
    items: dict[int, list[str]] = {}
    for oi in db.scalars(select(OrderItem).where(OrderItem.order_id.in_(oids)).order_by(OrderItem.id)) if oids else []:
        items.setdefault(oi.order_id, []).append(f"{oi.quantity} × {oi.product_name}")
    return {"total": total, "page": page, "page_size": page_size, "items": [
        {"id": p.id, "order_number": o.number, "created_at": p.created_at, "customer": f"{u.first_name} {u.last_name}",
         "products": items.get(o.id, []), "order_total_usd": o.total_usd, "declared_usd": p.amount_declared_usd,
         "method": m.name, "method_code": m.code, "origin_bank": obn, "receiving_bank": rbn, "reference": p.reference,
         "has_proof": bool(p.proof_storage_key), "status": p.status, "flags": (p.details or {}).get("flags", [])}
        for p, o, u, m, obn, rbn in rows]}


@router.get("/admin/payments/{pid}")
def admin_payment_detail(pid: int, _: User = Depends(REVIEW), db: DbSession = Depends(get_db)):
    p = db.get(Payment, pid)
    if not p:
        raise HTTPException(404, "Pago no encontrado")
    o, u, m = db.get(Order, p.order_id), None, db.get(PaymentMethod, p.method_id)
    u = db.get(User, o.user_id)
    events = db.execute(select(PaymentEvent, User.first_name).outerjoin(User, User.id == PaymentEvent.actor_user_id)
                        .where(PaymentEvent.payment_id == pid).order_by(PaymentEvent.id)).all()
    net = (p.details or {}).get("network")
    return {"id": p.id, "status": p.status, "order_number": o.number, "order_status": o.status, "order_total_usd": o.total_usd,
            "customer": {"name": f"{u.first_name} {u.last_name}", "phone": u.phone, "email": u.email},
            "method": m.name, "method_code": m.code, "declared_usd": p.amount_declared_usd, "reference": p.reference,
            "paid_at": p.paid_at, "details": p.details, "review_reason": p.review_reason, "reviewed_at": p.reviewed_at,
            "proof_url": storage.presigned_url(p.proof_storage_key) if p.proof_storage_key else None,
            "min_confirmations": (((m.config or {}).get("networks") or {}).get(net) or {}).get("min_confirmations") if net else None,
            "events": [{"action": e.action, "note": e.note, "detail": e.detail, "actor": name, "at": e.created_at} for e, name in events]}


@router.post("/admin/payments/{pid}/review")
def admin_review(pid: int, data: ReviewIn, request: Request, actor: User = Depends(REVIEW), db: DbSession = Depends(get_db)):
    try:
        p = svc.review(db, actor, pid, data, client_ip(request))
    except ShopError as e:
        _fail(e)
    return {"id": p.id, "status": p.status}


@router.post("/admin/orders/{number}/prepare")
def admin_prepare(number: str, request: Request, actor: User = Depends(require_permission("shipping.manage")),
                  db: DbSession = Depends(get_db)):
    try:
        o = svc.start_preparing(db, actor, number, client_ip(request))
    except ShopError as e:
        _fail(e)
    return {"number": o.number, "status": o.status}


# ---------- catálogo de bancos (administrable) ----------
BANKS = require_permission("banks.manage")


@router.get("/admin/banks")
def admin_banks(q: str | None = Query(default=None, max_length=60), _: User = Depends(BANKS), db: DbSession = Depends(get_db)):
    stmt = select(Bank).order_by(Bank.name)
    if q:
        stmt = stmt.where(Bank.name.ilike(f"%{q}%") | (Bank.code == q))
    return [{"id": b.id, "code": b.code, "name": b.name, "is_active": b.is_active, "verified_at": b.verified_at,
             "source_note": b.source_note} for b in db.scalars(stmt).all()]


@router.post("/admin/banks", status_code=201)
def create_bank(data: BankIn, actor: User = Depends(BANKS), db: DbSession = Depends(get_db)):
    if db.scalar(select(Bank.id).where(Bank.code == data.code)):
        raise HTTPException(409, "Ya existe un banco con ese código")
    b = Bank(**data.model_dump())
    db.add(b); db.flush()
    audit(db, "bank.created", actor.id, "bank", b.id, {"code": b.code})
    db.commit()
    return {"id": b.id}


@router.patch("/admin/banks/{bid}")
def update_bank(bid: int, data: BankUpdate, actor: User = Depends(BANKS), db: DbSession = Depends(get_db)):
    b = db.get(Bank, bid)
    if not b:
        raise HTTPException(404, "Banco no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(b, k, v)
    audit(db, "bank.updated", actor.id, "bank", bid, data.model_dump(exclude_unset=True))
    db.commit()
    return {"id": b.id}


@router.post("/admin/banks/{bid}/verify", status_code=204)
def verify_bank(bid: int, actor: User = Depends(BANKS), db: DbSession = Depends(get_db)):
    b = db.get(Bank, bid)
    if not b:
        raise HTTPException(404, "Banco no encontrado")
    b.verified_at = now()
    audit(db, "bank.verified", actor.id, "bank", bid)
    db.commit()


# ---------- configuración de métodos de pago (Master) ----------
SETTINGS = require_permission("settings.general")


@router.get("/admin/payment-methods")
def admin_methods(_: User = Depends(SETTINGS), db: DbSession = Depends(get_db)):
    return [{"id": m.id, "code": m.code, "name": m.name, "is_active": m.is_active, "instructions": m.instructions,
             "config": m.config or {}} for m in db.scalars(select(PaymentMethod).order_by(PaymentMethod.id)).all()]


@router.put("/admin/payment-methods/{mid}")
def update_method(mid: int, data: MethodUpdate, actor: User = Depends(SETTINGS), db: DbSession = Depends(get_db)):
    m = db.get(PaymentMethod, mid)
    if not m:
        raise HTTPException(404, "Método no encontrado")
    if data.is_active is not None:
        m.is_active = data.is_active
    if data.instructions is not None:
        m.instructions = data.instructions
    if data.config is not None:
        m.config = data.config.model_dump()
    audit(db, "payment_method.updated", actor.id, "payment_method", mid, {"fields": sorted(data.model_dump(exclude_unset=True))})
    db.commit()
    return {"id": m.id}


# ---------- notificaciones ----------
def _scope(user: User):
    """Cliente: las suyas. Personal con permisos de pagos/pedidos: además la bandeja del equipo."""
    conds = [Notification.user_id == user.id]
    if user.is_staff and ({"payments.review", "orders.view"} & user.permission_codes):
        conds.append(Notification.audience == "staff")
    return or_(*conds)


@router.get("/notifications")
def notifications(unread_only: bool = False, page: int = Query(default=1, ge=1), user: User = Depends(ready_user),
                  db: DbSession = Depends(get_db)):
    base = _scope(user)
    unread = db.scalar(select(func.count()).select_from(Notification).where(base, Notification.read_at.is_(None)))
    stmt = select(Notification).where(base)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.id.desc()).limit(30).offset((page - 1) * 30)).all()
    nums = {o.id: o.number for o in db.scalars(select(Order).where(Order.id.in_({n.order_id for n in rows if n.order_id})))} if rows else {}
    return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "audience": n.audience, "title": n.title,
                                         "body": n.body, "order_number": nums.get(n.order_id), "read": bool(n.read_at),
                                         "created_at": n.created_at} for n in rows]}


@router.post("/notifications/read-all", status_code=204)
def read_all(user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    for n in db.scalars(select(Notification).where(_scope(user), Notification.read_at.is_(None))).all():
        n.read_at = now()
    db.commit()


@router.post("/notifications/{nid}/read", status_code=204)
def read_one(nid: int, user: User = Depends(ready_user), db: DbSession = Depends(get_db)):
    n = db.scalar(select(Notification).where(Notification.id == nid, _scope(user)))
    if not n:
        raise HTTPException(404, "Notificación no encontrada")
    n.read_at = n.read_at or now()
    db.commit()
