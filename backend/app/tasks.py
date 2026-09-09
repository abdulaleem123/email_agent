"""All mail movement through Celery (worker) + Celery Beat (schedules).

Rules enforced here:
- Outbound stagger 3–12 min per agent (configurable per agent)
- Inbound auto-reply delay ~15 min (per agent), plain-text only, KB-first
- SAME-DAY DEDUPE: if any agent already emailed a lead today, another agent
  cannot email that lead until tomorrow (rescheduled + notification raised)
- Per-agent daily caps; batch progress tracking (pending -> running -> completed)
- MX-unverified recipients -> Garbage, never sent
- Garbage auto-purge after GARBAGE_RETENTION_DAYS (daily beat)
"""
import random
from datetime import datetime, timedelta
from .celery_app import celery
from .database import SessionLocal
from .config import settings
from . import models
from .services import spam_filter, scoring, mailer, tavily
from .services import llm as llm_service


def _notify(db, kind: str, title: str, body: str = "", agent_id: int | None = None):
    db.add(models.Notification(kind=kind, title=title[:300], body=body[:2000], agent_id=agent_id))
    db.commit()


def _outbound_delay(agent) -> int:
    lo = agent.outbound_delay_min or settings.OUTBOUND_DELAY_MIN_SECONDS
    hi = agent.outbound_delay_max or settings.OUTBOUND_DELAY_MAX_SECONDS
    return random.randint(min(lo, hi), max(lo, hi))


def _reply_delay(agent) -> int:
    return agent.reply_delay_seconds or settings.INBOUND_REPLY_DELAY_SECONDS


def _today_start() -> datetime:
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def _daily_limit_reached(db, agent) -> bool:
    sent_today = (db.query(models.EmailMessage)
                  .filter(models.EmailMessage.agent_id == agent.id,
                          models.EmailMessage.direction == "out",
                          models.EmailMessage.created_at >= _today_start())
                  .count())
    return sent_today >= (agent.daily_send_limit or 150)


def _lead_emailed_today_by_other_agent(db, lead, agent_id: int):
    """SAME-DAY DEDUPE: has another agent already emailed this lead today?"""
    m = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.lead_id == lead.id,
                 models.EmailMessage.direction == "out",
                 models.EmailMessage.agent_id.isnot(None),
                 models.EmailMessage.agent_id != agent_id,
                 models.EmailMessage.created_at >= _today_start())
         .first())
    return m


def _seconds_until_tomorrow() -> int:
    now = datetime.utcnow()
    tomorrow = (_today_start() + timedelta(days=1, minutes=random.randint(5, 120)))
    return max(300, int((tomorrow - now).total_seconds()))


def _route_to_garbage(db, lead, reason: str):
    lead.status = models.LeadStatus.garbage
    db.add(models.EmailMessage(
        lead_id=lead.id, agent_id=lead.agent_id, direction="out",
        subject="(blocked before send)", body="",
        is_spam=True, spam_reason=reason))
    db.commit()


def _batch_progress(db, lead, ok: bool):
    if not lead.batch_id:
        return
    batch = db.get(models.Batch, lead.batch_id)
    if not batch:
        return
    if ok:
        batch.sent += 1
    else:
        batch.failed += 1
    if batch.status == models.BatchStatus.pending:
        batch.status = models.BatchStatus.running
    if batch.sent + batch.failed >= batch.total:
        batch.status = models.BatchStatus.completed
        batch.completed_at = datetime.utcnow()
        _campaign = db.get(models.Campaign, batch.campaign_id)
        _notify(db, "batch",
                f"Batch #{batch.number} completed",
                f"Campaign #{batch.campaign_id}: {batch.sent} sent, {batch.failed} failed.",
                agent_id=_campaign.agent_id if _campaign else None)
    db.commit()


# ---------------------------------------------------------------- inbound
@celery.task(name="app.tasks.poll_inbox")
def poll_inbox():
    """Polls EVERY agent's own IMAP mailbox separately (Gmail x3 + Hostinger,
    etc). Falls back to the global .env IMAP only when no agent has a mailbox
    configured — so nothing gets double-fetched."""
    db = SessionLocal()
    processed = 0
    try:
        agents = db.query(models.Agent).all()
        mailboxes = []                    # (agent_or_None, creds)
        for a in agents:
            creds = mailer.imap_creds_for(a)
            if creds:
                mailboxes.append((a, creds))
        if not mailboxes:
            g = mailer.imap_creds_for(None)
            if g:
                mailboxes.append((None, g))

        for mb_agent, creds in mailboxes:
            try:
                fetched = mailer.fetch_unseen(creds)
            except Exception:
                continue                  # one broken mailbox must not stop the rest
            for mail in fetched:
                sender, subject, body = mail["from"], mail["subject"], mail["body"]

                # Bounce notification (Gmail/etc rejecting a prior send) —
                # this is the most reliable real-world "mailbox is dead"
                # signal, since SMTP RCPT pre-checks are often blocked or
                # unreliable. Handle it BEFORE spam filtering would just
                # silently discard it.
                if spam_filter.is_bounce(sender, subject):
                    known = {l.email.lower() for l in db.query(models.Lead.email).all()}
                    bounced_addr = spam_filter.extract_bounced_recipient(body, known)
                    if bounced_addr:
                        bad_lead = db.query(models.Lead).filter(
                            models.Lead.email == bounced_addr).first()
                        if bad_lead:
                            bad_lead.email_verified = False
                            bad_lead.status = models.LeadStatus.garbage
                            db.commit()
                    db.add(models.EmailMessage(
                        lead_id=bad_lead.id if bounced_addr and bad_lead else None,
                        agent_id=mb_agent.id if mb_agent else None,
                        direction="in", from_addr=sender, subject=subject,
                        body=body[:5000], is_spam=True, spam_reason="bounce-notification",
                        message_id=mail["message_id"]))
                    db.commit()
                    processed += 1
                    continue

                spam, reason = spam_filter.is_spam(sender, subject, body)
                lead = db.query(models.Lead).filter(models.Lead.email == sender).first()

                if spam:
                    db.add(models.EmailMessage(
                        lead_id=lead.id if lead else None,
                        agent_id=mb_agent.id if mb_agent else None,
                        direction="in",
                        from_addr=sender, subject=subject, body=body[:5000],
                        is_spam=True, spam_reason=reason,
                        message_id=mail["message_id"]))
                    db.commit()
                    continue

                if not lead:
                    lead = models.Lead(email=sender, name=sender.split("@")[0],
                                       source="inbound",
                                       agent_id=mb_agent.id if mb_agent else None,
                                       status=models.LeadStatus.replied)
                    db.add(lead)
                    db.flush()
                elif lead.agent_id is None and mb_agent:
                    lead.agent_id = mb_agent.id      # claim by mailbox owner

                db.add(models.EmailMessage(
                    lead_id=lead.id,
                    agent_id=(mb_agent.id if mb_agent else lead.agent_id),
                    direction="in",
                    from_addr=sender, subject=subject, body=body,
                    message_id=mail["message_id"]))

                temperature, confidence = scoring.classify_reply(body)
                lead.temperature = models.Temperature(temperature)
                lead.confidence = confidence
                lead.priority = scoring.priority_bump(lead.priority, temperature)
                lead.last_inbound_at = datetime.utcnow()
                lead.status = models.LeadStatus.replied
                lead.followups_sent = 0
                db.commit()

                _notify(db, "reply",
                        f"Reply from {lead.name or lead.email} ({temperature})",
                        body[:400], agent_id=lead.agent_id)

                agent = db.get(models.Agent, lead.agent_id) if lead.agent_id else None
                campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
                cold_optout = temperature == "cold" and confidence >= 60
                if (agent and agent.is_active
                        and (campaign is None or campaign.status == "active")
                        and not cold_optout):
                    auto_reply.apply_async(args=[lead.id], countdown=_reply_delay(agent))
                processed += 1
    finally:
        db.close()
    return processed


# ---------------------------------------------------------------- outbound
@celery.task(name="app.tasks.auto_reply", bind=True, max_retries=2, default_retry_delay=120)
def auto_reply(self, lead_id: int):
    """Inbound replies are ALWAYS plain text — short, KB-first, meeting link direct."""
    db = SessionLocal()
    try:
        lead = db.get(models.Lead, lead_id)
        if not lead or not lead.agent_id:
            return "no-lead-or-agent"
        if lead.ai_paused:
            return "ai-paused-human-takeover"
        agent = db.get(models.Agent, lead.agent_id)
        if not agent or not agent.is_active:
            return "agent-paused"
        campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
        if campaign and campaign.status != "active":
            return "campaign-paused"
        if _daily_limit_reached(db, agent):
            auto_reply.apply_async(args=[lead_id], countdown=3600)
            return "daily-limit-requeued"

        subject, body, _ = (None, None, None)
        try:
            from .services import agentic
            subject, body = agentic.generate_reply_agentic(db, lead, agent)
        except Exception:
            subject, body, _ = llm_service.generate_email(
                db, lead, agent, purpose="reply",
                campaign_goal=campaign.goal if campaign else "",
                strategy=campaign.strategy if campaign else "B2B",
                use_template=False, campaign=campaign)
        last_in = next((m for m in reversed(lead.messages) if m.direction == "in"), None)
        try:
            msg_id = mailer.send_email(
                lead.email, subject, body,
                in_reply_to=last_in.message_id if last_in else "",
                use_html_template=False, agent_name=agent.name, agent=agent)
        except mailer.UnverifiedRecipient as e:
            _route_to_garbage(db, lead, f"unverified recipient: {e}")
            return "unverified-garbage"

        db.add(models.EmailMessage(lead_id=lead.id, agent_id=agent.id,
                                   direction="out", sent_by="agent",
                                   subject=subject, body=body, message_id=msg_id))
        lead.last_outbound_at = datetime.utcnow()
        db.commit()
        return "sent"
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery.task(name="app.tasks.start_campaign_lead", bind=True, max_retries=2, default_retry_delay=120)
def start_campaign_lead(self, lead_id: int):
    """Initial outreach: MX verify -> same-day dedupe -> DuckDuckGo advanced
    research -> persona email (template mode = HTML + Chatversio logo bottom,
    first touch only) -> send."""
    db = SessionLocal()
    try:
        lead = db.get(models.Lead, lead_id)
        if not lead or not lead.agent_id:
            return "no-lead-or-agent"
        if lead.unsubscribed:
            return "unsubscribed-skip"
        agent = db.get(models.Agent, lead.agent_id)
        campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
        if not agent or not agent.is_active or (campaign and campaign.status != "active"):
            return "paused"

        # SAME-DAY DEDUPE across agents
        clash = _lead_emailed_today_by_other_agent(db, lead, agent.id)
        if clash:
            delay = _seconds_until_tomorrow()
            start_campaign_lead.apply_async(args=[lead_id], countdown=delay)
            other = db.get(models.Agent, clash.agent_id)
            _notify(db, "warn",
                    f"Dedupe: {lead.email} already emailed today by "
                    f"{other.name if other else 'another agent'}",
                    f"{agent.name}'s email rescheduled for tomorrow.")
            return "dedupe-rescheduled"

        if _daily_limit_reached(db, agent):
            start_campaign_lead.apply_async(args=[lead_id], countdown=3600)
            return "daily-limit-requeued"

        # Mailbox verification right before send — the final real gate.
        # Free-only: MX + SMTP RCPT probe with catch-all detection.
        ok, reason = mailer.verify_recipient(lead.email)
        if not ok:
            _route_to_garbage(db, lead, f"unverified recipient: {reason}")
            _batch_progress(db, lead, ok=False)
            return "unverified-garbage"

        # DuckDuckGo research (company + person + website + country)
        if not lead.company_research and (lead.company or lead.website):
            research, pains = tavily.research_lead(
                lead.company, lead.name, lead.website, lead.country,
                db=db, lead_email=lead.email)
            lead.company_research = research
            lead.pain_points = pains
            db.commit()

        use_tpl = bool(campaign and campaign.template_mode == "template")
        subject, body, _ = llm_service.generate_email(
            db, lead, agent, purpose="initial",
            campaign_goal=campaign.goal if campaign else "",
            strategy=campaign.strategy if campaign else "B2B",
            use_template=use_tpl, campaign=campaign)
        if not lead.unsub_token:
            import secrets as _secrets
            lead.unsub_token = _secrets.token_urlsafe(24)
            db.commit()
        try:
            msg_id = mailer.send_email(lead.email, subject, body,
                                       use_html_template=use_tpl,
                                       agent_name=agent.name, agent=agent,
                                       unsub_token=lead.unsub_token)
        except mailer.UnverifiedRecipient as e:
            _route_to_garbage(db, lead, f"unverified recipient: {e}")
            _batch_progress(db, lead, ok=False)
            return "unverified-garbage"

        db.add(models.EmailMessage(lead_id=lead.id, agent_id=agent.id,
                                   direction="out", sent_by="agent",
                                   subject=subject, body=body,
                                   html_used=use_tpl, message_id=msg_id))
        lead.status = models.LeadStatus.contacted
        lead.email_verified = True
        lead.last_outbound_at = datetime.utcnow()
        db.commit()
        _batch_progress(db, lead, ok=True)
        return "sent"
    except Exception as exc:
        db.rollback()
        try:
            lead = db.get(models.Lead, lead_id)
            if lead and self.request.retries >= 2:
                _batch_progress(db, lead, ok=False)
        except Exception:
            pass
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------- follow-ups
@celery.task(name="app.tasks.followup_sweep")
def followup_sweep():
    db = SessionLocal()
    scheduled = 0
    try:
        leads = (db.query(models.Lead)
         .filter(models.Lead.status == models.LeadStatus.contacted,
                 models.Lead.last_outbound_at.isnot(None),
                 models.Lead.followups_sent < settings.MAX_FOLLOWUPS,
                 models.Lead.agent_id.isnot(None))
         .all())
        for lead in leads:
            if lead.last_inbound_at and lead.last_inbound_at > lead.last_outbound_at:
                continue
            agent = db.get(models.Agent, lead.agent_id)
            campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
            if not agent or not agent.is_active or (campaign and campaign.status != "active"):
                continue
            # Per-agent timing: use agent.followup_after_hours if set, else global setting
            agent_hours = getattr(agent, "followup_after_hours", None) or settings.FOLLOWUP_AFTER_HOURS
            cutoff = datetime.utcnow() - timedelta(hours=agent_hours)
            if lead.last_outbound_at >= cutoff:
                continue  # not yet time for this agent's followup
            lead.followups_sent += 1
            lead.last_outbound_at = datetime.utcnow()
            db.commit()
            send_followup.apply_async(args=[lead.id], countdown=_outbound_delay(agent))
            scheduled += 1
    finally:
        db.close()
    return scheduled


@celery.task(name="app.tasks.send_followup", bind=True, max_retries=2, default_retry_delay=120)
def send_followup(self, lead_id: int):
    """Follow-ups are ALWAYS plain text (template only on very first touch)."""
    db = SessionLocal()
    try:
        lead = db.get(models.Lead, lead_id)
        if not lead:
            return "no-lead"
        if lead.unsubscribed:
            return "unsubscribed-skip"
        if lead.ai_paused:
            return "ai-paused-human-takeover"
        agent = db.get(models.Agent, lead.agent_id) if lead.agent_id else None
        if not agent or not agent.is_active:
            return "agent-paused"
        if _lead_emailed_today_by_other_agent(db, lead, agent.id):
            send_followup.apply_async(args=[lead_id], countdown=_seconds_until_tomorrow())
            return "dedupe-rescheduled"
        if _daily_limit_reached(db, agent):
            send_followup.apply_async(args=[lead_id], countdown=3600)
            return "daily-limit-requeued"
        campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
        # Pass which follow-up number this is so the LLM applies the correct
        # tone from BASE_RULES (natural / direct / final-close)
        followup_goal = f"FOLLOWUP_NUMBER={lead.followups_sent} — see BASE_RULES for exact tone."
        subject, body, _ = llm_service.generate_email(
            db, lead, agent, purpose="followup",
            campaign_goal=followup_goal,
            strategy=campaign.strategy if campaign else "B2B",
            use_template=False, campaign=campaign)
        last_out = next((m for m in reversed(lead.messages) if m.direction == "out"), None)
        if not lead.unsub_token:
            import secrets as _secrets
            lead.unsub_token = _secrets.token_urlsafe(24)
            db.commit()
        try:
            msg_id = mailer.send_email(lead.email, subject, body,
                                       in_reply_to=last_out.message_id if last_out else "",
                                       use_html_template=False, agent_name=agent.name, agent=agent,
                                       unsub_token=lead.unsub_token)
        except mailer.UnverifiedRecipient as e:
            _route_to_garbage(db, lead, f"unverified recipient: {e}")
            return "unverified-garbage"
        db.add(models.EmailMessage(lead_id=lead.id, agent_id=agent.id,
                                   direction="out", sent_by="agent",
                                   subject=subject, body=body, message_id=msg_id))
        # After the final follow-up (3rd), mark lead as closed — never contact again
        max_fu = settings.MAX_FOLLOWUPS
        if lead.followups_sent >= max_fu:
            lead.status = models.LeadStatus.closed
            db.add(models.EmailMessage(
                lead_id=lead.id, agent_id=agent.id, direction="out",
                subject="(sequence closed — no reply after 3 outbounds)",
                body=f"Lead closed automatically after {max_fu} follow-up(s) with no reply.",
                sent_by="system"))
            _notify(db, "info",
                    f"Lead {lead.email} closed",
                    f"No reply after {max_fu} follow-ups. Marked as closed — will not be contacted again.",
                    agent_id=agent.id)
        db.commit()
        return "sent"
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------- maintenance
@celery.task(name="app.tasks.purge_garbage")
def purge_garbage():
    """Auto-delete old garbage so memory/DB size never balloons (daily)."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=settings.GARBAGE_RETENTION_DAYS)
        n = (db.query(models.EmailMessage)
             .filter(models.EmailMessage.is_spam.is_(True),
                     models.EmailMessage.created_at < cutoff)
             .delete(synchronize_session=False))
        db.commit()
        return n
    finally:
        db.close()



@celery.task(name="app.tasks.daily_backup")
def daily_backup():
    """Runs once a day via beat: safe DB backup + retention cleanup."""
    from .services import backup
    return backup.run_backup()