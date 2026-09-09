"""Pitch Decker endpoints. Osaja (default sales-led agent) generates a
region-aware sales-call transcript for a lead; the team reviews it in the
right-hand panel and it's stored as a PitchRecord."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from .. import models, schemas
from ..services import pitch as pitch_service

router = APIRouter(prefix="/api/pitch", tags=["pitch"])


def _default_sales_agent(db: Session) -> models.Agent | None:
    a = db.query(models.Agent).filter(models.Agent.name.ilike("osaja")).first()
    return a or db.query(models.Agent).order_by(models.Agent.id).first()


@router.get("", response_model=list[schemas.PitchOut])
def list_pitches(lead_id: int | None = Query(default=None),
                 db: Session = Depends(get_db)):
    q = db.query(models.PitchRecord)
    if lead_id is not None:
        q = q.filter(models.PitchRecord.lead_id == lead_id)
    return q.order_by(models.PitchRecord.created_at.desc()).limit(100).all()


@router.get("/records")
def list_pitch_records(page: int = Query(1, ge=1),
                       per_page: int = Query(20, ge=5, le=100),
                       agent_id: int | None = Query(default=None),
                       db: Session = Depends(get_db)):
    """Paginated browser of EVERY pitch ever generated, across all leads —
    real-time (no cache), click a row to expand full summary+transcript,
    delete individually or select multiple."""
    q = db.query(models.PitchRecord)
    if agent_id is not None:
        q = q.filter(models.PitchRecord.agent_id == agent_id)
    total = q.count()
    rows = (q.order_by(models.PitchRecord.created_at.desc())
             .offset((page - 1) * per_page).limit(per_page).all())
    return {
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
        "items": [schemas.PitchOut.model_validate(r).model_dump() for r in rows],
    }


class BulkPitchIds(BaseModel):
    ids: list[int]


@router.post("/bulk-delete")
def bulk_delete_pitches(data: BulkPitchIds, db: Session = Depends(get_db)):
    if not data.ids:
        raise HTTPException(400, "No pitches selected")
    n = (db.query(models.PitchRecord)
         .filter(models.PitchRecord.id.in_(data.ids))
         .delete(synchronize_session=False))
    db.commit()
    return {"deleted": n}


@router.get("/{pid}", response_model=schemas.PitchOut)
def get_pitch(pid: int, db: Session = Depends(get_db)):
    p = db.get(models.PitchRecord, pid)
    if not p:
        raise HTTPException(404, "Pitch not found")
    return p


@router.post("/generate", response_model=schemas.PitchOut)
def generate(lead_id: int = Query(...), agent_id: int | None = Query(default=None),
             db: Session = Depends(get_db)):
    """Build a pitch transcript for a lead (Tavily research -> OpenAI role-play)
    and store it as a PitchRecord."""
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    agent = db.get(models.Agent, agent_id) if agent_id else _default_sales_agent(db)
    if not agent:
        raise HTTPException(400, "No agent available")

    from ..services import keys as keysvc
    if settings.LLM_PROVIDER.lower() == "openai" and not keysvc.openai_key(db):
        raise HTTPException(400, "No OpenAI key set — add it in Super Admin → API Keys")

    summary, transcript = pitch_service.generate_pitch(db, lead, agent)
    rec = models.PitchRecord(
        lead_id=lead.id, agent_id=agent.id, lead_name=lead.name,
        company=lead.company, phone=lead.phone, country=lead.country,
        summary=summary, transcript=transcript)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


class AskIn(BaseModel):
    question: str


class PickupIn(BaseModel):
    notes: str  # agent's plain-English description of what actually happened on the call


@router.post("/pickup", response_model=schemas.PitchOut)
def generate_from_pickup(lead_id: int = Query(...), agent_id: int | None = Query(default=None),
                         data: PickupIn = ..., db: Session = Depends(get_db)):
    """Generate a transcript based on what ACTUALLY happened when the client picked up.

    The agent writes a few plain sentences (mood, what they said, objections, outcome).
    The LLM writes a transcript that matches those notes exactly — no invented happy endings.
    Stored as a PitchRecord so the team can see it in Pitch Decker."""
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if not data.notes or not data.notes.strip():
        raise HTTPException(400, "Notes cannot be empty")
    agent = db.get(models.Agent, agent_id) if agent_id else _default_sales_agent(db)
    if not agent:
        raise HTTPException(400, "No agent available")
    from ..services import keys as keysvc
    if settings.LLM_PROVIDER.lower() == "openai" and not keysvc.openai_key(db):
        raise HTTPException(400, "No OpenAI key — add it in Super Admin → API Keys")
    summary, transcript = pitch_service.generate_pickup_transcript(db, lead, agent, data.notes.strip())
    rec = models.PitchRecord(
        lead_id=lead.id, agent_id=agent.id, lead_name=lead.name,
        company=lead.company, phone=lead.phone, country=lead.country,
        summary=f"[CALL LOG] {summary}", transcript=transcript)
    db.add(rec); db.commit(); db.refresh(rec)
    return rec


@router.post("/ask")
def ask(lead_id: int = Query(...), agent_id: int | None = Query(default=None),
        data: AskIn = ..., db: Session = Depends(get_db)):
    """Ask the agent a direct question about a lead (objection handling,
    strategy, etc.) — separate from the pitch transcript itself."""
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if not data.question or not data.question.strip():
        raise HTTPException(400, "Question cannot be empty")
    agent = db.get(models.Agent, agent_id) if agent_id else _default_sales_agent(db)
    if not agent:
        raise HTTPException(400, "No agent available")

    from ..services import keys as keysvc
    if settings.LLM_PROVIDER.lower() == "openai" and not keysvc.openai_key(db):
        raise HTTPException(400, "No OpenAI key set — add it in Super Admin → API Keys")

    latest = (db.query(models.PitchRecord)
              .filter(models.PitchRecord.lead_id == lead.id)
              .order_by(models.PitchRecord.created_at.desc()).first())
    answer = pitch_service.ask_about_lead(
        db, lead, agent, data.question, latest.transcript if latest else "")
    return {"question": data.question, "answer": answer, "agent": agent.name}


@router.delete("/{pid}", status_code=204)
def delete_pitch(pid: int, db: Session = Depends(get_db)):
    p = db.get(models.PitchRecord, pid)
    if p:
        db.delete(p)
        db.commit()