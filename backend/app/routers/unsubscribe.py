"""Public unsubscribe endpoint — deliberately NOT behind login. Gmail/Yahoo's
one-click unsubscribe (RFC 8058) POSTs here directly from the mail client,
and a person clicking the link in their inbox does a plain GET — both must
work without any auth. Honoring this immediately (not just recording intent)
is both a legal requirement (CAN-SPAM) and a real deliverability signal —
providers watch whether senders actually stop mailing people who opted out."""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/unsub", tags=["unsubscribe"])

_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Unsubscribed</title>
<style>body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f5f7fb;
color:#0f1b33;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #e7ebf3;border-radius:14px;padding:32px 40px;
max-width:420px;text-align:center;box-shadow:0 10px 30px rgba(0,27,88,.08)}}
h1{{font-size:18px;color:#001B58;margin:0 0 8px}}p{{color:#6b7690;font-size:14px;margin:0}}</style>
</head><body><div class="card"><h1>{title}</h1><p>{body}</p></div></body></html>"""


def _unsubscribe(token: str, db: Session) -> bool:
    lead = db.query(models.Lead).filter(models.Lead.unsub_token == token).first()
    if not lead:
        return False
    lead.unsubscribed = True
    db.commit()
    return True


@router.get("/{token}", response_class=HTMLResponse)
def unsubscribe_get(token: str, db: Session = Depends(get_db)):
    """A person clicking the link in their inbox lands here."""
    ok = _unsubscribe(token, db)
    if ok:
        return _PAGE.format(title="You're unsubscribed",
                            body="You won't receive any further emails from this sender. "
                                 "This takes effect immediately.")
    return _PAGE.format(title="Link not recognized",
                        body="This unsubscribe link is invalid or already used.")


@router.post("/{token}")
def unsubscribe_post(token: str, db: Session = Depends(get_db)):
    """Gmail/Yahoo one-click (RFC 8058): the mail client POSTs here directly,
    no page render needed, no confirmation click required."""
    ok = _unsubscribe(token, db)
    return {"ok": ok}