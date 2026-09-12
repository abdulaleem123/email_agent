import enum
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Text, Boolean, DateTime,
                        Float, ForeignKey, Enum, UniqueConstraint, Index)
from sqlalchemy.orm import relationship
from .database import Base


class Tone(str, enum.Enum):
    professional = "professional"
    friendly = "friendly"
    casual = "casual"
    formal = "formal"


class MsgLength(str, enum.Enum):
    short = "short"
    medium = "medium"
    long = "long"


class Temperature(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"


class LeadStatus(str, enum.Enum):
    new = "new"
    enrolled = "enrolled"
    contacted = "contacted"
    replied = "replied"
    meeting = "meeting"
    closed = "closed"
    garbage = "garbage"


class BatchStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"     # shows green in UI
    paused = "paused"


# ---------------------------------------------------------------- auth
class User(Base):
    """Single admin user, seeded from .env. No public registration."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    is_admin = Column(Boolean, default=True)
    is_superadmin = Column(Boolean, default=False)   # usage + API keys pages
    failed_logins = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)      # brute-force lockout
    created_at = Column(DateTime, default=datetime.utcnow)


class OtpCode(Base):
    """Email OTP for 2-step login."""
    __tablename__ = "otp_codes"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    code_hash = Column(String(200), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------- agents
class Agent(Base):
    """Persona-driven agents: Osaja (sales), Saif (co-founder), Aleem (tech AI
    freelancer), Dawood (fullstack solo dev). Each has its OWN knowledge base,
    inbox, persona prompt, delays and daily cap."""
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    role = Column(String(120), default="")               # e.g. "Senior Sales Strategist"
    avatar_url = Column(String(500), default="")
    description = Column(Text, default="")
    persona_prompt = Column(Text, default="")            # how THIS agent writes & pitches
    pitch_style = Column(Text, default="")               # extra sales-psychology notes
    tone = Column(Enum(Tone), default=Tone.professional)
    message_length = Column(Enum(MsgLength), default=MsgLength.medium)
    project_url = Column(String(500), default="")
    meeting_url = Column(String(500), default="")        # Calendly
    signature = Column(Text, default="")                 # Best regards, ... block
    daily_send_limit = Column(Integer, default=150)
    outbound_delay_min = Column(Integer, default=60)     # 1 min
    outbound_delay_max = Column(Integer, default=300)    # 5 min
    reply_delay_seconds = Column(Integer, default=900)   # inbound reply ~15 min
    followup_after_hours = Column(Integer, default=None)  # None = use global setting   
    # --- per-agent mailbox: each agent sends/receives from its OWN email ---
    smtp_host = Column(String(200), default="")          # e.g. smtp.gmail.com / smtp.hostinger.com
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String(320), default="")
    smtp_password = Column(String(300), default="")      # Gmail App Password / Hostinger password
    smtp_from = Column(String(320), default="")          # usually same as smtp_user
    imap_host = Column(String(200), default="")          # imap.gmail.com / imap.hostinger.com
    imap_port = Column(Integer, default=993)
    imap_user = Column(String(320), default="")
    imap_password = Column(String(300), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    leads = relationship("Lead", back_populates="agent")
    campaigns = relationship("Campaign", back_populates="agent")
    knowledge = relationship("KnowledgeDoc", back_populates="agent")


# ---------------------------------------------------------------- campaigns
class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    goal = Column(Text, default="")
    strategy = Column(String(20), default="B2B")         # B2B | B2C | ABM | custom
    template_mode = Column(String(20), default="template")  # template | plain
    batch_size = Column(Integer, default=20)             # 20–50
    industry = Column(String(120), default="")           # target industry
    email_length = Column(String(20), default="concise") # short|concise|long|professional
    what_to_sell = Column(Text, default="")              # products/services to pitch
    what_to_avoid = Column(Text, default="")             # never mention / off-limits
    target_focus = Column(Text, default="")              # pain focus e.g. "support automation"
    target_country = Column(String(100), default="")     # override lead country for psychology
    pain_focus = Column(Text, default="")                # which pains to target (country/target wise)
    sell_points = Column(Text, default="")               # WHAT to sell / emphasise
    avoid_points = Column(Text, default="")              # what NOT to mention
    status = Column(String(20), default="active")        # active | paused
    agent_id = Column(Integer, ForeignKey("agents.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="campaigns")
    leads = relationship("Lead", back_populates="campaign")
    batches = relationship("Batch", back_populates="campaign",
                           cascade="all, delete-orphan")


class Batch(Base):
    """Campaign leads are sent in batches of 20–50; completed shows green."""
    __tablename__ = "batches"
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    number = Column(Integer, default=1)
    total = Column(Integer, default=0)
    sent = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    status = Column(Enum(BatchStatus), default=BatchStatus.pending)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    campaign = relationship("Campaign", back_populates="batches")
    leads = relationship("Lead", back_populates="batch")


# ---------------------------------------------------------------- leads
class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), default="")               # person name
    email = Column(String(320), index=True, nullable=False)
    company = Column(String(300), default="")
    title = Column(String(200), default="")
    phone = Column(String(60), default="")
    website = Column(String(500), default="")
    country = Column(String(100), default="")            # drives email psychology
    source = Column(String(100), default="excel")
    status = Column(Enum(LeadStatus), default=LeadStatus.new)
    temperature = Column(Enum(Temperature), default=Temperature.cold)
    confidence = Column(Integer, default=20)
    priority = Column(Float, default=0.0, index=True)
    company_research = Column(Text, default="")          # DuckDuckGo web research
    pain_points = Column(Text, default="")               # extracted pain points
    email_verified = Column(Boolean, default=False)      # MX check passed (red row if False)
    unsubscribed = Column(Boolean, default=False)         # honor List-Unsubscribe -> never email again
    unsub_token = Column(String(64), default="", unique=False)  # public no-auth unsub link token
    ai_paused = Column(Boolean, default=False)           # human takeover on this thread
    pitch_done = Column(Boolean, default=False, index=True)  # marked done in Pitch Decker
    upload_tag = Column(String(200), default="", index=True)  # which excel sheet it came from
    followups_sent = Column(Integer, default=0)
    last_outbound_at = Column(DateTime, nullable=True)
    last_inbound_at = Column(DateTime, nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="leads")
    campaign = relationship("Campaign", back_populates="leads")
    batch = relationship("Batch", back_populates="leads")
    messages = relationship("EmailMessage", back_populates="lead",
                            order_by="EmailMessage.created_at",
                            cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("email", name="uq_lead_email"),)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), index=True, nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    direction = Column(String(10))                       # in | out
    sent_by = Column(String(10), default="agent")        # agent | user
    from_addr = Column(String(320), default="")
    subject = Column(String(500), default="")
    body = Column(Text, default="")
    html_used = Column(Boolean, default=False)           # template (HTML+logo) vs plain
    is_spam = Column(Boolean, default=False)
    spam_reason = Column(String(300), default="")
    message_id = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    lead = relationship("Lead", back_populates="messages")


class Template(Base):
    __tablename__ = "templates"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    length = Column(Enum(MsgLength), default=MsgLength.medium)
    body = Column(Text, nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)  # None = shared
    created_at = Column(DateTime, default=datetime.utcnow)


class TemplateUse(Base):
    __tablename__ = "template_uses"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), index=True)
    template_id = Column(Integer, ForeignKey("templates.id"))
    __table_args__ = (UniqueConstraint("lead_id", "template_id", name="uq_lead_template"),)


class KnowledgeDoc(Base):
    """PER-AGENT knowledge base: each doc belongs to exactly one agent
    (or agent_id NULL = shared across all)."""
    __tablename__ = "knowledge_docs"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="knowledge")


class Notification(Base):
    """Dashboard notifications: replies received, batch completed, dedupe
    reschedules, daily-limit hits, etc."""
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    kind = Column(String(40), default="info")            # info | reply | batch | warn
    title = Column(String(300), default="")
    body = Column(Text, default="")
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ApiUsage(Base):
    """Every LLM / embedding / search call recorded for the super-admin
    usage dashboard (real-time input/output tokens + cost, per agent)."""
    __tablename__ = "api_usage"
    id = Column(Integer, primary_key=True)
    provider = Column(String(20), index=True)            # openai | duckduckgo
    kind = Column(String(30), default="chat")            # chat | embedding | search | moderation
    model = Column(String(80), default="")
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ResearchCache(Base):
    """Web research cached by email/company-domain: one research per lead
    EVER — a second campaign or agent reuses the cache, zero extra credits."""
    __tablename__ = "research_cache"
    id = Column(Integer, primary_key=True)
    cache_key = Column(String(360), unique=True, index=True)   # email or domain
    research = Column(Text, default="")
    pain_points = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class KbChunk(Base):
    """Embedded knowledge chunks (per agent). Embedding stored as JSON list;
    on Postgres a pgvector column is added by embeddings.ensure_pgvector()."""
    __tablename__ = "kb_chunks"
    id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, ForeignKey("knowledge_docs.id"), index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Text, default="")                 # JSON floats (fallback store)
    created_at = Column(DateTime, default=datetime.utcnow)


class SettingKV(Base):
    """Runtime toggles editable from the Settings page (override .env defaults)."""
    __tablename__ = "settings_kv"
    key = Column(String(100), primary_key=True)
    value = Column(String(500), default="")


class AuditLog(Base):
    """Who did what, when. Covers sensitive/destructive admin actions:
    login attempts, API key changes, campaign/lead/mail-record deletes,
    agent pause/resume, quota changes. Not exhaustive of every read
    endpoint (that would be noise) — focused on actions with real
    consequences."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_email = Column(String(255), default="")       # denormalized so it survives user deletion
    action = Column(String(80), nullable=False)          # e.g. "login_failed", "campaign.delete"
    target_type = Column(String(60), default="")
    target_id = Column(String(60), default="")
    detail = Column(Text, default="")
    ip_address = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PitchRecord(Base):
    """A generated sales-call TRANSCRIPT (pitch) for a lead, produced by the
    Pitch Decker: Osaja researches the lead (cached DuckDuckGo) and role-plays a
    region-aware sales conversation that ends in the client agreeing. Stored
    so the team can review how a strong pitch would go."""
    __tablename__ = "pitch_records"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), index=True, nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    lead_name = Column(String(200), default="")
    company = Column(String(300), default="")
    phone = Column(String(60), default="")
    country = Column(String(100), default="")
    summary = Column(Text, default="")                   # short, concise recap
    transcript = Column(Text, default="")                # the full role-play
    created_at = Column(DateTime, default=datetime.utcnow, index=True)