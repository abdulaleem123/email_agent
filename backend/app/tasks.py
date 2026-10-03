"""All mail movement through Celery (worker) + Celery Beat (schedules).

Rules enforced here:
- Outbound stagger 3–12 min per agent (configurable per agent)
- Inbound auto-reply delay ~15 min (per agent), plain-text only, KB-first
- SAME-DAY DEDUPE: if any agent already emailed a lead today, another agent
  cannot email that lead until tomorrow (rescheduled + notification raised)
- Per-agent daily caps (no batch objects involved anywhere in this flow —
  campaigns only report how many leads went out; batch bookkeeping for the
  UI lives in Mail Records)
- MX-unverified recipients + blocked role/disposable addresses -> ESCALATION
  (a human decides), never sent, and the lead is auto-paused
- Inbound meeting links / promotions / role-account replies / bounces ->
  ESCALATION, never auto-replied to
- Garbage auto-purge after GARBAGE_RETENTION_DAYS; escalations auto-purge
  after ESCALATION_RETENTION_DAYS; leads with no activity for
  STALE_LEAD_DAYS move to Garbage (both daily beats)
"""
import random
from datetime import datetime, timedelta
from .celery_app import celery
from .database import SessionLocal
from .config import settings
from . import models, audit
from .services import spam_filter, scoring, mailer, tavily
from .services import outbound as outbound_guard
from .services import health as health_service
from .services import llm as llm_service
from .services import intent as intent_service, subjects as subject_service
from .services import playbook, targeting as targeting_service
from .services import agent_settings


def _notify(db, kind: str, title: str, body: str = "", agent_id: int | None = None):
    db.add(models.Notification(kind=kind, title=title[:300], body=body[:2000], agent_id=agent_id))
    db.commit()




def _get_setting_int(db, key: str, fallback: int) -> int:
    from .routers.app_settings import get_runtime_setting
    val = get_runtime_setting(db, key)
    if val is None:
        return fallback
    try:
        return int(val)
    except (TypeError, ValueError):
        return fallback


def _outbound_delay_bounds(agent, db=None) -> tuple[int, int]:
    """The (min, max) spacing for an agent.

    The agent's own values win when it has them; anything it leaves unset falls
    back to the Settings page, so changing the delay there actually changes it
    instead of being masked by a hardcoded default."""
    lo = getattr(agent, "outbound_delay_min", None)
    hi = getattr(agent, "outbound_delay_max", None)
    if lo is None or hi is None:
        close = False
        if db is None:
            db = SessionLocal()
            close = True
        try:
            if lo is None:
                lo = _get_setting_int(db, "outbound_delay_min", settings.OUTBOUND_DELAY_MIN_SECONDS)
            if hi is None:
                hi = _get_setting_int(db, "outbound_delay_max", settings.OUTBOUND_DELAY_MAX_SECONDS)
        finally:
            if close:
                db.close()
    return int(lo), int(hi)


def _outbound_delay(agent, db=None) -> int:
    lo, hi = _outbound_delay_bounds(agent, db)
    return random.randint(min(lo, hi), max(lo, hi))


def _reply_delay(agent, db=None) -> int:
    if agent.reply_delay_seconds is not None:
        return agent.reply_delay_seconds
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        return _get_setting_int(db, "inbound_reply_delay", settings.INBOUND_REPLY_DELAY_SECONDS)
    finally:
        if close:
            db.close()

def _today_start() -> datetime:
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def _daily_limit(db, agent) -> int:
    """The effective per-agent-per-day outbound cap.

    Two knobs can set it: the agent's own `daily_send_limit` and the global
    `daily_send_limit` on the Settings page. The global value is a CEILING, so
    the effective limit is always the smaller of the two non-zero numbers. That
    way an operator can tighten sending from one place for every agent, and
    tighten it further on an individual agent, but can never accidentally undo
    the global cap by editing an agent.
    """
    agent_cap = int(getattr(agent, "daily_send_limit", 0) or 0)
    global_cap = _get_setting_int(db, "daily_send_limit", settings.DAILY_SEND_LIMIT)
    caps = [c for c in (agent_cap, global_cap) if c and c > 0]
    return min(caps) if caps else (agent_cap or global_cap or 150)


def _daily_limit_reached(db, agent) -> bool:
    sent_today = (db.query(models.EmailMessage)
                  .filter(models.EmailMessage.agent_id == agent.id,
                          models.EmailMessage.direction == "out",
                          models.EmailMessage.created_at >= _today_start())
                  .count())
    return sent_today >= _daily_limit(db, agent)


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


def _park_until_tomorrow(task, *args) -> str:
    """Hold a send back until the daily quota resets.

    The cap is a PER-DAY number, so once an agent is at its limit it stays at
    its limit until the day rolls over — there is nothing to gain by waking up
    every hour to be told the same thing. With 80k leads queued that hourly
    retry was 80k pointless broker messages a day; parking until tomorrow keeps
    the queue honest and the broker quiet. The lead is never dropped: its task
    is simply re-scheduled, and the batch/lead stays 'enrolled'."""
    task.apply_async(args=list(args), countdown=_seconds_until_tomorrow())
    return "daily-limit-requeued"


def _route_to_garbage(db, lead, reason: str, *, subject: str = "(blocked before send)",
                      body: str = "", spam_reason: str | None = None):
    lead.status = models.LeadStatus.garbage
    db.add(models.EmailMessage(
        lead_id=lead.id, agent_id=lead.agent_id, direction="out",
        subject=subject, body=body or "",
        is_spam=True, spam_reason=spam_reason or reason))
    db.commit()


def _route_to_escalation(db, lead, reason: str, *, subject: str = "",
                         body: str = "", direction: str = "out",
                         hide_from_messages: bool = True):
    """Park something on the Escalation page instead of sending it or dumping
    it in Garbage. Escalation rows are NOT spam and NOT garbage: they are
    excluded from Mail Records, the agent never auto-replies to them, and they
    self-purge after ESCALATION_RETENTION_DAYS.

    hide_from_messages=True also sets lead.escalated, which REMOVES the thread
    from Messages (that is what "escalated" means: parked out of sight until a
    human hits Resume).

    hide_from_messages=False is the human-review path: the escalation row is
    still written for the Escalation page, but the thread STAYS visible in
    Messages so the operator can read the conversation and reply themselves.
    In that case the lead is marked needs_human + ai_paused instead, which is
    what stops the agent writing back on its own."""
    if lead is not None:
        if hide_from_messages:
            lead.escalated = True
            lead.escalation_reason = reason[:300]
        else:
            lead.needs_human = True
            lead.needs_human_reason = reason[:300]
            lead.ai_paused = True
    db.add(models.EmailMessage(
        lead_id=lead.id if lead else None, agent_id=lead.agent_id if lead else None,
        direction=direction, sent_by="system",
        subject=subject or f"(escalated — {reason})", body=body or reason,
        is_escalation=True, escalation_reason=reason[:300]))
    db.commit()


def _park_not_interested(db, lead, agent, campaign, note: str,
                         *, subject: str = "") -> str:
    """They said "not interested" / "we don't want to work". Go SILENT and park
    the lead.

    No reply is sent — answering a decline is exactly how an engine loses
    credibility. The lead is moved to the Garbage inbox (reviewable, not
    deleted), the agent is auto-paused on it, and `garbage_at` starts the
    campaign's retention clock so the daily purge deletes it for good after
    30 days by default.

    If the campaign is configured as action='close' instead, the lead is closed
    without touching Garbage (kept for campaigns that want the lead back)."""
    now = datetime.utcnow()
    action = (getattr(campaign, "not_interested_action", "") or "garbage").lower()
    lead.not_interested = True
    lead.not_interested_at = now
    lead.not_interested_note = (note or "not interested")[:300]
    lead.ai_paused = True                      # agent never writes again
    lead.followups_sent = 999                  # belt & braces on the sweeps
    # NOT INTERESTED -> the lead is COLD, full stop. The conversation itself is
    # neither deleted nor hidden: it stays readable in the Messages page while
    # the lead is parked in Trash (the Garbage inbox) for the retention window.
    lead.temperature = models.Temperature.cold
    lead.confidence = max(int(lead.confidence or 0), 90)
    if action == "close":
        lead.status = models.LeadStatus.closed
    else:
        lead.status = models.LeadStatus.garbage
        lead.garbage_at = now
    db.add(models.EmailMessage(
        lead_id=lead.id, agent_id=agent.id if agent else lead.agent_id,
        direction="out", sent_by="system",
        subject=subject or "(not interested — sequence ended, lead moved to Trash)",
        body=(note or "Prospect said they are not interested.")
             + " Follow-up sequence ended: no reply and no further email. "
               "Lead marked COLD, conversation kept in Messages, lead moved to Trash."
             + (" Agent auto-paused."
                if action != "close" else " Thread closed."),
        is_spam=(action != "close"),
        spam_reason=("not-interested" if action != "close" else "")))
    db.commit()
    _notify(db, "info",
            f"Not interested: {lead.name or lead.email}",
            ("Sequence ended. Lead marked COLD, conversation kept in Messages, "
             "lead moved to Trash and purged after the retention window."
             if action != "close" else
             "Agent paused, no reply sent. Thread closed."),
            agent_id=lead.agent_id)
    return "parked-not-interested"


def _include_unsubscribe(campaign) -> bool:
    """Unsubscribe: the default is REMOVE the link.

    The link only comes back when the campaign exists AND the operator
    deliberately unticks the "Unsubscribe" part of the selection box."""
    if campaign is None:
        return False
    return not agent_settings.is_on(campaign, "unsubscribe")


def _part_allowed(campaign, key: str) -> bool:
    """May this part of the agent act? Selection box decides; no campaign means
    every part applies, which is the default prompt's behaviour."""
    return campaign is None or agent_settings.is_on(campaign, key)


def _subject_word_cap(campaign) -> int:
    """Subject: 3 words is the aim, 4 the hard ceiling, whenever the
    (optional) Subject part of the selection box is on — the default. One
    definition, shared with the subject builder and the preview so they can
    never disagree."""
    return subject_service.subject_word_cap(campaign)


def _seconds_until_schedule(campaign, now: datetime | None = None) -> int:
    """How long until the campaign's follow-up window opens again.

    0 = it is open right now (day allowed AND the configured time has come).
    Otherwise the number of seconds until the next moment it is — used to
    defer a follow-up instead of sending it on a day or at an hour the
    operator did not configure."""
    now = now or datetime.utcnow()
    if agent_settings.schedule_ok(campaign, now):
        return 0
    raw = ((getattr(campaign, "followup_time", "") or "").strip()
           if campaign is not None else "")
    hh, mm = 9, 0
    if len(raw) >= 5:
        try:
            hh, mm = int(raw[0:2]), int(raw[3:5])
        except (TypeError, ValueError):
            hh, mm = 9, 0
    if not raw:
        hh, mm = now.hour, now.minute      # no time gate -> just advance a day
    for offset in range(0, 9):
        day = (now + timedelta(days=offset)).replace(
            hour=hh, minute=mm, second=0, microsecond=0)
        if day <= now:
            continue
        if agent_settings.day_allowed(campaign, day):
            return max(60, int((day - now).total_seconds()))
    return 3600


def _followup_plan(campaign) -> list[float]:
    """Parse a campaign's days-wise follow-up plan.

    Accepts "3,7,14", "3, 7, 14" and fractional days ("0.5,2,5") so a team can
    put the first nudge in a few hours. Returns [] when the campaign has no plan
    (legacy stage-hour timing applies) or nothing usable in the field."""
    raw = (getattr(campaign, "followup_plan", "") or "").strip() if campaign else ""
    if not raw:
        return []
    out: list[float] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip().rstrip("dD").strip()
        if not part:
            continue
        try:
            val = float(part)
        except ValueError:
            continue
        if 0 <= val <= 365:
            out.append(val)
    return out


def _targeting_gate(db, lead, agent, campaign=None) -> str:
    """Final code-level check of the agent's targeting rules, run immediately
    before anything is generated or sent. Returns '' when the lead may be
    contacted, otherwise the rule it failed.

    Enrolling already filters on these, but a rule can be added AFTER a lead
    was queued, and "never email recruiters / our competitors" has to hold
    even then. Prompt rules are not a gate; this is.

    The campaign's selection box decides which halves are in force: a campaign
    that unticks "Excluded titles" or "Target titles" is not bound by them."""
    if agent is None:
        return ""
    return targeting_service.exclusion_reason(
        agent, lead,
        parts=agent_settings.enabled_keys(campaign) if campaign is not None else None)


def _subject_for_lead(lead, campaign, agent, *, llm_subject: str = "", **kwargs) -> str:
    """A short subject that is ABOUT the email that is about to go out.

    First choice is the subject the model wrote alongside the body — it was
    drafted from the same content, so it names the actual topic instead of a
    generic line. It only gets to pick the WORDS: `subjects.fit_llm_subject`
    forces the house format on it (3 words, 4 the hard max, sentence case, no
    Re:/Fwd:, no banned opener, no AI/marketing fluff) and drops it when
    nothing usable is left.

    Fallback — and the normal path when the model gives nothing usable — is the
    code-owned bank, so the only way a banned phrase gets in is if it is also
    in the bank. Rebuild with the offending candidate marked as taken until the
    line is clean.

    When the campaign has the Subject part switched on (the default) the
    word limit is hard-capped at 4 words — the UI instruction is a code
    guarantee, not a hope."""
    cap = _subject_word_cap(campaign)
    taken = {s.lower() for s in (kwargs.get("used")
                                 or subject_service._used_subjects(lead))}
    subject = ""
    if llm_subject:
        cand = subject_service.fit_llm_subject(llm_subject, max_words=cap,
                                               lead=lead, taken=taken)
        if cand:
            subject = cand
    if not subject:
        # Second choice: a topic line from the DuckDuckGo research / pain
        # points — the subject still names what the search found about THIS
        # company instead of jumping straight to the generic bank.
        subject = subject_service.research_subject(lead, max_words=cap,
                                                   taken=taken)
    if not subject:
        subject = subject_service.build_subject(lead, campaign, **kwargs)
    phrases = playbook.avoid_phrases(agent)
    for _ in range(5):
        if not playbook.contains_any(subject, phrases):
            break
        used = set(subject_service._used_subjects(lead)) | {subject.lower()}
        nxt = subject_service.build_subject(lead, campaign, used=used, **kwargs)
        if not nxt or nxt == subject:
            break
        subject = nxt
    subject = playbook.scrub(subject, agent) or subject
    # FINAL HOUSE FORMAT — a COMPLETE 3–4 word line, sentence case, and never a
    # "?" or "!": a 1–2 word fragment reads unfinished, and an interrogative
    # subject reads like a cold-sales tease. The ceiling is 3 or 4 (the
    # campaign's own cap, kept inside the 3–4 window), so nothing longer
    # survives either.
    ceiling = 4 if campaign is None else max(3, min(4, _subject_word_cap(campaign)))
    subject = subject.replace("?", "").replace("!", "").strip()
    subject = subject_service._normalise(subject, ceiling) or subject
    tries = 0
    while len(subject.split()) < 3 and tries < 6:
        tries += 1
        used = ({str(s).lower() for s in (kwargs.get("used") or [])}
                | set(subject_service._used_subjects(lead))
                | {subject.lower()})
        nxt = (subject_service.research_subject(lead, max_words=4, taken=used)
               or subject_service.build_subject(lead, campaign, used=used,
                                                **{k: v for k, v in kwargs.items()
                                                   if k != "used"}))
        if not nxt or nxt == subject:
            break
        subject = nxt
    subject = subject_service._normalise(subject, ceiling) or subject
    subject = subject.replace("?", "").replace("!", "").strip()
    return subject


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
        # Written the instant Beat hands us the task: proves the scheduler is
        # firing even if this cycle goes on to fail. See services/health.py.
        health_service.heartbeat(db, "beat", "poll_inbox scheduled")
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

        # How many inbound messages one cycle reads per mailbox, from the
        # Settings page. A huge backlog is picked up across several cycles
        # instead of in one long IMAP session.
        poll_size = _get_setting_int(db, "email_poll_size", settings.EMAIL_POLL_SIZE)

        for mb_agent, creds in mailboxes:
            try:
                fetched = mailer.fetch_unseen(creds, limit=poll_size)
            except Exception:
                continue                  # one broken mailbox must not stop the rest
            for mail in fetched:
                sender, subject, body = mail["from"], mail["subject"], mail["body"]

                # ── ESCALATION GATE ────────────────────────────────────────
                # Delivery failures, meeting links, promotions, role-account
                # replies, system notifications and disposables all stop here.
                # They are recorded on the Escalation page (never in Mail
                # Records, never in Garbage), never become a lead, and NEVER
                # trigger an auto-reply — a human has to decide.
                escalate, esc_reason = spam_filter.classify_escalation(
                    sender, subject, body)
                if escalate:
                    lead = db.query(models.Lead).filter(
                        models.Lead.email == sender.lower()).first()
                    if esc_reason == "delivery-failed":
                        # A parsed bounce is the most reliable "this mailbox is
                        # dead" signal there is — mark the address unverified
                        # and retire the lead.
                        known = {l.email.lower()
                                 for l in db.query(models.Lead.email).all()}
                        bounced = spam_filter.extract_bounced_recipient(body, known)
                        bad_lead = (db.query(models.Lead)
                                    .filter(models.Lead.email == bounced).first()
                                    if bounced else lead)
                        if bad_lead:
                            bad_lead.email_verified = False
                            bad_lead.status = models.LeadStatus.garbage
                    if lead is not None:
                        # Pause the thread — no follow-ups, no auto-replies
                        # until someone clears the escalation.
                        lead.escalated = True
                        lead.escalation_reason = esc_reason[:300]
                    db.add(models.EmailMessage(
                        lead_id=lead.id if lead else None,
                        agent_id=(mb_agent.id if mb_agent
                                  else (lead.agent_id if lead else None)),
                        direction="in", from_addr=sender, subject=subject,
                        body=body[:5000], is_escalation=True,
                        escalation_reason=esc_reason[:300],
                        message_id=mail["message_id"]))
                    db.commit()
                    processed += 1
                    continue

                # Worthless junk (scam keywords / link-stuffed blasts) — the
                # one bucket that really is garbage.
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

                agent = db.get(models.Agent, lead.agent_id) if lead.agent_id else None
                campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None

                # ── INTENT GATE ─────────────────────────────────────────────
                # Decided here, from patterns, before anything is generated.
                #
                #  1. "not interested" / "we don't want to work"  -> go SILENT
                #     and park the lead in Garbage on the campaign's 30-day
                #     clock. No reply is ever sent.
                #  2. pricing / contract / legal / security / "who are you"
                #     -> NEVER answered by the AI. Auto-pause the agent,
                #     escalate for a human, keep the thread in Messages so the
                #     human can answer it themselves.
                intent = intent_service.classify(body)

                if intent.not_interested and _part_allowed(campaign, "not_interested"):
                    _park_not_interested(db, lead, agent, campaign,
                                         intent_service.describe(intent),
                                         subject=subject[:300])
                    processed += 1
                    continue

                # INTERESTED -> the lead is HOT. The message itself is a normal
                # inbound row (never spam, never an escalation) so the thread
                # stays exactly where it was: in the Messages page.
                if intent.interested and _part_allowed(campaign, "interested"):
                    lead.temperature = models.Temperature.hot
                    lead.confidence = max(int(lead.confidence or 0), 80)
                    lead.priority = scoring.priority_bump(lead.priority, "hot")
                    db.commit()

                if (intent.needs_human
                        and (campaign is None
                             or (campaign.pricing_policy or "escalate").lower()
                             == "escalate")):
                    # The prospect's own words are already stored as a normal
                    # inbound message, so the conversation is in Messages; this
                    # only adds the "a human must answer this" marker.
                    _route_to_escalation(
                        db, lead, f"needs-human:{intent.human_reason}",
                        subject=subject[:300], body=body[:4000], direction="in",
                        hide_from_messages=False)
                    _notify(db, "warn",
                            f"Human needed: {lead.name or lead.email}",
                            intent_service.describe(intent) +
                            " The thread stays in Messages — reply yourself or Resume the agent.",
                            agent_id=lead.agent_id)
                    processed += 1
                    continue

                _notify(db, "reply",
                        f"Reply from {lead.name or lead.email} ({temperature})",
                        body[:400], agent_id=lead.agent_id)

                cold_optout = temperature == "cold" and confidence >= 60
                if (agent and agent.is_active
                        and (campaign is None or campaign.status == "active")
                        and not cold_optout
                        and not lead.escalated
                        and not lead.needs_human
                        and not lead.not_interested):     # auto-paused → human decides
                    auto_reply.apply_async(args=[lead.id], countdown=_reply_delay(agent, db))
                processed += 1
        health_service.heartbeat(db, "worker", "poll cycle finished")
        health_service.heartbeat(
            db, "inbox", f"{len(mailboxes)} mailboxes · {processed} messages")
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
        if lead.escalated:
            return "escalation-paused"
        if lead.needs_human:
            return "needs-human-paused"
        if lead.not_interested:
            return "not-interested-silent"
        agent = db.get(models.Agent, lead.agent_id)
        if not agent or not agent.is_active:
            return "agent-paused"
        campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
        if campaign and campaign.status != "active":
            return "campaign-paused"
        # Never reply to/for worthless addresses — escalated for a human.
        block = spam_filter.block_reason_for_recipient(lead.email)
        if block:
            _route_to_escalation(db, lead, f"blocked-outbound: {block}")
            return "escalated-blocked-address"
        # Targeting rules still hold on the reply path: an excluded title or
        # company gets no answer from the agent either (subject to the
        # campaign's selection box).
        rule = _targeting_gate(db, lead, agent, campaign)
        if rule:
            _notify(db, "warn", f"Auto-reply withheld: {lead.email}",
                    f"{rule} — the agent's targeting rules silence this thread.",
                    agent_id=agent.id)
            return "excluded-targeting"
        # The subject of a REPLY keeps the thread intact, so it is the incoming
        # subject (trimmed to the house 3-word aim, 4-word max) rather than a
        # new one.
        last_in = next((m for m in reversed(lead.messages) if m.direction == "in"), None)
        if last_in is not None:
            intent = intent_service.classify(last_in.body)
            if intent.not_interested and _part_allowed(campaign, "not_interested"):
                _park_not_interested(db, lead, agent, campaign,
                                     intent_service.describe(intent),
                                     subject=last_in.subject[:300])
                return "parked-not-interested"
            if (intent.needs_human
                    and (campaign is None
                         or (campaign.pricing_policy or "escalate").lower() == "escalate")):
                _route_to_escalation(db, lead, f"needs-human:{intent.human_reason}",
                                     subject=last_in.subject[:300],
                                     body=last_in.body[:4000], direction="in",
                                     hide_from_messages=False)
                _notify(db, "warn",
                        f"Human needed: {lead.name or lead.email}",
                        intent_service.describe(intent), agent_id=agent.id)
                return "escalated-needs-human"
        if _daily_limit_reached(db, agent):
            return _park_until_tomorrow(auto_reply, lead_id)

        subject, body, _ = (None, None, None)
        try:
            from .services import agentic
            subject, body = agentic.generate_reply_agentic(db, lead, agent, campaign)
        except Exception:
            subject, body, _ = llm_service.generate_email(
                db, lead, agent, purpose="reply",
                campaign_goal=campaign.goal if campaign else "",
                strategy=campaign.strategy if campaign else "B2B",
                use_template=False, campaign=campaign)
        if last_in is not None:
            subject = subject_service._normalise(
                (subject or "").strip() or last_in.subject,
                _subject_word_cap(campaign))
        try:
            msg_id = mailer.send_email(
                lead.email, subject, body,
                in_reply_to=last_in.message_id if last_in else "",
                use_html_template=False, agent_name=agent.name, agent=agent)
        except mailer.UnverifiedRecipient as e:
            _route_to_escalation(db, lead, f"unverified-recipient: {e}")
            return "escalated-unverified"

        db.add(models.EmailMessage(lead_id=lead.id, agent_id=agent.id,
                                   direction="out", sent_by="agent",
                                   subject=subject, body=body, message_id=msg_id))
        # "NOT INTERESTED": we did NOT send a grace reply — poll_inbox parks
        # the lead before this task is ever queued. This guard covers a reply
        # that arrived while this task was already in flight: the words go
        # nowhere, the lead is parked, and the agent is paused.
        last_in = next((m for m in reversed(lead.messages) if m.direction == "in"), None)
        if last_in is not None:
            intent = intent_service.classify(last_in.body)
            if intent.not_interested and _part_allowed(campaign, "not_interested"):
                db.rollback()
                lead = db.get(models.Lead, lead_id)
                _park_not_interested(db, lead, agent, campaign,
                                     intent_service.describe(intent))
                return "parked-not-interested"
            if intent.needs_human and (campaign is None
                                       or (campaign.pricing_policy or "escalate").lower() == "escalate"):
                db.rollback()
                lead = db.get(models.Lead, lead_id)
                _route_to_escalation(db, lead, f"needs-human:{intent.human_reason}",
                                     subject=last_in.subject[:300],
                                     body=last_in.body[:4000], direction="in",
                                     hide_from_messages=False)
                return "escalated-needs-human"
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
        if lead.escalated:
            return "escalation-paused"
        if lead.needs_human:
            return "needs-human-paused"
        if lead.not_interested:
            return "not-interested-silent"
        agent = db.get(models.Agent, lead.agent_id)
        campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
        if not agent or not agent.is_active or (campaign and campaign.status != "active"):
            return "paused"

        # ONE INITIAL EMAIL PER LEAD — always. A lead can end up queued twice
        # (two enroll clicks, a re-enroll while the first send is still being
        # written, two batches over the same selection). The message table is
        # the source of truth: if a real outbound already exists for this lead,
        # this task is a duplicate and must not send again. Follow-ups are a
        # separate path (send_followup) and are not affected by this.
        if outbound_guard.already_contacted(db, lead):
            return "duplicate-initial-skipped"

        # NEVER contact worthless addresses (noreply@/info@/support@, Zoho/
        # Hostinger notification aliases, disposable mailboxes). Stopped
        # before anything is generated or sent → Escalation for a human.
        block = spam_filter.block_reason_for_recipient(lead.email)
        if block:
            _route_to_escalation(db, lead, f"blocked-outbound: {block}")
            _batch_progress(db, lead, ok=False)
            return "escalated-blocked-address"

        # AGENT TARGETING RULES — excluded job titles, excluded companies /
        # company types, target titles, target location. Checked here as well
        # as at enroll time so a rule added after queueing still holds: the
        # lead leaves the queue for Garbage and is never contacted.
        rule = _targeting_gate(db, lead, agent, campaign)
        if rule:
            _route_to_garbage(
                db, lead, f"targeting-rule: {rule}",
                subject=f"(not targeted — {rule})",
                body=f"{lead.email} was not contacted: {rule}.",
                spam_reason="excluded-targeting")
            _batch_progress(db, lead, ok=False)
            _notify(db, "warn", f"Skipped {lead.email}",
                    f"Not contacted — {rule}. The agent's targeting rules "
                    "decided this lead is out of scope.",
                    agent_id=agent.id)
            return "excluded-targeting"

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
            return _park_until_tomorrow(start_campaign_lead, lead_id)

        # Mailbox verification right before send — the final real gate.
        # Free-only: MX + SMTP RCPT probe with catch-all detection.
        ok, reason = mailer.verify_recipient(lead.email)
        if not ok:
            _route_to_escalation(db, lead, f"unverified-recipient: {reason}")
            _batch_progress(db, lead, ok=False)
            return "escalated-unverified"

        # DUCKDUCKGO RESEARCH — runs automatically before the first email, so
        # the draft is written about THIS company instead of "many companies
        # struggle...". Two things used to let it come back blank: no target
        # when company/website were empty, and a stale/short blob never being
        # refreshed. Both are closed here; the research goes straight into the
        # prompt below and the email goes out from the normal send path.
        company = (lead.company or "").strip()
        website = (lead.website or "").strip()
        if not company or not website:
            domain = (lead.email or "").split("@")[-1].strip().lower()
            if domain and "." in domain and not domain.startswith(("example.", "test.")):
                website = website or ("https://" + domain)
                if not company:
                    company = domain.split(".")[0].replace("-", " ").replace("_", " ").title()
        if (company or website) and len(lead.company_research or "") < 200:
            research, pains = tavily.research_lead(
                company, lead.name, website, lead.country,
                db=db, lead_email=lead.email)
            if research:
                lead.company_research = research
            if pains:
                lead.pain_points = pains
            db.commit()

        use_tpl = bool(campaign and campaign.template_mode == "template")
        subject, body, _ = llm_service.generate_email(
            db, lead, agent, purpose="initial",
            campaign_goal=campaign.goal if campaign else "",
            strategy=campaign.strategy if campaign else "B2B",
            use_template=use_tpl, campaign=campaign,
            first_email_length=(campaign.first_email_length if campaign else ""),
            offer_demo=bool(campaign.demo_offer) if campaign else True)
        # The subject is written FROM this email (the model drafts it with the
        # body), then hard-fitted to the house rule: 3 words (4 the hard max),
        # sentence case, aimed at this lead's country/region and this campaign's
        # angle, never a line this lead already received, and never a phrase
        # from the agent's Avoid Phrases list. Anything unusable falls back to
        # the code-owned bank, so a bad model subject can never go out.
        subject = _subject_for_lead(lead, campaign, agent, llm_subject=subject)
        if not lead.unsub_token:
            import secrets as _secrets
            lead.unsub_token = _secrets.token_urlsafe(24)
            db.commit()
        # CLAIM THE SEND. Two tasks can be racing on this lead (double queue,
        # double click, two batches over the same selection): take a row lock
        # and RE-CHECK the message table inside it. The loser blocks here for
        # the few seconds the winner needs to hand the mail to SMTP, then sees
        # the winner's email and backs off — the lead is never emailed twice.
        # The lock is released by the commit at the end of this task.
        db.commit()                                   # nothing pending — start clean
        db.query(models.Lead).filter(models.Lead.id == lead_id)\
          .with_for_update().first()
        if outbound_guard.already_contacted(db, lead):
            db.rollback()
            return "duplicate-initial-skipped"
        try:
            msg_id = mailer.send_email(lead.email, subject, body,
                                       use_html_template=use_tpl,
                                       agent_name=agent.name, agent=agent,
                                       unsub_token=(lead.unsub_token
                                                    if _include_unsubscribe(campaign) else ""))
        except mailer.UnverifiedRecipient as e:
            _route_to_escalation(db, lead, f"unverified-recipient: {e}")
            _batch_progress(db, lead, ok=False)
            return "escalated-unverified"

        db.add(models.EmailMessage(lead_id=lead.id, agent_id=agent.id,
                                   direction="out", sent_by="agent",
                                   subject=subject, body=body,
                                   html_used=use_tpl, message_id=msg_id))
        lead.last_outbound_subject = subject[:300]
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
                # Three strikes — the send itself is broken, not just the
                # address. Park it on the Escalation page for a human.
                if not lead.escalated:
                    _route_to_escalation(
                        db, lead, f"send-failed: {str(exc)[:200]}",
                        subject="(outbound send failed — escalated)",
                        body=f"{lead.email}: {str(exc)[:1500]}")
        except Exception:
            pass
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------- follow-ups
@celery.task(name="app.tasks.dispatch_batch", bind=True, max_retries=3, default_retry_delay=300)
def dispatch_batch(self, batch_id: int, cursor: int = 0):
    """Hand out ONE WINDOW of a batch, then re-schedule itself.

    Why windows instead of "send all 50 with a sleep between": the first
    version slept inside the worker, so one batch pinned a worker slot for
    hours (50 leads x up to 5 min) and 1 600 batches could never drain on a
    normal 2-4 worker box. Now each pass publishes a handful of send tasks with
    a per-lead countdown (so spacing is still the agent's real delay) and hands
    the rest of the batch back to the broker, releasing the worker immediately.

    The queue is derived from the DB, not from memory: batch -> leads by id.
    So if a worker dies mid-window, the next pass re-reads the same list and
    skips whatever already went out (leads that got an email are no longer
    'new'/'enrolled', and each send task is idempotent)."""
    WINDOW = 5                        # leads in flight per pass
    db = SessionLocal()
    try:
        batch = db.get(models.Batch, batch_id)
        if not batch:
            # Not visible yet — the task can beat the publisher's commit, and
            # answering "no-batch" here used to strand the batch at `pending`
            # with nothing left to ever pick it up. Short retry, then give up.
            try:
                raise self.retry(countdown=10)
            except self.MaxRetriesExceededError:
                return "no-batch"
        if batch.status in (models.BatchStatus.completed,
                            models.BatchStatus.cancelled):
            return f"batch-{batch.status}"
        leads = (db.query(models.Lead)
                 .filter(models.Lead.batch_id == batch_id)
                 .order_by(models.Lead.id).all())
        if not leads:
            batch.status = models.BatchStatus.completed
            db.commit()
            return "empty"
        agent = db.get(models.Agent, leads[0].agent_id) if leads[0].agent_id else None
        if not agent or not agent.is_active:
            return "agent-paused"

        campaign = (db.get(models.Campaign, leads[0].campaign_id)
                    if leads[0].campaign_id else None)
        if campaign and campaign.status != "active":
            return "campaign-paused"

        lo, hi = _outbound_delay_bounds(agent, db)
        step = max(60, (lo + hi) // 2)

        # Anything before the cursor that is still 'new'/'enrolled' was skipped
        # (already contacted, garbage…). Count it as failed so the batch can
        # actually reach completed instead of hanging at 80%.
        for lead in leads[:cursor]:
            if lead.status in (models.LeadStatus.new, models.LeadStatus.enrolled):
                batch.failed += 1
        batch.status = models.BatchStatus.running
        db.commit()

        window = [l for l in leads[cursor:cursor + WINDOW]
                  if l.status in (models.LeadStatus.new, models.LeadStatus.enrolled)]
        sent = 0
        for i, lead in enumerate(window):
            try:
                # Countdown per lead keeps the agent's spacing real without the
                # worker waiting: lead 1 now, lead 2 in `step` seconds, …
                start_campaign_lead.apply_async(
                    args=[lead.id], countdown=i * step)
                sent += 1
            except Exception as exc:           # broker hiccup → retry the batch
                db.rollback()
                raise self.retry(exc=exc)

        nxt = cursor + WINDOW
        if nxt < len(leads):
            try:
                dispatch_batch.apply_async(args=[batch_id, nxt],
                                           countdown=len(window) * step)
            except Exception as exc:
                db.rollback()
                raise self.retry(exc=exc)
            if cursor == 0:
                _notify(db, "ok", f"Batch #{batch.number} queued",
                        f"{len(leads)} lead(s) going out one at a time for "
                        f"{agent.name} (every ~{step // 60} min).", agent.id)
            return f"queued-{sent}-more"
        _notify(db, "ok", f"Batch #{batch.number} queued",
                f"{sent} lead(s) added to {agent.name}'s outbound queue.", agent.id)
        return f"queued-{sent}"
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery.task(name="app.tasks.followup_sweep")
def followup_sweep():
    """Days-wise + count-wise follow-ups, per campaign.

    Two scheduling styles, chosen per campaign:
      * followup_plan = "3,7,14"  → follow-up 1 on day 3 after the last outbound,
        follow-up 2 on day 7, follow-up 3 on day 14, and followup_count caps how
        many actually go out. This is the new default the user asked for.
      * followup_plan = ""        → the legacy followup_1/2/3_hours stage timing
        (24h/48h/72h by default), so campaigns created before this keep behaving
        exactly as they did.

    Either way: anything still unanswered when the plan is exhausted, or past
    followup_max_days, goes to Garbage and is never contacted again."""
    db = SessionLocal()
    scheduled = 0
    try:
        leads = (db.query(models.Lead)
         .filter(models.Lead.status == models.LeadStatus.contacted,
                 models.Lead.last_outbound_at.isnot(None),
                 models.Lead.agent_id.isnot(None),
                 models.Lead.escalated.is_(False),
                 # a decline is final: never swept, never followed up
                 models.Lead.needs_human.is_(False),
                 models.Lead.not_interested.is_(False))
         .all())
        for lead in leads:
            if lead.last_inbound_at and lead.last_inbound_at > lead.last_outbound_at:
                continue
            if lead.ai_paused or lead.unsubscribed:
                continue
            agent = db.get(models.Agent, lead.agent_id)
            campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
            if not agent or not agent.is_active or (campaign and campaign.status != "active"):
                continue

            # FOLLOW-UP SCHEDULE — days from Monday to Sunday + time of day.
            # Nothing is counted or queued outside the configured window; the
            # next sweep picks the same lead up once the window opens.
            if not agent_settings.schedule_ok(campaign, datetime.utcnow()):
                continue

            # HOW MANY follow-ups are allowed at all (count-wise). The campaign
            # wins, then the global setting, then the built-in default.
            max_fu = (campaign.followup_count if campaign and campaign.followup_count
                      else _get_setting_int(db, "max_followups", settings.MAX_FOLLOWUPS))
            plan = _followup_plan(campaign)

            # ── the sequence is over: close it out ────────────────────────
            if plan and lead.followups_sent >= min(max_fu, len(plan)):
                _route_to_garbage(
                    db, lead, "closed-no-reply",
                    subject="(sequence closed — no reply after the follow-up plan)",
                    body=(f"No reply after {lead.followups_sent} follow-up(s) "
                          f"(plan: day {', '.join(str(d) for d in plan)}). "
                          f"Moved to Garbage."),
                    spam_reason="closed-no-reply")
                _notify(db, "info",
                        f"Lead {lead.name or lead.email} closed → garbage",
                        f"Follow-up plan finished ({lead.followups_sent} sent) with no reply. "
                        f"Moved to Garbage — will not be contacted again.",
                        agent_id=agent.id)
                continue
            if not plan and lead.followups_sent >= max_fu:
                continue  # legacy: send_followup closes it after the last one

            # CAMPAIGN CLOSE WINDOW (days-wise): if the lead hasn't replied within
            # the campaign's own followup_max_days, or the global Settings value
            # when the campaign doesn't set one, auto-close the thread → Garbage.
            # It is NEVER contacted again after that.
            max_days = (campaign.followup_max_days if campaign and campaign.followup_max_days
                        else _get_setting_int(db, "followup_max_days",
                                              settings.FOLLOWUP_MAX_DAYS))
            if (lead.last_outbound_at
                    and lead.last_outbound_at + timedelta(days=max_days) < datetime.utcnow()):
                _route_to_garbage(
                    db, lead, "closed-no-reply-window",
                    subject="(sequence closed — no reply within window)",
                    body=f"No reply within {max_days} day(s). Moved to Garbage.",
                    spam_reason="closed-no-reply-window")
                _notify(db, "info",
                        f"Lead {lead.name or lead.email} closed → garbage",
                        f"No reply within {max_days} day(s). Moved to Garbage — will not be contacted again.",
                        agent_id=agent.id)
                continue

            stage = lead.followups_sent + 1                    # 1 → first follow-up
            if plan:
                # DAYS-WISE: offsets are days since the previous outbound, so a
                # plan of "3,7,14" means +3d, then +7d, then +14d.
                if stage > len(plan):
                    continue
                delay_days = plan[stage - 1]
            else:
                # Per-campaign STAGE timing: follow-up 1 → followup_1_hours (24h
                # default), follow-up 2 → followup_2_hours (48h), follow-up 3 →
                # followup_3_hours (72h). Falls back to the agent's
                # followup_after_hours, then the global setting.
                agent_hours = (getattr(agent, "followup_after_hours", None)
                               or _get_setting_int(db, "followup_after_hours", settings.FOLLOWUP_AFTER_HOURS))
                hours = None
                if campaign:
                    hours = {1: campaign.followup_1_hours,
                             2: campaign.followup_2_hours,
                             3: campaign.followup_3_hours}.get(stage)
                if not hours:
                    hours = agent_hours
                delay_days = max(0.0, hours / 24.0)
            cutoff = datetime.utcnow() - timedelta(days=delay_days)
            if lead.last_outbound_at >= cutoff:
                continue  # not yet time for this follow-up
            lead.followups_sent += 1
            lead.last_outbound_at = datetime.utcnow()
            db.commit()
            send_followup.apply_async(args=[lead.id], countdown=_outbound_delay(agent, db))
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
        if lead.escalated:
            return "escalation-paused"
        if lead.needs_human:
            return "needs-human-paused"
        if lead.not_interested:
            return "not-interested-silent"
        agent = db.get(models.Agent, lead.agent_id) if lead.agent_id else None
        if not agent or not agent.is_active:
            return "agent-paused"
        # Never reply to/for worthless addresses — escalated for a human.
        block = spam_filter.block_reason_for_recipient(lead.email)
        if block:
            _route_to_escalation(db, lead, f"blocked-outbound: {block}")
            return "escalated-blocked-address"
        # No follow-up for a lead the agent's own targeting rules exclude —
        # park it so the sweep stops walking a thread that must stay closed.
        campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
        rule = _targeting_gate(db, lead, agent, campaign)
        if rule:
            _route_to_garbage(
                db, lead, f"targeting-rule: {rule}",
                subject=f"(follow-up withheld — {rule})",
                body=f"{lead.email}: follow-up not sent, {rule}.",
                spam_reason="excluded-targeting")
            _notify(db, "warn", f"Follow-up withheld: {lead.email}",
                    f"{rule} — no further contact.", agent_id=agent.id)
            return "excluded-targeting"
        if _lead_emailed_today_by_other_agent(db, lead, agent.id):
            send_followup.apply_async(args=[lead_id], countdown=_seconds_until_tomorrow())
            return "dedupe-rescheduled"
        if _daily_limit_reached(db, agent):
            return _park_until_tomorrow(send_followup, lead_id)
        # FOLLOW-UP SCHEDULE — re-checked here as well as in the sweep, because
        # the countdown between the two can cross into a closed window.
        wait = _seconds_until_schedule(campaign)
        if wait:
            send_followup.apply_async(args=[lead_id], countdown=wait)
            return "followup-deferred-schedule"
        # Pass which follow-up number this is so the LLM applies the correct
        # tone from BASE_RULES (natural / direct / final-close)
        followup_goal = f"FOLLOWUP_NUMBER={lead.followups_sent} — see BASE_RULES for exact tone."
        # A follow-up must READ the thread, not talk into the void: pass the real
        # conversation so it can reference what was already said instead of
        # sending another "just following up". If the campaign turned memory off
        # we send the plan text only, which is the old behaviour.
        if campaign is not None and not campaign.followup_memory:
            followup_goal += " MEMORY=off — do not reference earlier emails."
        else:
            followup_goal += " MEMORY=on — read the thread summary and build on it."
        subject, body, _ = llm_service.generate_email(
            db, lead, agent, purpose="followup",
            campaign_goal=followup_goal,
            strategy=campaign.strategy if campaign else "B2B",
            use_template=False, campaign=campaign,
            use_thread_memory=bool(campaign.followup_memory) if campaign else True)
        # 3 words (4 max), sentence case, about THIS email, never a subject this
        # lead already got, and never one from the Avoid Phrases list — a
        # repeated or banned subject line is the loudest "automated sequence"
        # signal.
        subject = _subject_for_lead(lead, campaign, agent,
                                    followup_number=lead.followups_sent,
                                    llm_subject=subject)
        last_out = next((m for m in reversed(lead.messages) if m.direction == "out"), None)
        if not lead.unsub_token:
            import secrets as _secrets
            lead.unsub_token = _secrets.token_urlsafe(24)
            db.commit()
        try:
            msg_id = mailer.send_email(lead.email, subject, body,
                                       in_reply_to=last_out.message_id if last_out else "",
                                       use_html_template=False, agent_name=agent.name, agent=agent,
                                       unsub_token=(lead.unsub_token
                                                    if _include_unsubscribe(campaign) else ""))
        except mailer.UnverifiedRecipient as e:
            _route_to_escalation(db, lead, f"unverified-recipient: {e}")
            return "escalated-unverified"
        db.add(models.EmailMessage(lead_id=lead.id, agent_id=agent.id,
                                   direction="out", sent_by="agent",
                                   subject=subject, body=body, message_id=msg_id))
        lead.last_outbound_subject = subject[:300]
        # After the final follow-up, close the thread → Garbage. Which limit
        # applies depends on the campaign: a days-wise plan is closed by
        # followup_sweep once the plan is used up, a legacy campaign is closed
        # here once the count is reached.
        plan = _followup_plan(campaign)
        if plan:
            max_fu = min(campaign.followup_count or len(plan), len(plan))
        else:
            max_fu = _get_setting_int(db, "max_followups", settings.MAX_FOLLOWUPS)
        if lead.followups_sent >= max_fu and not plan:
            _route_to_garbage(
                db, lead, "closed-no-reply",
                subject=f"(sequence closed — no reply after {max_fu} outbounds)",
                body=f"Lead closed automatically after {max_fu} follow-up(s) with no reply.",
                spam_reason="closed-no-reply")
            _notify(db, "info",
                    f"Lead {lead.name or lead.email} closed → garbage",
                    f"No reply after {max_fu} follow-ups. Moved to Garbage — will not be contacted again.",
                    agent_id=agent.id)
            return "sent-closed-garbage"
        db.commit()
        return "sent"
    except Exception as exc:
        try:
            lead = db.get(models.Lead, lead_id)
            if lead and self.request.retries >= 2 and not lead.escalated:
                _route_to_escalation(
                    db, lead, f"send-failed: {str(exc)[:200]}",
                    subject="(follow-up send failed — escalated)",
                    body=f"{lead.email}: {str(exc)[:1500]}")
        except Exception:
            pass
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------- maintenance
def _delete_lead(db, lead) -> None:
    """Remove a lead and everything hanging off it, in FK-safe order.

    Mail records first, then the lead, so there is never a moment where a
    message points at a lead that is gone."""
    db.query(models.EmailMessage).filter(
        models.EmailMessage.lead_id == lead.id).delete(synchronize_session=False)
    db.delete(lead)
    db.commit()


@celery.task(name="app.tasks.purge_garbage")
def purge_garbage():
    """Auto-delete old garbage so memory/DB size never balloons (daily).

    Two separate purges:
      1. Spam mail records older than garbage_retention_days.
      2. Leads parked as "not interested" once their campaign's retention
         window has passed (default 30 days). This is the whole point of
         parking them instead of deleting them on the spot — the lead sits in
         Garbage where a human can still look at it, and only then goes away
         for good."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=_get_setting_int(db, "garbage_retention_days", settings.GARBAGE_RETENTION_DAYS))
        n = (db.query(models.EmailMessage)
             .filter(models.EmailMessage.is_spam.is_(True),
                     models.EmailMessage.created_at < cutoff)
             .delete(synchronize_session=False))
        db.commit()

        # Retention is per campaign, so each candidate's own campaign decides
        # how long it stays. Default 30 days when there is no campaign.
        candidates = (db.query(models.Lead)
                      .filter(models.Lead.not_interested.is_(True),
                              models.Lead.garbage_at.isnot(None))
                      .all())
        purged = 0
        for lead in candidates:
            campaign = db.get(models.Campaign, lead.campaign_id) if lead.campaign_id else None
            days = (campaign.not_interested_retention_days
                    if campaign and campaign.not_interested_retention_days
                    else _get_setting_int(db, "not_interested_retention_days", 30))
            if days <= 0:
                continue  # 0 = keep forever
            if lead.garbage_at + timedelta(days=days) > datetime.utcnow():
                continue
            _delete_lead(db, lead)
            purged += 1
        if purged:
            _notify(db, "info", f"Purged {purged} not-interested lead(s)",
                    "Retention window passed — deleted for good.")
        return {"spam_rows": n, "not_interested_leads": purged}
    finally:
        db.close()


@celery.task(name="app.tasks.purge_audit_logs")
def purge_audit_logs():
    """24h retention for the Super Admin audit trail.

    Runs hourly regardless of traffic so an install where nobody touches an
    admin endpoint still gets trimmed — otherwise the table would only ever
    shrink when someone opens the Audit logs page or performs an action."""
    db = SessionLocal()
    try:
        dropped = audit.purge_old(db)
        return {"dropped": dropped, "retention_hours": audit.RETENTION_HOURS}
    finally:
        db.close()


@celery.task(name="app.tasks.purge_escalations")
def purge_escalations():
    """Escalations run on their OWN retention clock (default 30 days), separate
    from garbage. If nobody acted on a meeting link / promotion / delivery
    failure by then, the row is dropped for good — nothing else is written,
    because the escalation IS the record and the lead already carries the
    auto-pause."""
    db = SessionLocal()
    try:
        days = _get_setting_int(db, "escalation_retention_days",
                                settings.ESCALATION_RETENTION_DAYS)
        cutoff = datetime.utcnow() - timedelta(days=days)
        # A needs-human escalation is a live to-do, not a stale record. The
        # lead's needs_human flag is what silences the agent, so purging the row
        # while it is unresolved would leave the thread muted with nothing left
        # on the Escalation page to explain why. Those keep their own clock and
        # are only dropped once a human closes them out.
        stale_ids = [i for (i,) in db.query(models.EmailMessage.id)
                     .filter(models.EmailMessage.is_escalation.is_(True),
                             models.EmailMessage.created_at < cutoff).all()]
        if not stale_ids:
            return 0
        keep = {lid for (lid,) in db.query(models.Lead.id)
                .filter(models.Lead.id.in_([
                    e.lead_id for e in db.query(models.EmailMessage)
                    .filter(models.EmailMessage.id.in_(stale_ids)).all() if e.lead_id]),
                    models.Lead.needs_human.is_(True)).all()} if stale_ids else set()
        live_ids = {e.id for e in db.query(models.EmailMessage)
                    .filter(models.EmailMessage.id.in_(stale_ids),
                            models.EmailMessage.lead_id.in_(keep)).all()} if keep else set()
        stale_ids = [i for i in stale_ids if i not in live_ids]
        # Delete and nothing else. An escalation is NOT garbage and NOT a mail
        # record — writing a marker row here would put the purge notice into
        # exactly the two places the user asked us to keep it out of. The lead
        # keeps its auto-pause (leads.escalated) until a human hits Resume.
        n = (db.query(models.EmailMessage)
             .filter(models.EmailMessage.id.in_(stale_ids))
             .delete(synchronize_session=False))
        db.commit()
        return n
    finally:
        db.close()


@celery.task(name="app.tasks.stale_leads_sweep")
def stale_leads_sweep():
    """Everything that has gone quiet for STALE_LEAD_DAYS (default 30) goes to
    Garbage — no exceptions. Awaiting-reply threads, dead conversations,
    escalated threads, even leads that were uploaded and never sent. A lead's
    "last activity" is the newest of: upload date, last outbound, last inbound,
    so a 90-day-old sheet that was enrolled yesterday is judged on yesterday.

    This is the hard backstop for the Messages page: anything still sitting
    there without a live conversation gets retired here instead of clogging the
    hot-lead list forever."""
    db = SessionLocal()
    try:
        days = _get_setting_int(db, "stale_lead_days", settings.STALE_LEAD_DAYS)
        cutoff = datetime.utcnow() - timedelta(days=days)
        live = (models.LeadStatus.new, models.LeadStatus.enrolled,
                models.LeadStatus.contacted, models.LeadStatus.replied)
        leads = (db.query(models.Lead)
                 .filter(models.Lead.status.in_(live))
                 .all())
        moved = 0
        for lead in leads:
            last = max([d for d in (lead.last_outbound_at, lead.last_inbound_at,
                                    lead.created_at) if d is not None] or [None])
            if last is None or last >= cutoff:
                continue
            # A thread that is waiting on a human is a live to-do, not a stale
            # lead. Retiring it to Garbage would hide the very conversation
            # somebody still has to answer.
            if lead.needs_human or lead.escalated:
                continue
            lead.status = models.LeadStatus.garbage
            moved += 1
            db.add(models.EmailMessage(
                lead_id=lead.id, agent_id=lead.agent_id, direction="out",
                sent_by="system",
                subject=f"(auto-garbage — no activity for {days} days)",
                body=f"No inbound, no outbound and no reply for {days} days. "
                     f"Moved to Garbage — no agent will contact this lead again.",
                is_spam=True, spam_reason=f"stale-{days}d-no-activity"))
        db.commit()
        return moved
    finally:
        db.close()


@celery.task(name="app.tasks.daily_backup")
def daily_backup():
    """Runs once a day via beat: safe DB backup + retention cleanup."""
    from .services import backup
    return backup.run_backup()