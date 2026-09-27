"""Lead ownership — WHO holds a lead right now, and for how long.

Three rules, evaluated live (nothing is stored, so a rule change applies at
once):

1. No owner agent            -> free: any agent may enroll it.
2. Owner agent is PAUSED     -> released immediately: its leads become
                                available so another agent can take the
                                outbound over.
3. Owner silent for more than `lead_ownership_days` (Settings page,
   default 7) — neither an outbound nor an inbound on that thread — the
   lead is released even though the agent is still active.

Otherwise the lead is HELD: only the owner may keep communicating with it
(enroll by anyone else is blocked with the owner's name as the reason).

Used by the Leads enroll path, the enroller and the send pipeline so all
three always agree on the same answer."""
from datetime import datetime, timedelta

from .. import models


def ownership_days(db) -> int:
    """The Settings-page timeline (default 7 days)."""
    try:
        from ..routers.app_settings import get_runtime_setting
        return max(1, int(get_runtime_setting(db, "lead_ownership_days") or 7))
    except Exception:
        return 7


def last_activity(db, lead) -> datetime | None:
    """Most recent REAL communication on this thread, either direction."""
    newest_msg = (db.query(models.EmailMessage.created_at)
                  .filter(models.EmailMessage.lead_id == lead.id)
                  .order_by(models.EmailMessage.created_at.desc())
                  .first())
    stamps = [lead.last_outbound_at]
    if newest_msg and newest_msg[0]:
        stamps.append(newest_msg[0])
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def held(db, lead, days: int | None = None) -> tuple[bool, str]:
    """(is_held, human-readable reason) — one answer for every code path.

    Reason strings double as the `owned_by` text on the blocked list, so the
    UI can say exactly WHY a lead cannot be taken ("Saif — active" vs
    "Saif — paused (released)" vs "Saif — silent 9d (released after 7d)").

    Pass `days` when checking many leads in one request so the Settings KV
    is read once instead of once per lead."""
    if not lead.agent_id:
        return False, "unassigned"
    agent = db.get(models.Agent, lead.agent_id)
    if agent is None:
        return False, "owner agent deleted"
    if not agent.is_active:
        return False, f"{agent.name} — paused (released)"

    since = last_activity(db, lead) or lead.created_at
    if since is None:
        return True, f"{agent.name} — active"
    if days is None:
        days = ownership_days(db)
    cutoff = datetime.utcnow() - timedelta(days=days)
    if since < cutoff:
        silent = (datetime.utcnow() - since).days
        return False, f"{agent.name} — silent {silent}d (released after {days}d)"
    return True, f"{agent.name} — active"
