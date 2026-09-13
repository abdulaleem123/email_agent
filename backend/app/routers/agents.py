from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import settings
from ..security import current_user
from .. import models, schemas, audit

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _out(agent: models.Agent) -> schemas.AgentOut:
    o = schemas.AgentOut.model_validate(agent)
    o.smtp_configured = bool(agent.smtp_user and agent.smtp_password)
    o.imap_configured = bool(agent.imap_user and agent.imap_password)
    return o


@router.get("", response_model=list[schemas.AgentOut])
def list_agents(db: Session = Depends(get_db)):
    return [_out(a) for a in db.query(models.Agent).order_by(models.Agent.id).all()]


@router.post("", response_model=schemas.AgentOut)
def create_agent(data: schemas.AgentCreate, db: Session = Depends(get_db)):
    if db.query(models.Agent).count() >= settings.MAX_AGENTS:
        raise HTTPException(400, f"Max {settings.MAX_AGENTS} agents allowed")
    agent = models.Agent(**data.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _out(agent)


@router.put("/{agent_id}", response_model=schemas.AgentOut)
def update_agent(agent_id: int, data: schemas.AgentCreate, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    payload = data.model_dump()
    # blank password in the form means "keep the saved one"
    for secret in ("smtp_password", "imap_password"):
        if not payload.get(secret):
            payload.pop(secret, None)
    for k, v in payload.items():
        setattr(agent, k, v)
    db.commit()
    db.refresh(agent)
    return _out(agent)


@router.post("/{agent_id}/toggle")
def toggle_agent(agent_id: int, request: Request, db: Session = Depends(get_db),
                 user: models.User = Depends(current_user)):
    """Play/pause — realtime effect: paused agents abort even mid-delay."""
    agent = db.get(models.Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    agent.is_active = not agent.is_active
    db.commit()
    audit.log(db, user, "agent.toggle", "agent", agent_id,
             f"{agent.name} -> {'active' if agent.is_active else 'paused'}",
             request.client.host if request.client else "")
    return {"id": agent.id, "is_active": agent.is_active}


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: int, db: Session = Depends(get_db)):
    """Delete an agent after clearing all FK references."""
    agent = db.get(models.Agent, agent_id)
    if not agent:
        return

    # Block if campaigns still exist (agent_id is NOT NULL there)
    camp_count = db.query(models.Campaign).filter(models.Campaign.agent_id == agent_id).count()
    if camp_count:
        raise HTTPException(
            400,
            f"Cannot delete: agent still owns {camp_count} campaign(s). "
            "Delete or re-assign those campaigns first."
        )

    # Null-out all nullable FKs so delete succeeds
    db.query(models.Lead).filter(models.Lead.agent_id == agent_id)\
      .update({models.Lead.agent_id: None})
    db.query(models.EmailMessage).filter(models.EmailMessage.agent_id == agent_id)\
      .update({models.EmailMessage.agent_id: None})
    db.query(models.Template).filter(models.Template.agent_id == agent_id)\
      .update({models.Template.agent_id: None})
    db.query(models.KnowledgeDoc).filter(models.KnowledgeDoc.agent_id == agent_id)\
      .update({models.KnowledgeDoc.agent_id: None})
    db.query(models.KbChunk).filter(models.KbChunk.agent_id == agent_id)\
      .update({models.KbChunk.agent_id: None})
    db.query(models.Notification).filter(models.Notification.agent_id == agent_id)\
      .update({models.Notification.agent_id: None})
    db.query(models.ApiUsage).filter(models.ApiUsage.agent_id == agent_id)\
      .update({models.ApiUsage.agent_id: None})
    if hasattr(models, "PitchRecord"):
        db.query(models.PitchRecord).filter(models.PitchRecord.agent_id == agent_id)\
          .update({models.PitchRecord.agent_id: None})

    db.delete(agent)
    db.commit()


class MailboxTestIn(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""


@router.post("/test-connection")
def test_connection(data: MailboxTestIn):
    """Live SMTP + IMAP test of whatever is currently typed in the Configure
    form — BEFORE saving. Catches a bad App Password / wrong host immediately
    instead of discovering it only when a campaign tries to send."""
    from ..services import mailer
    if not data.smtp_user or not data.smtp_password:
        raise HTTPException(400, "Enter SMTP user + password first")
    smtp_creds = {
        "host": data.smtp_host or "smtp.gmail.com", "port": data.smtp_port,
        "user": data.smtp_user, "password": data.smtp_password,
    }
    imap_creds = None
    if data.imap_user and data.imap_password:
        imap_creds = {
            "host": data.imap_host or "imap.gmail.com", "port": data.imap_port,
            "user": data.imap_user, "password": data.imap_password,
        }
    return mailer.test_connection(smtp_creds, imap_creds)