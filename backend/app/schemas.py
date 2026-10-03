from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator
 
 
class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = ""
    avatar_url: str = ""
    description: str = ""
    persona_prompt: str = ""
    sentiment_prompt: str = ""
    country_prompt: str = ""
    judgment_prompt: str = ""
    pitch_style: str = ""
    # who to target, what to present, what never to say — enforced in code too
    persona: str = ""
    why_you: str = ""
    target_titles: str = ""
    target_location: str = ""
    excluded_titles: str = ""
    excluded_companies: str = ""
    solutions: str = ""
    avoid_phrases: str = ""
    extra_instructions: str = ""
    tone: str = "professional"
    message_length: str = "medium"
    project_url: str = ""
    meeting_url: str = ""
    signature: str = ""
    daily_send_limit: int = Field(default=150, ge=1, le=2000)
    outbound_delay_min: int = Field(default=180, ge=30, le=7200)
    outbound_delay_max: int = Field(default=720, ge=30, le=14400)
    reply_delay_seconds: int = Field(default=900, ge=30, le=7200)
    # per-agent mailbox (passwords write-only: never echoed back by the API)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    imap_host: str = ""
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_user: str = ""
    imap_password: str = ""
 
    @field_validator("tone")
    @classmethod
    def tone_ok(cls, v):
        assert v in {"professional", "friendly", "casual", "formal"}
        return v

    @field_validator("persona")
    @classmethod
    def persona_ok(cls, v):
        """One of the four shipped voices; '' falls back to the agent's name."""
        v = (v or "").strip().lower()
        if v in ("", "custom", "dawod", "dawood"):
            return "dawood" if v in ("dawod", "dawood") else ""
        assert v in {"osaja", "saif", "aleem", "dawood"}, "unknown persona"
        return v
 
    @field_validator("message_length")
    @classmethod
    def len_ok(cls, v):
        assert v in {"short", "medium", "long"}
        return v
 
 
class LaunchIn(BaseModel):
    """Body for POST /api/campaigns/{cid}/launch — frontend always sends {lead_ids: [...]}."""
    lead_ids: List[int] 
 
class AgentCreate(AgentBase):
    pass
 
 
class AgentOut(AgentBase):
    id: int
    is_active: bool
    created_at: datetime
    smtp_configured: bool = False
    imap_configured: bool = False
 
    @field_validator("smtp_password", "imap_password", mode="after")
    @classmethod
    def _mask(cls, v):          # write-only: API responses never leak passwords
        return ""
 
    class Config:
        from_attributes = True
 
 
class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str = ""
    strategy: str = "B2B"
    strategy_notes: str = ""
    template_mode: str = "template"
    email_length: str = "concise"          # short | concise | long | professional
    what_to_sell: str = ""
    what_to_avoid: str = ""
    target_focus: str = ""
    target_country: str = ""
    followup_1_hours: int = Field(default=24, ge=0, le=720)
    followup_2_hours: int = Field(default=48, ge=0, le=720)
    followup_3_hours: int = Field(default=72, ge=0, le=720)
    followup_max_days: int = Field(default=30, ge=0, le=365)   # no reply for N days -> Garbage
    # Days-wise + count-wise follow-up plan. e.g. followup_plan="3,7,14" means
    # nudge on day 3, then 7, then 14; followup_count caps how many go out.
    # Leave the plan empty to keep the legacy followup_N_hours stage timing.
    followup_plan: str = ""
    followup_count: int = Field(default=3, ge=0, le=20)
    followup_memory: bool = True          # follow-ups read the real thread
    # "Not interested" -> agent goes silent, lead parks in Garbage, then purges.
    not_interested_action: str = "garbage"      # garbage | close
    not_interested_retention_days: int = Field(default=30, ge=0, le=3650)  # 0 = keep forever
    # The AI never answers pricing / contract / legal / security on its own.
    pricing_policy: str = "escalate"            # escalate | reply
    first_email_length: str = ""                # short | medium | long (overrides agent)
    demo_offer: bool = True                     # offer a live realtime demo
    # 3 is the house rule; subjects.subject_word_cap() clamps it at send time.
    # The upper bound stays loose on purpose so an older campaign still holding
    # 4 can be saved again without a validation error.
    subject_max_words: int = Field(default=3, ge=1, le=4)
    # ── WHAT ARE YOU OFFERING? ───────────────────────────────────────────────
    # Reality-based description of the service (never a sales pitch) + the
    # delivery model in plain text.
    offering: str = ""
    delivery_model: str = ""
    ideal_customer: str = ""
    platform_rules: str = ""                    # "" = the built-in platform rules
    no_pricing: bool = True                     # never mention pricing
    cta_enabled: bool = True                    # end on the booking link
    booking_link: str = ""                      # "" = use the agent's meeting URL
    # FOLLOW-UP SCHEDULE — days from Monday to Sunday + time of day (UTC).
    followup_days: str = ""                     # "" = any day of the week
    followup_time: str = ""                     # "" = any time of day
    # SELECTION BOX — which parts of the agent this campaign drives. "" = all.
    agent_parts: str = ""
    agent_id: int

    @field_validator("strategy")
    @classmethod
    def strat_ok(cls, v):
        assert v in {"B2B", "B2C", "ABM", "custom", "C2C", "C2B", "B2G", "G2C",
                     "B2B2C", "B2B2B", "D2C", "D2B", "SMB", "SME", "Enterprise"}
        return v

    @field_validator("template_mode")
    @classmethod
    def tm_ok(cls, v):
        assert v in {"template", "plain"}
        return v

    @field_validator("not_interested_action")
    @classmethod
    def ni_ok(cls, v):
        assert v in {"garbage", "close"}
        return v

    @field_validator("pricing_policy")
    @classmethod
    def price_ok(cls, v):
        assert v in {"escalate", "reply"}
        return v

    @field_validator("first_email_length")
    @classmethod
    def fel_ok(cls, v):
        assert v in {"", "short", "medium", "long"}
        return v

    @field_validator("followup_plan")
    @classmethod
    def plan_ok(cls, v):
        # Accepts "3,7,14" / "3, 7, 14" / fractional days. Reject anything that
        # is not a list of non-negative day offsets, so a typo cannot silently
        # disable follow-ups.
        raw = (v or "").replace(";", ",").strip()
        if not raw:
            return ""
        days = []
        for part in raw.split(","):
            part = part.strip().rstrip("dD").strip()
            if not part:
                continue
            val = float(part)          # raises on junk
            assert 0 <= val <= 365, "each follow-up day must be 0-365"
            days.append(val)
        assert days, "follow-up plan has no usable day offsets"
        return raw

    @field_validator("followup_days")
    @classmethod
    def fd_ok(cls, v):
        """Which days a follow-up may go out: mon..sun, any separator.
        '' means every day (the default, and what older campaigns behave like)."""
        from .services.agent_settings import ALL_DAYS
        raw = (v or "").replace(";", ",").strip()
        if not raw:
            return ""
        keep = []
        for part in raw.split(","):
            part = part.strip().lower()[:3]
            if part in ALL_DAYS and part not in keep:
                keep.append(part)
        assert keep, "follow-up days must include at least one of mon..sun"
        return ",".join(keep)

    @field_validator("followup_time")
    @classmethod
    def ft_ok(cls, v):
        """Time of day (HH:MM, UTC) a follow-up may go out. '' = any time."""
        raw = (v or "").strip()
        if not raw:
            return ""
        assert len(raw) == 5 and raw[2] == ":", "follow-up time must look like 09:30"
        hh, mm = int(raw[0:2]), int(raw[3:5])
        assert 0 <= hh <= 23 and 0 <= mm <= 59, "follow-up time must be a real time"
        return f"{hh:02d}:{mm:02d}"

    @field_validator("agent_parts")
    @classmethod
    def ap_ok(cls, v):
        """The campaign-to-agent selection box. '' = every part (the default),
        otherwise only the named parts are driven by this campaign."""
        from .services.agent_settings import PART_KEYS, parse_parts
        raw = (v or "").strip()
        if not raw:
            return ""
        items = [p.strip().lower() for p in raw.replace(";", ",").split(",") if p.strip()]
        unknown = [p for p in items if p not in PART_KEYS]
        assert not unknown, f"unknown agent part(s): {', '.join(unknown)}"
        chosen = [k for k in PART_KEYS if k in parse_parts(raw)]
        assert chosen, "select at least one part of the agent"
        return ",".join(chosen)
 
 
class BatchOut(BaseModel):
    id: int
    number: int
    total: int
    sent: int
    failed: int
    status: str
    source_filename: str = ""
    created_at: datetime
    completed_at: Optional[datetime]
    class Config:
        from_attributes = True
 
 
class CampaignOut(CampaignCreate):
    id: int
    status: str
    created_at: datetime
    batches: List[BatchOut] = []
    class Config:
        from_attributes = True
 
 
class LeadOut(BaseModel):
    id: int
    name: str
    email: str
    company: str
    title: str
    phone: str
    website: str
    country: str
    source: str
    status: str
    temperature: str
    confidence: int
    priority: float
    company_research: str
    pain_points: str
    email_verified: bool
    followups_sent: int
    last_outbound_at: Optional[datetime]
    last_inbound_at: Optional[datetime]
    agent_id: Optional[int]
    agent_name: str = ""
    agent_active: bool = True              # is the owning agent live right now
    locked_until: Optional[datetime] = None   # if another agent emailed this lead today
    campaign_id: Optional[int]
    batch_id: Optional[int]
    # a human has to answer this — thread stays in Messages, agent is silent
    needs_human: bool = False
    needs_human_reason: str = ""
    # they said not interested — parked in Garbage, purged after retention
    not_interested: bool = False
    not_interested_at: Optional[datetime] = None
    not_interested_note: str = ""
    garbage_at: Optional[datetime] = None
    last_outbound_subject: str = ""
    escalated: bool = False
    escalation_reason: str = ""
    class Config:
        from_attributes = True
 
 
class MessageOut(BaseModel):
    id: int
    lead_id: Optional[int]
    agent_id: Optional[int]
    direction: str
    sent_by: str
    from_addr: str = ""
    subject: str
    body: str
    html_used: bool
    is_spam: bool
    spam_reason: str
    created_at: datetime
    class Config:
        from_attributes = True
 
 
class ManualSend(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
 
 
class TemplateCreate(BaseModel):
    name: str
    length: str = "medium"
    body: str
    agent_id: Optional[int] = None
 
 
class TemplateOut(TemplateCreate):
    id: int
    class Config:
        from_attributes = True
 
 
class KnowledgeCreate(BaseModel):
    title: str
    content: str
    agent_id: Optional[int] = None      # None = shared with all agents
 
 
class KnowledgeOut(KnowledgeCreate):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True
 
 
class EnrollIn(BaseModel):
    lead_ids: List[int]
    campaign_id: int
    agent_id: Optional[int] = None
 
 
class EnrollByFilter(BaseModel):
    """Enroll EVERY lead matching the current Leads-page filter (select-all
    across all pages) — no need to send 50k IDs from the browser."""
    campaign_id: int
    agent_id: Optional[int] = None          # agent to enroll them WITH
    # the same filters the /paged list uses, so 'what you see' == 'what enrolls'
    status: Optional[str] = None
    filter_agent_id: Optional[int] = None   # filter: only leads currently on this agent
    unverified_only: bool = False
    unassigned_only: bool = False
    # Same two chips the /paged list uses, so 'what you see' == 'what enrolls'.
    needs_human_only: bool = False
    not_interested_only: bool = False
    q: str = ""
    max_leads: int = 20000
 
 
class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    agent_id: Optional[int] = None
    agent_name: str = ""
    read: bool
    created_at: datetime
    class Config:
        from_attributes = True
 
 
class PitchOut(BaseModel):
    id: int
    lead_id: Optional[int]
    agent_id: Optional[int]
    lead_name: str
    company: str
    phone: str
    country: str
    summary: str
    transcript: str
    created_at: datetime
    class Config:
        from_attributes = True
