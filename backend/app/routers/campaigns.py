"""Campaigns with strategy (B2B/B2C/ABM/custom + many more) and template/plain
mode. Leads go out ONE AT A TIME in FIFO order — each email `step` seconds after
the previous one (step = the agent's average outbound delay), batch N starts
after batch N-1's window, per-agent/global outbound delays and daily caps still
apply.

The campaign screen shows ONE number — how many leads have gone out — and
nothing about batches. Batch bookkeeping is a Mail Records concern; the
`batches` relation still exists internally (it groups the FIFO queue) but is
never returned here, so the campaign page can't grow a batch UI by accident.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas, audit
from ..security import current_user
from ..services import enroller
 
router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
 
 
@router.get("", response_model=list[schemas.CampaignOut])
def list_campaigns(db: Session = Depends(get_db)):
    return (db.query(models.Campaign)
            .order_by(models.Campaign.created_at.desc()).all())
 
 
@router.get("/parts")
def campaign_parts():
    """The campaign-to-agent SELECTION BOX: which parts of the agent a
    campaign's information is allowed to drive, with their default rules.

    Every part is on by default — that is what the default Agent prompt says
    too — so an untouched campaign uses the whole agent as configured."""
    from ..services import agent_settings
    return {
        "parts": [{"key": p["key"], "label": p["label"], "desc": p["desc"],
                   "rule": p["rule"]} for p in agent_settings.PARTS],
        "weekdays": agent_settings.WEEKDAYS,
        "default_prompt": agent_settings.default_prompt(),
    }


@router.get("/paged")
def list_campaigns_paged(page: int = 1, per_page: int = 20, db: Session = Depends(get_db)):
    """Paginated campaign list for the Campaigns page — matters once you have
    dozens+ campaigns; the plain /api/campaigns (unpaginated) stays for the
    small agent/campaign-picker dropdowns elsewhere that need the full list."""
    per_page = min(max(per_page, 1), 100)
    q = db.query(models.Campaign).order_by(models.Campaign.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()

    # Per-campaign live counts for the card. The Campaigns screen only ever
    # renders "how many leads went out" — no batch rows, no batch counters.
    cids = [c.id for c in items]
    out_counts = dict(
        db.query(models.Campaign.id, func.count(models.EmailMessage.id))
        .join(models.Lead, models.Lead.campaign_id == models.Campaign.id)
        .join(models.EmailMessage, models.EmailMessage.lead_id == models.Lead.id)
        .filter(models.Campaign.id.in_(cids or [0]),
                models.EmailMessage.direction == "out",
                models.EmailMessage.is_spam.is_(False),
                models.EmailMessage.is_escalation.is_(False))
        .group_by(models.Campaign.id).all())
    in_counts = dict(
        db.query(models.Campaign.id, func.count(models.EmailMessage.id))
        .join(models.Lead, models.Lead.campaign_id == models.Campaign.id)
        .join(models.EmailMessage, models.EmailMessage.lead_id == models.Lead.id)
        .filter(models.Campaign.id.in_(cids or [0]),
                models.EmailMessage.direction == "in",
                models.EmailMessage.is_spam.is_(False),
                models.EmailMessage.is_escalation.is_(False))
        .group_by(models.Campaign.id).all())
    fu_counts = dict(
        db.query(models.Lead.campaign_id,
                 func.coalesce(func.sum(models.Lead.followups_sent), 0))
        .filter(models.Lead.campaign_id.in_(cids or [0]))
        .group_by(models.Lead.campaign_id).all())
    lead_counts = dict(
        db.query(models.Lead.campaign_id, func.count(models.Lead.id))
        .filter(models.Lead.campaign_id.in_(cids or [0]))
        .group_by(models.Lead.campaign_id).all())
    esc_counts = dict(
        db.query(models.Campaign.id, func.count(models.EmailMessage.id))
        .join(models.Lead, models.Lead.campaign_id == models.Campaign.id)
        .join(models.EmailMessage, models.EmailMessage.lead_id == models.Lead.id)
        .filter(models.Campaign.id.in_(cids or [0]),
                models.EmailMessage.is_escalation.is_(True))
        .group_by(models.Campaign.id).all())

    result = []
    for c in items:
        d = schemas.CampaignOut.model_validate(c).model_dump()
        d.pop("batches", None)          # batch data is a Mail Records concern
        d["outbound_sent"] = int(out_counts.get(c.id, 0))
        d["followups_sent"] = int(fu_counts.get(c.id, 0))
        d["replies_received"] = int(in_counts.get(c.id, 0))
        d["leads_enrolled"] = int(lead_counts.get(c.id, 0))
        d["escalated"] = int(esc_counts.get(c.id, 0))
        result.append(d)
    return {
        "items": result,
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
    }
 
 
@router.post("", response_model=schemas.CampaignOut)
def create_campaign(data: schemas.CampaignCreate, db: Session = Depends(get_db)):
    if not db.get(models.Agent, data.agent_id):
        raise HTTPException(404, "Agent not found")
    c = models.Campaign(**data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
 
 
@router.put("/{cid}", response_model=schemas.CampaignOut)
def update_campaign(cid: int, data: schemas.CampaignCreate, db: Session = Depends(get_db)):
    c = db.get(models.Campaign, cid)
    if not c:
        raise HTTPException(404, "Campaign not found")
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c
 
 
@router.post("/{cid}/toggle")
def toggle(cid: int, db: Session = Depends(get_db)):
    c = db.get(models.Campaign, cid)
    if not c:
        raise HTTPException(404, "Campaign not found")
    c.status = "paused" if c.status == "active" else "active"
    db.commit()
    return {"id": c.id, "status": c.status}


@router.get("/{cid}/subject-preview")
def subject_preview(cid: int, lead_id: Optional[int] = Query(None),
                    country: str = Query(""), n: int = Query(6, ge=1, le=20),
                    db: Session = Depends(get_db)):
    """Show the subject lines this campaign would actually use, before anything
    is sent.

    A real lead gives the truest answer (their industry, title, country and the
    subjects they already received all feed the pick). With no lead it falls back
    to a bare stand-in so the form can still preview. Used by the campaign screen
    so nobody is surprised by a 3-word subject in someone's inbox."""
    from ..services import subjects as subject_service
    c = db.get(models.Campaign, cid)
    if not c:
        raise HTTPException(404, "Campaign not found")
    lead = db.get(models.Lead, lead_id) if lead_id else None
    if lead is None:
        lead = models.Lead(id=0, name="", email="", company="",
                           title="", country=country or (c.target_country or ""))
    elif country:
        lead.country = country
    # The subject cap actually in force: 3 words max while the Subject part of
    # the selection box is ticked (the default), otherwise this campaign's own
    # configured limit — never above the house ceiling of 3. Same helper the
    # builder and the send path use.
    return {
        "campaign_id": cid,
        "max_words": subject_service.subject_word_cap(c),
        "candidates": subject_service.subject_bank_preview(lead, c, n),
    }
 
 
@router.post("/{cid}/launch")
def launch(cid: int, data: schemas.LaunchIn, db: Session = Depends(get_db)):
    """Queue every launchable lead in a strict FIFO: email #1 sends after one
    step (~agent outbound delay), email #2 one step later, and so on — never
    all at once, always in the order they were selected. The next batch's
    window starts right after the current one so volume ramps safely.

    Returns a single lead count — the campaign screen only ever reports "how
    many leads have gone out". Batch numbers are visible in Mail Records."""
    lead_ids = data.lead_ids
    c = db.get(models.Campaign, cid)
    if not c:
        raise HTTPException(404, "Campaign not found")
    if c.status != "active":
        raise HTTPException(400, "Campaign is paused")
    agent = db.get(models.Agent, c.agent_id)
    if not agent:
        raise HTTPException(400, "Campaign has no agent")

    leads = (db.query(models.Lead)
             .filter(models.Lead.id.in_(lead_ids),
                     models.Lead.status.in_([models.LeadStatus.new,
                                             models.LeadStatus.enrolled]))
             .all())
    if not leads:
        raise HTTPException(400, "No launchable leads (already contacted or missing)")

    out = enroller.enqueue_fifo(
        db, c, agent, leads,
        existing_batches=db.query(models.Batch)
                              .filter(models.Batch.campaign_id == cid).count())
    db.commit()
    return {"batches": out["batches"], "queued": out["queued"],
            "batch_size": out["batch_size"],
            "source_filenames": out.get("source_filenames", [])}
 
 
@router.get("/{cid}/batches", response_model=list[schemas.BatchOut])
def batches(cid: int, db: Session = Depends(get_db)):
    return (db.query(models.Batch).filter(models.Batch.campaign_id == cid)
            .order_by(models.Batch.number).all())
 
 
@router.delete("/batches/{bid}", status_code=204)
def delete_batch(bid: int, db: Session = Depends(get_db)):
    """Delete a (completed) batch to keep memory/DB lean."""
    b = db.get(models.Batch, bid)
    if b:
        db.query(models.Lead).filter(models.Lead.batch_id == bid)\
          .update({models.Lead.batch_id: None})
        db.delete(b)
        db.commit()
 
 
@router.delete("/{cid}", status_code=204)
def delete_campaign(cid: int, request: Request, db: Session = Depends(get_db),
                    user: models.User = Depends(current_user)):
    c = db.get(models.Campaign, cid)
    if c:
        name = c.name
        db.query(models.Lead).filter(models.Lead.campaign_id == cid)\
          .update({models.Lead.campaign_id: None, models.Lead.batch_id: None})
        db.delete(c)
        db.commit()
        audit.log(db, user, "campaign.delete", "campaign", cid, name,
                 request.client.host if request.client else "")
