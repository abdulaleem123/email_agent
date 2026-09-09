"""Outbound guards — keep the send pipeline honest.

The core rule the team asked for: an INITIAL outreach must never be sent to the
same lead twice. If a first-touch outbound email already exists for a lead, we
DO NOT send again — we surface it as a duplicate (notification + return code)
so it's visible, not silently re-sent.

This does NOT block follow-ups (those are a separate, intentional sequence) —
it only blocks a second *initial* cold email to a lead that was already
contacted, whatever campaign/agent tries it.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from .. import models


def already_contacted(db: Session, lead: models.Lead) -> models.EmailMessage | None:
    """Return the first real outbound email ever sent to this lead, or None.

    'Real' = direction 'out', not a spam/blocked marker row. If this returns a
    message, an initial outreach has already gone out and must not repeat."""
    return (db.query(models.EmailMessage)
            .filter(models.EmailMessage.lead_id == lead.id,
                    models.EmailMessage.direction == "out",
                    models.EmailMessage.is_spam.is_(False))
            .order_by(models.EmailMessage.created_at.asc())
            .first())


def is_duplicate_initial(db: Session, lead: models.Lead) -> bool:
    """True when an initial outbound to this lead already exists — i.e. sending
    now would be a duplicate. Status is the fast path; the message table is the
    source of truth (a lead can be re-enrolled and its status reset)."""
    if lead.status in (models.LeadStatus.contacted,
                        models.LeadStatus.replied,
                        models.LeadStatus.meeting,
                        models.LeadStatus.closed):
        # already moved past first-touch AND has a real outbound on file
        if already_contacted(db, lead):
            return True
    return already_contacted(db, lead) is not None


def mark_duplicate(db: Session, lead: models.Lead, agent_id: int | None = None):
    """Record that a duplicate send was prevented — a visible audit row + a
    notification, instead of a silent skip. The row is flagged is_spam=True so
    it lands in the same 'blocked before send' bucket the UI already filters,
    and never counts as a real sent email."""
    prior = already_contacted(db, lead)
    when = prior.created_at.strftime("%Y-%m-%d %H:%M") if prior else "earlier"
    db.add(models.EmailMessage(
        lead_id=lead.id, agent_id=agent_id or lead.agent_id, direction="out",
        subject="(duplicate — not sent)",
        body=f"Skipped: {lead.email} already received an initial outreach on {when} UTC. "
             "Duplicate first-touch sends are blocked so a lead is never emailed "
             "the same cold pitch twice.",
        is_spam=True, spam_reason="duplicate-initial-blocked",
        created_at=datetime.utcnow()))
    db.add(models.Notification(
        kind="warn",
        title=f"Duplicate blocked: {lead.email} already contacted",
        body=f"An initial outreach to {lead.name or lead.email} already went out "
             f"on {when} UTC — this repeat send was skipped, not delivered.",
        agent_id=agent_id or lead.agent_id))
    db.commit()