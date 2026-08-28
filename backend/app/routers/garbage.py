"""Garbage collector: paginated audit view, single + bulk delete, clear-all.
Auto-purge also runs daily via Celery (purge_garbage task)."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas

router = APIRouter(prefix="/api/garbage", tags=["garbage"])


class BulkIds(BaseModel):
    ids: list[int]


@router.get("")
def garbage(page: int = Query(default=1, ge=1),
            per_page: int = Query(default=25, ge=5, le=100),
            db: Session = Depends(get_db)):
    q = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.is_spam.is_(True))
         .order_by(models.EmailMessage.created_at.desc()))
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return {"total": total, "page": page, "per_page": per_page,
            "pages": max(1, -(-total // per_page)),
            "items": [schemas.MessageOut.model_validate(m).model_dump() for m in items]}


@router.delete("/{msg_id}", status_code=204)
def delete_one(msg_id: int, db: Session = Depends(get_db)):
    m = db.get(models.EmailMessage, msg_id)
    if m and m.is_spam:
        db.delete(m)
        db.commit()


@router.post("/bulk-delete")
def bulk_delete(data: BulkIds, db: Session = Depends(get_db)):
    n = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.id.in_(data.ids),
                 models.EmailMessage.is_spam.is_(True))
         .delete(synchronize_session=False))
    db.commit()
    return {"deleted": n}


@router.post("/clear")
def clear_all(db: Session = Depends(get_db)):
    n = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.is_spam.is_(True))
         .delete(synchronize_session=False))
    db.commit()
    return {"deleted": n}
