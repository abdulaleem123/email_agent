"""Campaigns with strategy (B2B/B2C/ABM), template/plain mode and BATCHED
sending: 20–50 leads per batch, staggered 3–12 min per agent, batch progress
tracked (pending -> running -> completed=green), deletable batches."""
import random
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas, audit
from ..security import current_user
from ..tasks import start_campaign_lead
 
router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
 
 
@router.get("", response_model=list[schemas.CampaignOut])
def list_campaigns(db: Session = Depends(get_db)):
    return (db.query(models.Campaign)
            .order_by(models.Campaign.created_at.desc()).all())
 
 
@router.get("/paged")
def list_campaigns_paged(page: int = 1, per_page: int = 20, db: Session = Depends(get_db)):
    """Paginated campaign list for the Campaigns page — matters once you have
    dozens+ campaigns; the plain /api/campaigns (unpaginated) stays for the
    small agent/campaign-picker dropdowns elsewhere that need the full list."""
    per_page = min(max(per_page, 1), 100)
    q = db.query(models.Campaign).order_by(models.Campaign.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [schemas.CampaignOut.model_validate(c) for c in items],
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
 
 
@router.post("/{cid}/launch")
def launch(cid: int, lead_ids: list[int], db: Session = Depends(get_db)):
    """Split into batches of campaign.batch_size (20–50) and schedule each lead
    with a per-agent random 3–12 min stagger; batch N starts after batch N-1's
    window so volume ramps safely (Gmail/Outlook/Hostinger friendly)."""
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
 
    # Per-campaign batch size now scales for large lead sets (20k–50k). The
    # old hard cap of 50 forced hundreds/thousands of tiny batches; a campaign
    # can now choose a big batch (up to 2000) and the per-agent daily cap +
    # stagger still throttle actual send-rate safely.
    size = max(10, min(2000, c.batch_size or 50))
    existing = db.query(models.Batch).filter(models.Batch.campaign_id == cid).count()
    lo = agent.outbound_delay_min or 180
    hi = agent.outbound_delay_max or 720
    batches_made, cursor = [], 0
    batch_offset = 0
 
    for i in range(0, len(leads), size):
        chunk = leads[i:i + size]
        batch = models.Batch(campaign_id=cid, number=existing + len(batches_made) + 1,
                             total=len(chunk), status=models.BatchStatus.pending)
        db.add(batch)
        db.flush()
        for lead in chunk:
            lead.campaign_id = cid
            lead.agent_id = agent.id
            lead.batch_id = batch.id
            lead.status = models.LeadStatus.enrolled
            delay = batch_offset + random.randint(min(lo, hi), max(lo, hi)) \
                    + cursor * random.randint(20, 60)
            start_campaign_lead.apply_async(args=[lead.id], countdown=delay)
            cursor += 1
        batches_made.append(batch.id)
        batch_offset += len(chunk) * ((lo + hi) // 2)   # next batch after this window
        cursor = 0
    db.commit()
    return {"batches": batches_made, "queued": len(leads), "batch_size": size}
 
 
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
