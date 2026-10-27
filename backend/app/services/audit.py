from sqlalchemy.orm import Session
from app.models import AuditLog

_FORBIDDEN = {"password", "password_hash", "token", "secret", "new_password", "current_password"}


def audit(db: Session, action: str, actor_id: int | None = None, entity_type: str | None = None,
          entity_id: str | int | None = None, detail: dict | None = None, ip: str | None = None) -> None:
    clean = {k: v for k, v in (detail or {}).items() if k.lower() not in _FORBIDDEN}
    db.add(AuditLog(actor_user_id=actor_id, action=action, entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None, detail=clean or None, ip=ip))
