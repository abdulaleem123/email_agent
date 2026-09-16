from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator
 
 
class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = ""
    avatar_url: str = ""
    description: str = ""
    persona_prompt: str = ""
    pitch_style: str = ""
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
    template_mode: str = "template"
    batch_size: int = Field(default=50, ge=10, le=2000)   # scale up for 20k–50k lead sets
    email_length: str = "concise"          # short | concise | long | professional
    what_to_sell: str = ""
    what_to_avoid: str = ""
    target_focus: str = ""
    target_country: str = ""
    agent_id: int
 
    @field_validator("strategy")
    @classmethod
    def strat_ok(cls, v):
        assert v in {"B2B", "B2C", "ABM", "custom"}
        return v
 
    @field_validator("template_mode")
    @classmethod
    def tm_ok(cls, v):
        assert v in {"template", "plain"}
        return v
 
 
class BatchOut(BaseModel):
    id: int
    number: int
    total: int
    sent: int
    failed: int
    status: str
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
    locked_until: Optional[datetime] = None   # if another agent emailed this lead today
    campaign_id: Optional[int]
    batch_id: Optional[int]
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
